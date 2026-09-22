# avd-flow

Small Python CLI for bootstrapping and building Arista AVD inventory projects.

## Install from a private Git repository

```shell
uv tool install 'git+ssh://git@github.com/dlobato/avd-flow.git'
```

The SSH key and repository access remain managed by Git. Update from the same
repository and branch recorded during installation with `uv`:

```shell
uv tool upgrade avd-flow
```

## Create a project

```shell
avd-flow init my-fabric --avd-version 6.3.0
```

The command creates a standard `pyproject.toml`, collection requirements,
`.gitignore`, and an empty `inventory/` directory. Standard Ansible configuration
and playbooks ship with `avd-flow` instead of being copied into every project.
Add `inventory/inventory.yml` and its variable files before building. Use
`--force` to refresh generated project files without removing inventory files.

## Build configurations

```shell
cd my-fabric
avd-flow build
```

From a parent directory, use `avd-flow -C my-fabric build`. Run
`avd-flow prepare` to install project dependencies and collections without
building; `--no-sync` installs only collections into an environment that was
already synchronized with standard Python tooling.

Use `avd-flow build --sanitize` to hide passwords in generated configurations,
`avd-flow build --digital-twin` to generate digital-twin artifacts, or
`--inventory PATH` to select a different inventory file.
By default, commands ignore an unrelated active virtual environment and use the
project's `.venv`. Pass `--active` to a workflow command to use it.

Build an inventory without initializing a project by selecting the AVD version:

```shell
avd-flow build --avd-version 6.3.0 --inventory inventory.yml
```

This uses the packaged project resources in a temporary directory. The inventory,
its variable files, `.env`, and generated output remain in the current project.

Deploy generated configurations to CloudVision:

```shell
avd-flow cv-deploy
```

Use `avd-flow cv-deploy --digital-twin` for the digital-twin artifacts, or
deploy them directly over eAPI with `avd-flow eapi-deploy`. Validate generated
configurations in an abandoned CloudVision workspace without submitting them:

```shell
avd-flow cv-validate
```

Run the inventory's ANTA tests against hardware:

```shell
avd-flow anta
```

Use `avd-flow anta --digital-twin` to validate the digital twin. Build, deploy,
and validation commands accept `--vault-id` and pass it to Ansible.

## Reuse a prepared CI environment

Set `VIRTUAL_ENV` to an activated, prebuilt environment and opt into read-only
reuse once for the CI image:

```shell
export VIRTUAL_ENV=/runtime-home/.venv
export PATH="$VIRTUAL_ENV/bin:$PATH"
export AVD_FLOW_ENVIRONMENT=prepared
```

Prepared mode verifies the project's exact PyAVD pin and matching `arista.avd`
collection, then runs with `uv --active --no-sync`. It does not synchronize the
environment or install collections in individual jobs.

## Use a `.env` file

Create `.env` in the initialized project directory and run commands from that
directory. Workflow commands load it automatically; `init` does not use it.
Only add the values needed by the command you run, for example:

```dotenv
FABRIC_INVENTORY_GROUP=FABRIC
BUILD_OUTPUT_DIR=inventory
CV_DEPLOY_SERVER=cv.example.com
CV_DEPLOY_TOKEN=replace-me
CV_VERIFY_CERTS=true
WORKSPACE_NAME=avd-flow
WORKSPACE_DESCRIPTION=Deploy configurations from avd-flow
WORKSPACE_REQUESTED_STATE=abandoned
CHANGE_CONTROL_DESCRIPTION=Deploy configurations from avd-flow
EAPI_USER=admin
EAPI_PASSWORD=replace-me
EAPI_ENABLE_PASSWORD=replace-me
```

| Command | Supported values |
| --- | --- |
| `build` | `FABRIC_INVENTORY_GROUP` (default: `FABRIC`), `BUILD_OUTPUT_DIR` (default: the inventory directory), `SANITIZE` (default: `false`; `--sanitize` sets it to `true`) |
| `cv-deploy` | `FABRIC_INVENTORY_GROUP` (default: `FABRIC`), `CV_VERIFY_CERTS` (default: `true`), `WORKSPACE_NAME`, `WORKSPACE_DESCRIPTION`, `CHANGE_CONTROL_DESCRIPTION` |
| `cv-validate` | `FABRIC_INVENTORY_GROUP` (default: `FABRIC`), `CV_DEPLOY_SERVER`, `CV_DEPLOY_TOKEN`, `CV_VERIFY_CERTS` (default: `true`), `WORKSPACE_ID`, `WORKSPACE_NAME`, `WORKSPACE_DESCRIPTION`, `WORKSPACE_REQUESTED_STATE` (default: `abandoned`) |
| `anta` | `FABRIC_INVENTORY_GROUP` (default: `FABRIC`), `EAPI_USER`, `EAPI_PASSWORD`, `EAPI_ENABLE_PASSWORD` (default: `EAPI_PASSWORD`) |

Exported environment variables take precedence over `.env`. The generated
`.gitignore` excludes `.env`; keep it uncommitted because it may contain secrets.

## Packaged resources

Standard Ansible configuration and playbooks live in
`src/avd_flow/resources/`. Projects keep their Python dependencies in
`pyproject.toml` and may add Ansible collections to
`collection-requirements.yml`. Custom playbooks remain normal Ansible workflows;
set `ANSIBLE_CONFIG` when a project needs its own Ansible configuration or
plugins.

## Development checks

```shell
make help
make format
make check
make mypy
make build
make pre-commit-install
make pre-commit-run
```

Wheel versions derive from Git tags, commit distance, and the short commit hash.
