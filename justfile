# fin-assist task runner

set dotenv-load := false
set shell := ["bash", "-euo", "pipefail", "-c"]

_default:
    @just --list

# ── Dev shell ────────────────────────────────────────────────────────────────

dev:
    devenv shell

# ── Code quality ─────────────────────────────────────────────────────────────

fmt:
    treefmt

check:
    treefmt --ci

lint:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -d src/ ]; then
        uv run ruff check src/
    else
        echo "src/ not found, skipping lint"
    fi

lint-fix:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -d src/ ]; then
        uv run ruff check --fix src/
    else
        echo "src/ not found, skipping lint-fix"
    fi

typecheck:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -d src/ ]; then
        uv run ty check src/
    else
        echo "src/ not found, skipping typecheck"
    fi

test *args:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -d tests/ ]; then
        uv run pytest tests/ {{ args }}
    else
        echo "tests/ not found, skipping tests"
    fi

test-cov:
    uv run pytest tests/ --cov=fin_assist --cov-report=term-missing

ci: check lint typecheck test

# ── Local dev ────────────────────────────────────────────────────────────────

run:
    uv run python -m fin_assist

install-fish:
    mkdir -p ~/.config/fish/conf.d
    mkdir -p ~/.config/fish/functions
    cp fish/conf.d/fin_assist.fish ~/.config/fish/conf.d/
    cp fish/functions/fin_assist.fish ~/.config/fish/functions/

# Install package in dev mode
install-dev:
    uv pip install -e .

# ── Build ────────────────────────────────────────────────────────────────────

build:
    uv build

clean:
    rm -rf dist/ build/ *.egg-info src/*.egg-info
    find . -type d -name __pycache__ -exec rm -rf {} +
    find . -type d -name .pytest_cache -exec rm -rf {} +
    find . -type d -name .ruff_cache -exec rm -rf {} +
