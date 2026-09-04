import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import Any

VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+!-]*\Z")
INVENTORY_MESSAGE = (
    "Add inventory/inventory.yml and variable files before running avd-flow build."
)
RESOURCE_FILES = {
    "pyproject.toml.template": "pyproject.toml",
    "collection-requirements.yml": "collection-requirements.yml",
    "ansible.cfg": "ansible.cfg",
    "playbooks/fabric-build.yml": "playbooks/fabric-build.yml",
    "playbooks/cv_deploy.yml": "playbooks/cv_deploy.yml",
    "playbooks/anta_runner.yml": "playbooks/anta_runner.yml",
    "gitignore": ".gitignore",
}


class CliError(Exception):
    pass


def init_project(
    avd_version: str,
    path: Path | None = None,
    global_vars_path: Path | None = None,
    force: bool = False,
    quiet: bool = False,
) -> None:
    if not VERSION_PATTERN.fullmatch(avd_version):
        raise CliError(f"invalid AVD version: {avd_version!r}")
    global_vars = str(global_vars_path) if global_vars_path is not None else None
    if global_vars is not None and ("\n" in global_vars or "\r" in global_vars):
        raise CliError("global vars path must not contain newlines")

    root = path or Path.cwd()
    project_name = (
        re.sub(r"[^a-z0-9]+", "-", root.absolute().name.lower()).strip("-")
        or "avd-project"
    )
    resource_root = files("avd_flow.resources")
    project_files = {
        root / destination: resource_root.joinpath(*source.split("/"))
        for source, destination in RESOURCE_FILES.items()
    }
    existing = [str(path) for path in project_files if path.exists()]
    if existing and not force:
        raise CliError(f"refusing to overwrite: {', '.join(existing)}")

    for output_path, resource in project_files.items():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            resource.read_text()
            .replace("__AVD_VERSION__", avd_version)
            .replace("__PROJECT_NAME__", project_name)
        )
        if output_path.name == "ansible.cfg":
            global_vars_config = ""
            if global_vars is not None:
                global_vars_config = (
                    resource_root.joinpath("global-vars.cfg.template")
                    .read_text()
                    .replace("__GLOBAL_VARS_PATH__", global_vars)
                )
            content = content.replace("__GLOBAL_VARS_CONFIG__", global_vars_config)
        output_path.write_text(content)
    (root / "inventory").mkdir(parents=True, exist_ok=True)

    if not quiet:
        print(f"Initialized AVD {avd_version} project in {root}")
        print(INVENTORY_MESSAGE)


def run(
    command: list[str], root: Path, active: bool = False, **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    environment = kwargs.get("env", os.environ)
    if not active and "VIRTUAL_ENV" in environment:
        kwargs["env"] = environment.copy()
        kwargs["env"].pop("VIRTUAL_ENV")
    return subprocess.run(command, cwd=root, check=True, text=True, **kwargs)


def prepare_project(
    inventory_path: Path, root: Path | None = None, active: bool = False
) -> tuple[Path, str]:
    root = root or Path.cwd()
    inventory = root / inventory_path
    if not inventory.is_file():
        raise CliError(f"{inventory_path} not found. {INVENTORY_MESSAGE}")

    uv = shutil.which("uv")
    if uv is None:
        raise CliError(
            "uv is required: https://docs.astral.sh/uv/getting-started/installation/"
        )

    active_argument = ["--active"] if active else []
    run([uv, "sync", *active_argument], root, active=active)
    installed_version = run(
        [
            uv,
            "run",
            *active_argument,
            "python",
            "-c",
            'from importlib.metadata import version; print(version("pyavd").replace(".dev", "-dev"))',
        ],
        root,
        active=active,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    run(
        [
            uv,
            "run",
            *active_argument,
            "ansible-galaxy",
            "collection",
            "install",
            f"arista.avd:=={installed_version}",
            "ansible.posix",
            "--collections-path",
            ".ansible/collections",
        ],
        root,
        active=active,
    )
    if (root / "collection-requirements.yml").is_file():
        run(
            [
                uv,
                "run",
                *active_argument,
                "ansible-galaxy",
                "collection",
                "install",
                "--requirements-file",
                "collection-requirements.yml",
                "--collections-path",
                ".ansible/collections",
            ],
            root,
            active=active,
        )

    return root, uv


def run_playbook(
    playbook: str,
    inventory_path: Path,
    environment_overrides: dict[str, str] | None = None,
    root: Path | None = None,
    env_file: Path | None = None,
    working_directory: Path | None = None,
    active: bool = False,
) -> None:
    root, uv = prepare_project(inventory_path, root, active)
    working_directory = working_directory or root
    env_file_argument = str(env_file) if env_file is not None else ".env"
    env_file = env_file or root / ".env"
    standalone = working_directory != root
    environment = {**os.environ, **(environment_overrides or {})}
    if standalone:
        environment["ANSIBLE_CONFIG"] = str(root / "ansible.cfg")

    run(
        [
            uv,
            "run",
            *(["--active"] if active else []),
            *(["--project", str(root)] if standalone else []),
            *(["--env-file", env_file_argument] if env_file.is_file() else []),
            "ansible-playbook",
            str(root / playbook) if standalone else playbook,
            "--inventory",
            str(inventory_path),
        ],
        working_directory,
        active=active,
        env=environment,
    )


def build_project(
    inventory_path: Path = Path("inventory/inventory.yml"),
    sanitize: bool = False,
    avd_version: str | None = None,
    global_vars_path: Path | None = None,
    active: bool = False,
) -> None:
    environment = {"SANITIZE": "true"} if sanitize else None
    if avd_version is None:
        if global_vars_path is not None:
            raise CliError("--global-vars requires --avd-version")
        run_playbook(
            "playbooks/fabric-build.yml", inventory_path, environment, active=active
        )
        return

    source_root = Path.cwd()
    inventory_path = (source_root / inventory_path).resolve()
    global_vars_path = (
        (source_root / global_vars_path).resolve()
        if global_vars_path is not None
        else None
    )
    with tempfile.TemporaryDirectory(prefix="avd-flow-") as directory:
        root = Path(directory)
        init_project(avd_version, root, global_vars_path, quiet=True)
        run_playbook(
            "playbooks/fabric-build.yml",
            inventory_path,
            environment,
            root,
            source_root / ".env",
            source_root,
            active=active,
        )


def cv_deploy(
    inventory_path: Path = Path("inventory/inventory.yml"),
    active: bool = False,
) -> None:
    run_playbook("playbooks/cv_deploy.yml", inventory_path, active=active)


def anta(
    inventory_path: Path = Path("inventory/inventory.yml"),
    active: bool = False,
) -> None:
    run_playbook("playbooks/anta_runner.yml", inventory_path, active=active)


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(prog="avd-flow")
    commands = command_parser.add_subparsers()
    command_parser.set_defaults(func=command_parser.print_help)

    init = commands.add_parser("init", help="create an AVD project")
    init.add_argument(
        "path", nargs="?", type=Path, default=Path.cwd(), help="project directory"
    )
    init.add_argument("--avd-version", required=True, help="AVD version to install")
    init.add_argument(
        "--force", action="store_true", help="overwrite generated project files"
    )
    init.add_argument(
        "--global-vars",
        dest="global_vars_path",
        type=Path,
        metavar="PATH",
        help="enable AVD global vars from PATH",
    )
    init.set_defaults(func=init_project)

    def add_inventory(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--inventory",
            dest="inventory_path",
            type=Path,
            default=Path("inventory/inventory.yml"),
            metavar="PATH",
            help="inventory file",
        )
        command.add_argument(
            "--active", action="store_true", help="use the active virtual environment"
        )

    build = commands.add_parser("build", help="build device configurations")
    add_inventory(build)
    build.add_argument(
        "--sanitize", action="store_true", help="hide passwords in generated configs"
    )
    build.add_argument(
        "--avd-version", help="AVD version for a build without an initialized project"
    )
    build.add_argument(
        "--global-vars",
        dest="global_vars_path",
        type=Path,
        metavar="PATH",
        help="enable AVD global vars from PATH for a standalone build",
    )
    build.set_defaults(func=build_project)

    deploy = commands.add_parser(
        "cv-deploy", help="deploy configurations to CloudVision"
    )
    add_inventory(deploy)
    deploy.set_defaults(func=cv_deploy)

    validation = commands.add_parser("anta", help="run ANTA validation")
    add_inventory(validation)
    validation.set_defaults(func=anta)

    return command_parser


def main(argv: list[str] | None = None) -> None:
    try:
        arguments = vars(parser().parse_args(argv))
        function = arguments.pop("func")
        function(**arguments)
    except CliError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode or 1) from error
