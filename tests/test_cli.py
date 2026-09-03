import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import call, patch

from avd_flow.cli import (
    INVENTORY_MESSAGE,
    anta,
    build_project,
    cv_deploy,
    init_project,
    main,
)


class InitTest(unittest.TestCase):
    def test_creates_project_with_empty_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fabric"
            output = io.StringIO()

            with redirect_stdout(output):
                main(["init", str(root), "--avd-version", "6.3.0"])

            self.assertIn(
                '"pyavd[ansible]==6.3.0"', (root / "pyproject.toml").read_text()
            )
            self.assertIn(
                "community.general", (root / "collection-requirements.yml").read_text()
            )
            self.assertIn(
                "callbacks_enabled = profile_roles, profile_tasks, timer",
                (root / "ansible.cfg").read_text(),
            )
            self.assertNotIn("global_vars", (root / "ansible.cfg").read_text())
            self.assertTrue((root / "playbooks" / "cv_deploy.yml").is_file())
            self.assertTrue((root / "playbooks" / "anta_runner.yml").is_file())
            self.assertEqual([], list((root / "inventory").iterdir()))
            self.assertIn(INVENTORY_MESSAGE, output.getvalue())

    def test_enables_global_vars_with_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fabric"

            init_project(
                path=root, avd_version="6.3.0", global_vars_path=Path("../global_vars")
            )

            config = (root / "ansible.cfg").read_text()
            self.assertIn(
                "vars_plugins_enabled = arista.avd.global_vars, host_group_vars", config
            )
            self.assertIn("paths = ../global_vars", config)

    def test_force_reinitializes_without_removing_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fabric"
            main(["init", str(root), "--avd-version", "6.3.0"])
            inventory = root / "inventory" / "inventory.yml"
            inventory.write_text("all:\n")

            main(["init", str(root), "--avd-version", "6.4.0", "--force"])

            self.assertIn(
                '"pyavd[ansible]==6.4.0"', (root / "pyproject.toml").read_text()
            )
            self.assertEqual("all:\n", inventory.read_text())


class BuildTest(unittest.TestCase):
    def test_builds_with_required_collections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory" / "inventory.yml"
            inventory.parent.mkdir()
            inventory.touch()
            (root / "collection-requirements.yml").touch()
            (root / ".env").write_text("FROM_DOTENV=loaded\nEXISTING_VALUE=from-file\n")
            results = [
                CompletedProcess([], 0, ""),
                CompletedProcess([], 0, "6.3.0\n"),
                CompletedProcess([], 0, ""),
                CompletedProcess([], 0, ""),
                CompletedProcess([], 0, ""),
            ]

            with (
                patch("avd_flow.cli.Path.cwd", return_value=root),
                patch("avd_flow.cli.shutil.which", return_value="/usr/bin/uv"),
                patch("avd_flow.cli.subprocess.run", side_effect=results) as run,
                patch.dict(
                    os.environ, {"EXISTING_VALUE": "from-environment"}, clear=True
                ),
            ):
                build_project(
                    inventory_path=Path("inventory/inventory.yml"), sanitize=True
                )

            self.assertEqual(
                call(
                    [
                        "/usr/bin/uv",
                        "run",
                        "ansible-galaxy",
                        "collection",
                        "install",
                        "arista.avd:==6.3.0",
                        "ansible.posix",
                        "--collections-path",
                        ".ansible/collections",
                    ],
                    cwd=root,
                    check=True,
                    text=True,
                ),
                run.call_args_list[2],
            )
            self.assertEqual(
                call(
                    [
                        "/usr/bin/uv",
                        "run",
                        "ansible-galaxy",
                        "collection",
                        "install",
                        "--requirements-file",
                        "collection-requirements.yml",
                        "--collections-path",
                        ".ansible/collections",
                    ],
                    cwd=root,
                    check=True,
                    text=True,
                ),
                run.call_args_list[3],
            )
            environment = run.call_args_list[4].kwargs["env"]
            self.assertEqual(
                ["/usr/bin/uv", "run", "--env-file", ".env"],
                run.call_args_list[4].args[0][:4],
            )
            self.assertEqual("from-environment", environment["EXISTING_VALUE"])
            self.assertEqual("true", environment["SANITIZE"])

    def test_skips_missing_collection_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory" / "inventory.yml"
            inventory.parent.mkdir()
            inventory.touch()
            results = [
                CompletedProcess([], 0, ""),
                CompletedProcess([], 0, "6.3.0\n"),
                CompletedProcess([], 0, ""),
                CompletedProcess([], 0, ""),
            ]

            with (
                patch("avd_flow.cli.Path.cwd", return_value=root),
                patch("avd_flow.cli.shutil.which", return_value="/usr/bin/uv"),
                patch("avd_flow.cli.subprocess.run", side_effect=results) as run,
            ):
                build_project()

            self.assertFalse(
                any(
                    "--requirements-file" in item.args[0] for item in run.call_args_list
                )
            )

    def test_builds_without_initialized_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory.yml"
            inventory.touch()
            (root / ".env").write_text("BUILD_OUTPUT_DIR=output\n")
            results = [
                CompletedProcess([], 0, ""),
                CompletedProcess([], 0, "6.3.0\n"),
                CompletedProcess([], 0, ""),
                CompletedProcess([], 0, ""),
                CompletedProcess([], 0, ""),
            ]

            with (
                patch("avd_flow.cli.Path.cwd", return_value=root),
                patch("avd_flow.cli.shutil.which", return_value="/usr/bin/uv"),
                patch("avd_flow.cli.subprocess.run", side_effect=results) as run,
            ):
                build_project(inventory_path=Path("inventory.yml"), avd_version="6.3.0")

            build = run.call_args_list[-1]
            self.assertEqual(root, build.kwargs["cwd"])
            self.assertEqual(
                str(root / ".env"),
                build.args[0][build.args[0].index("--env-file") + 1],
            )
            self.assertEqual(str(inventory.resolve()), build.args[0][-1])
            self.assertIn("--project", build.args[0])
            self.assertNotEqual(
                root / "ansible.cfg", Path(build.kwargs["env"]["ANSIBLE_CONFIG"])
            )
            self.assertFalse((root / "pyproject.toml").exists())


class DeployTest(unittest.TestCase):
    def test_runs_cv_deploy_playbook(self) -> None:
        inventory = Path("inventory/inventory.yml")
        with patch("avd_flow.cli.run_playbook") as run_playbook:
            cv_deploy(inventory)

        run_playbook.assert_called_once_with("playbooks/cv_deploy.yml", inventory)


class AntaTest(unittest.TestCase):
    def test_runs_anta_playbook(self) -> None:
        inventory = Path("inventory/inventory.yml")
        with patch("avd_flow.cli.run_playbook") as run_playbook:
            anta(inventory)

        run_playbook.assert_called_once_with("playbooks/anta_runner.yml", inventory)


if __name__ == "__main__":
    unittest.main()
