import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from avd_flow.cli import (
    INVENTORY_MESSAGE,
    anta,
    build_project,
    cv_deploy,
    eapi_deploy,
    main,
    prepare,
    run,
)


class InitTest(unittest.TestCase):
    def test_creates_project_with_empty_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "My Fabric"
            output = io.StringIO()

            with redirect_stdout(output):
                main(["init", str(root), "--avd-version", "6.3.0"])

            self.assertIn(
                '"pyavd[ansible]==6.3.0"', (root / "pyproject.toml").read_text()
            )
            self.assertIn('name = "my-fabric"', (root / "pyproject.toml").read_text())
            self.assertIn(
                "community.general", (root / "collection-requirements.yml").read_text()
            )
            self.assertFalse((root / "ansible.cfg").exists())
            self.assertFalse((root / "playbooks").exists())
            self.assertEqual([], list((root / "inventory").iterdir()))
            self.assertIn(INVENTORY_MESSAGE, output.getvalue())

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
    def test_ignores_an_unrequested_active_environment(self) -> None:
        root = Path("/project")
        with (
            patch.dict(
                os.environ,
                {"VIRTUAL_ENV": "/another/project/.venv", "KEEP": "value"},
                clear=True,
            ),
            patch("avd_flow.cli.subprocess.run") as subprocess_run,
        ):
            run(["uv", "sync"], root)

        subprocess_run.assert_called_once_with(
            ["uv", "sync"],
            cwd=root,
            check=True,
            text=True,
            env={"KEEP": "value"},
        )

    def test_uses_the_active_environment_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory" / "inventory.yml"
            inventory.parent.mkdir()
            inventory.touch()
            (root / "pyproject.toml").write_text(
                '[project]\ndependencies = ["pyavd[ansible]==6.3.0"]\n'
            )
            results = [
                CompletedProcess([], 0, ""),
                CompletedProcess([], 0, "6.3.0\n"),
                CompletedProcess([], 0, ""),
                CompletedProcess([], 0, ""),
            ]

            with (
                patch("avd_flow.cli.Path.cwd", return_value=root),
                patch("avd_flow.cli.shutil.which", return_value="/usr/bin/uv"),
                patch(
                    "avd_flow.cli.subprocess.run", side_effect=results
                ) as subprocess_run,
                patch.dict(
                    os.environ, {"VIRTUAL_ENV": "/another/project/.venv"}, clear=True
                ),
            ):
                main(["build", "--active"])

            self.assertTrue(
                all(
                    "--active" in item.args[0] for item in subprocess_run.call_args_list
                )
            )
            self.assertEqual(
                "/another/project/.venv",
                subprocess_run.call_args_list[-1].kwargs["env"]["VIRTUAL_ENV"],
            )

    def test_builds_with_required_collections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory" / "inventory.yml"
            inventory.parent.mkdir()
            inventory.touch()
            (root / "pyproject.toml").write_text(
                '[project]\ndependencies = ["pyavd[ansible]==6.3.0"]\n'
            )
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
                run.call_args_list[2].args[0],
            )
            self.assertEqual(
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
                run.call_args_list[3].args[0],
            )
            self.assertIn("ANSIBLE_LOCAL_TEMP", run.call_args_list[2].kwargs["env"])
            environment = run.call_args_list[4].kwargs["env"]
            self.assertEqual(
                ["/usr/bin/uv", "run", "--env-file", ".env"],
                run.call_args_list[4].args[0][:4],
            )
            self.assertEqual("from-environment", environment["EXISTING_VALUE"])
            self.assertEqual("true", environment["SANITIZE"])
            self.assertEqual(
                "fabric-build.yml", Path(run.call_args_list[4].args[0][-3]).name
            )
            self.assertIn("ANSIBLE_CONFIG", environment)

    def test_skips_missing_collection_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory" / "inventory.yml"
            inventory.parent.mkdir()
            inventory.touch()
            (root / "pyproject.toml").write_text(
                '[project]\ndependencies = ["pyavd[ansible]==6.3.0"]\n'
            )
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

    def test_reuses_a_prepared_active_environment_without_syncing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory" / "inventory.yml"
            inventory.parent.mkdir()
            inventory.touch()
            (root / "pyproject.toml").write_text(
                '[project]\ndependencies = ["pyavd[ansible]==6.3.0"]\n'
            )
            virtual_environment = root / "prepared"
            python = virtual_environment / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.touch()
            results = [
                CompletedProcess([], 0, "6.3.0\n"),
                CompletedProcess(
                    [],
                    0,
                    '{"/usr/share/ansible/collections": '
                    '{"arista.avd": {"version": "6.3.0"}}}\n',
                ),
                CompletedProcess([], 0, ""),
            ]

            with (
                patch("avd_flow.cli.Path.cwd", return_value=root),
                patch("avd_flow.cli.shutil.which", return_value="/usr/bin/uv"),
                patch("avd_flow.cli.subprocess.run", side_effect=results) as run,
                patch.dict(
                    os.environ,
                    {
                        "AVD_FLOW_ENVIRONMENT": "prepared",
                        "VIRTUAL_ENV": str(virtual_environment),
                    },
                    clear=True,
                ),
            ):
                build_project()

            self.assertEqual(3, run.call_count)
            self.assertTrue(
                all(
                    call.args[0][:4] == ["/usr/bin/uv", "run", "--active", "--no-sync"]
                    for call in run.call_args_list
                )
            )
            self.assertFalse(
                any(call.args[0][1] == "sync" for call in run.call_args_list)
            )


class PrepareTest(unittest.TestCase):
    def test_installs_collections_without_syncing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[project]\ndependencies = ["pyavd[ansible]==6.3.0"]\n'
            )
            results = [
                CompletedProcess([], 0, "6.3.0\n"),
                CompletedProcess([], 0, ""),
            ]

            with (
                patch("avd_flow.cli.Path.cwd", return_value=root),
                patch("avd_flow.cli.shutil.which", return_value="/usr/bin/uv"),
                patch("avd_flow.cli.subprocess.run", side_effect=results) as run,
            ):
                prepare(no_sync=True)

            self.assertEqual(2, run.call_count)
            self.assertFalse(
                any(call.args[0][1] == "sync" for call in run.call_args_list)
            )


class DirectoryTest(unittest.TestCase):
    def test_runs_from_selected_directory_and_restores_cwd(self) -> None:
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory)
            visited: list[Path] = []

            with patch(
                "avd_flow.cli.build_project",
                side_effect=lambda **kwargs: visited.append(Path.cwd()),
            ):
                main(["-C", str(selected), "build"])

        self.assertEqual([selected], visited)
        self.assertEqual(original, Path.cwd())


class DeployTest(unittest.TestCase):
    def test_runs_cv_deploy_playbook(self) -> None:
        inventory = Path("inventory/inventory.yml")
        with patch("avd_flow.cli.run_playbook") as run_playbook:
            cv_deploy(inventory)

        run_playbook.assert_called_once_with(
            "cv_deploy.yml", inventory, active=False, vault_id=None
        )

    def test_runs_digital_twin_cv_deploy_playbook(self) -> None:
        inventory = Path("inventory/inventory.yml")
        with patch("avd_flow.cli.run_playbook") as run_playbook:
            cv_deploy(inventory, digital_twin=True, vault_id="default@password")

        run_playbook.assert_called_once_with(
            "cv_deploy_digital_twin.yml",
            inventory,
            active=False,
            vault_id="default@password",
        )

    def test_runs_eapi_deploy_playbook(self) -> None:
        inventory = Path("inventory/inventory.yml")
        with patch("avd_flow.cli.run_playbook") as run_playbook:
            eapi_deploy(inventory)

        run_playbook.assert_called_once_with(
            "eapi_deploy.yml", inventory, active=False, vault_id=None
        )


class AntaTest(unittest.TestCase):
    def test_runs_anta_playbook(self) -> None:
        inventory = Path("inventory/inventory.yml")
        with patch("avd_flow.cli.run_playbook") as run_playbook:
            anta(inventory)

        run_playbook.assert_called_once_with(
            "anta_runner.yml", inventory, active=False, vault_id=None
        )

    def test_runs_digital_twin_anta_playbook(self) -> None:
        inventory = Path("inventory/inventory.yml")
        with patch("avd_flow.cli.run_playbook") as run_playbook:
            anta(inventory, digital_twin=True)

        run_playbook.assert_called_once_with(
            "anta_runner_digital_twin.yml",
            inventory,
            active=False,
            vault_id=None,
        )


if __name__ == "__main__":
    unittest.main()
