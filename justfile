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
    @test -d src/ && uv run ruff check src/ || echo "src/ not found, skipping lint"

lint-fix:
    @test -d src/ && uv run ruff check --fix src/ || echo "src/ not found, skipping lint-fix"

typecheck:
    @test -d src/ && uv run ty check src/ || echo "src/ not found, skipping typecheck"

test *args:
    @test -d tests/ && uv run pytest tests/ {{ args }} || echo "tests/ not found, skipping tests"

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
