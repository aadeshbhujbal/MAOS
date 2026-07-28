# MAOS developer task runner.
# Each target proxies through `uv run` so the pinned dev toolchain is used.

.PHONY: help install sync lint format type-check test test-property test-unit \
        test-integration check clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install: ## Create the virtualenv and install runtime + dev dependencies
	uv sync --extra dev

sync: install ## Alias for install

lint: ## Run ruff lint checks
	uv run ruff check src tests

format: ## Auto-format with ruff
	uv run ruff format src tests
	uv run ruff check --fix src tests

type-check: ## Run mypy in strict mode
	uv run mypy

test: ## Run the full test suite
	uv run pytest

test-property: ## Run property-based tests only
	uv run pytest tests/property

test-unit: ## Run unit tests only
	uv run pytest tests/unit

test-integration: ## Run integration tests only
	uv run pytest tests/integration

check: lint type-check test ## Run lint, type-check, and tests

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis dist build *.egg-info
