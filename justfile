# fin-assist task runner

set dotenv-load := false
set shell := ["bash", "-euo", "pipefail", "-c"]
set windows-shell := ["pwsh", "-NoLogo", "-Command"]

_default:
    @just --list

# ── Dev shell ────────────────────────────────────────────────────────────────

dev:
    {{ if os_family() == "windows" { "uv sync --all-groups" } else { "devenv shell" } }}

# ── Code quality ─────────────────────────────────────────────────────────────

fmt:
    {{ if os_family() == "windows" { "uv run ruff format src/" } else { "treefmt" } }}

check:
    {{ if os_family() == "windows" { "uv run ruff format --check src/" } else { "treefmt --ci" } }}

lint:
    uv run ruff check src/

lint-fix:
    uv run ruff check --fix src/

# Architecture firewall — enforces hub/cli import boundary.
# See docs/architecture.md § "Deliverables: Hub vs CLI".
lint-imports:
    uv run lint-imports

typecheck:
    uv run ty check src/

test *args:
    uv run pytest tests/ {{ args }}

test-cov:
    uv run pytest tests/ --cov=fin_assist --cov-report=term-missing

ci: check lint lint-imports typecheck test

# ── Local dev ────────────────────────────────────────────────────────────────

run:
    uv run python -m fin_assist

install-fish:
    {{ if os_family() == "windows" { "echo 'Fish plugin not supported on Windows'" } else { "mkdir -p ~/.config/fish/conf.d && mkdir -p ~/.config/fish/functions && cp fish/conf.d/fin_assist.fish ~/.config/fish/conf.d/ && cp fish/functions/fin_assist.fish ~/.config/fish/functions/" } }}

# Install package in dev mode
install-dev:
    uv pip install -e .

# ── Diagrams ─────────────────────────────────────────────────────────────────

# Render README ```mermaid blocks to docs/diagrams/*.svg (+ *.png).
# The README is the single source of truth; each block is named by a preceding
# `<!-- diagram:<slug> -->` comment. Generated files are gitignored.
diagrams:
    uv run python scripts/render_diagrams.py

# Remove generated diagram images.
diagrams-clean:
    {{ if os_family() == "windows" { "uv run python -c \"from pathlib import Path; [p.unlink() for p in Path('docs/diagrams').glob('*') if p.suffix in ('.svg', '.png')]\"" } else { "rm -f docs/diagrams/*.svg docs/diagrams/*.png" } }}

# ── Build ────────────────────────────────────────────────────────────────────

build:
    uv build

clean:
    {{ if os_family() == "windows" { "uv run python scripts/clean.py" } else { "rm -rf dist/ build/ *.egg-info src/*.egg-info && find . -type d -name __pycache__ -exec rm -rf {} + && find . -type d -name .pytest_cache -exec rm -rf {} + && find . -type d -name .ruff_cache -exec rm -rf {} +" } }}
