.PHONY: help
help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "}; /^[[:alnum:]_-]+:.*## / {printf "%-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: format
format: ## Format Python files
	uv run ruff format

.PHONY: check
check: ## Run Ruff checks
	uv run ruff check .

.PHONY: mypy
mypy: ## Run mypy
	uv run mypy src tests

.PHONY: build
build: ## Build the Python wheel
	uv build --wheel

.PHONY: pre-commit-install
pre-commit-install: ## Install pre-commit hooks
	uv run pre-commit install

.PHONY: pre-commit-run
pre-commit-run: pre-commit-install ## Run pre-commit hooks on all files
	uv run pre-commit run --all-files --show-diff-on-failure
