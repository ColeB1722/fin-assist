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
    uv run ruff check src/

lint-fix:
    uv run ruff check --fix src/

typecheck:
    uv run ty check src/

test *args:
    uv run pytest tests/ {{ args }}

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

# ── Diagrams ─────────────────────────────────────────────────────────────────

# Render README ```mermaid blocks to docs/diagrams/*.svg (+ *.png).
# The README is the single source of truth; each block is named by a preceding
# `<!-- diagram:<slug> -->` comment. Generated files are gitignored.
diagrams:
    python scripts/render_diagrams.py

# Remove generated diagram images.
diagrams-clean:
    rm -f docs/diagrams/*.svg docs/diagrams/*.png

# ── Build ────────────────────────────────────────────────────────────────────

build:
    uv build

clean:
    rm -rf dist/ build/ *.egg-info src/*.egg-info
    find . -type d -name __pycache__ -exec rm -rf {} +
    find . -type d -name .pytest_cache -exec rm -rf {} +
    find . -type d -name .ruff_cache -exec rm -rf {} +
