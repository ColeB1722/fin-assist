# Handoff Document

Rolling context for session handoffs. Updated as checkpoints are reached.

---

## Previous Session: Phase 1 - Repo Setup

**Date**: 2026-03-22
**Status**: ✅ Complete

### What Was Accomplished

1. **Architecture finalized** (`docs/architecture.md`)
   - Python 3.12+ (3.13 in nixos-unstable)
   - pydantic-ai for LLM abstraction
   - tmux + zellij multiplexer support
   - `/connect` command pattern for provider setup
   - Separate credential storage from config

2. **Repo initialized** with full dev environment (devenv, no flakes):
   - `devenv.nix`, `devenv.yaml` - Nix dev shell
   - `pyproject.toml` - Python package with dependencies
   - `justfile` - Task runner with common commands
   - `treefmt.toml` - Unified formatting
   - `.gitignore`, `.envrc` - Standard ignores, direnv
   - `secretspec.toml` - Dev secrets management
   - `AGENTS.md` - AI agent instructions (SSD → TDD pattern)
   - `handoff.md` - This file

3. **Verified working**:
   - `devenv shell just` - enters dev shell
   - `just fmt` - formats nix and python files

4. **CodeRabbit review** of initial commit (11 findings):
   - `.coderabbit.yaml` added (assertive profile, agent-friendly)
   - Fixed: `just ci` using `fmt` instead of `check` (bug)
   - Fixed: dead `tomli` dependency in pyproject.toml
   - Fixed: duplicate ruff-format pre-commit hook in devenv.nix
   - Fixed: justfile lint/typecheck/test guards for missing dirs
   - Fixed: AGENTS.md markdown lint (MD022, MD040, MD047)
   - Issue #1: Extract CI setup into composite action (tech-debt)
   - Issue #2: Guard install-fish for missing Phase 8 files (enhancement)
   - Dismissed: parallel CI jobs (fine), ProviderConfig in sketch (not code)

### Branch Protections ✅
Configured via GitHub ruleset ("Protect main"):
- [x] Require PR before merge to main
- [x] No force push to main
- [x] Auto-delete branches on merge
- [x] Require CI status checks — enabled in Phase 2

---

## Previous Session: CI & Docs Cleanup

**Date**: 2026-03-24
**Branch**: `chore/ci-and-docs-cleanup`
**Status**: ✅ Complete

### What Was Accomplished

1. **Removed CI workflow** (`.github/workflows/ci.yml`)
   - The devenv-based CI was too heavy for Phase 1 (~4.5 min for format check alone)
   - 5 of 6 historical runs failed (flake.nix requirement, devenv eval errors)
   - No code to lint/test yet (`src/` and `tests/` don't exist)
   - CI will be re-added in Phase 2 using targeted `nix shell` approach (design already in `architecture.md`)

2. **Updated branch protections**
   - Removed required status checks from "Protect main" ruleset
   - Kept: require PR before merge, no force push, auto-delete branches
   - Status checks will be re-enabled when CI is re-added in Phase 2

3. **Updated `docs/architecture.md`**
   - Marked CI section as Phase 2 target with rationale
   - Updated branch protections to reflect deferred checks
   - Moved "Add GitHub Actions CI workflow" from Phase 1 to Phase 2

4. **Closed issue #1** (Revisit CI strategy) — resolved by deferral

### Decision Record

| Decision | Choice | Rationale |
|----------|--------|-----------|
| CI in Phase 1 | Remove entirely | No code to check, devenv approach too heavy, 83% failure rate |
| CI approach for Phase 2 | `nix shell` + DeterminateSystems actions | Already designed in architecture.md, ~1 min vs ~4.5 min |
| Branch protections | Keep PR req, drop status checks | No CI to check against; re-add in Phase 2 |

---

## Previous Session: Phase 2 - Core Package Structure

**Date**: 2026-03-24
**Branch**: `feature/phase-2`
**PR**: #13
**Status**: ✅ Complete (merged)

### What Was Accomplished

1. **Dependencies aligned** (`pyproject.toml`)
   - Updated `pydantic-ai` from `>=0.1` to `>=1.0` (latest is v1.71)
   - Added `ty` type checker to dev dependencies (was missing)
   - All other dependencies verified current

2. **Package layout created** (TDD approach)
   - `src/fin_assist/__init__.py` - package root
   - `src/fin_assist/__main__.py` - entry point (stub)
   - `src/fin_assist/config/__init__.py` - config module
   - `src/fin_assist/config/schema.py` - pydantic-settings models
   - `src/fin_assist/config/loader.py` - TOML config loader
   - `tests/__init__.py` - test package
   - `tests/test_config.py` - 19 tests for schema + loader
   - `tests/test_package.py` - 3 smoke tests

3. **Config schema implemented** (`config/schema.py`)
   - `GeneralSettings` - default_provider, default_model (`claude-sonnet-4-6`), keybinding (env prefix: `FIN_`)
   - `ContextSettings` - max_file_size, max_history_items, include_git_status, include_env_vars
   - `ProviderConfig` - enabled, base_url, default_model (non-secret settings)
   - `Config` - aggregates all settings, providers dict

4. **Config loader implemented** (`config/loader.py`)
   - Loads from `~/.config/fin/config.toml` by default
   - Returns defaults if file missing or empty
   - Parses TOML and validates via pydantic
   - Handles partial configs (missing sections get defaults)

5. **CI workflow added** (`.github/workflows/ci.yml`)
   - Uses `nix shell` approach per architecture.md design
   - Three jobs: format (treefmt), lint (ruff + ty), test (pytest)
   - DeterminateSystems actions pinned: nix-installer@v21, magic-nix-cache@v13
   - Job names match ruleset requirements (format, lint, test)

6. **Branch protections updated**
   - Required status checks: format, lint, test
   - All checks must pass before merge to main

7. **CodeRabbit review fixes applied**
   - Pinned GitHub Action versions
   - Added subprocess timeout in tests
   - Fixed config module docstring
   - Simplified loader conditionals
   - Issues #10, #11, #12 created for deferred items

### Decision Record

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Loader return type | Return `Config` directly | Simpler; loader's job is to produce valid Config |
| Empty config file | Return defaults | Same behavior as missing file |
| ProviderConfig design | `dict[str, ProviderConfig]` | Extensible, matches TOML structure, non-secret settings only |
| Test scope | Schema + loader + smoke test | Enough for CI without over-engineering |
| CI format job | treefmt via nix shell | nix fmt requires flake.nix; treefmt uses same config as local dev |

### Test Summary

```
tests/test_config.py: 19 tests (schema + loader)
tests/test_package.py: 3 tests (smoke)
Total: 22 tests, all passing
```

---

## Next Session: Phase 3 - LLM Module

### Goals
1. Integrate pydantic-ai for provider abstraction
2. Implement Agent wrapper (`llm/agent.py`)
3. Create provider registry (`llm/providers.py`)
4. Write system prompts (`llm/prompts.py`)

### Design Questions to Resolve
- How to handle FallbackModel configuration (in code vs config)?
- Should providers be discovered dynamically or hardcoded?
- How to inject credentials from credential store into providers?

### Directory to Create
```
src/fin_assist/llm/
├── __init__.py
├── agent.py
├── providers.py
└── prompts.py
```

---

## Implementation Progress

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Repo Setup | ✅ Complete |
| 2 | Core Package Structure | ✅ Complete |
| 3 | LLM Module (pydantic-ai) | ⬜ Not Started |
| 4 | Credential Management | ⬜ Not Started |
| 5 | Context Module | ⬜ Not Started |
| 6 | UI Layer (Textual) | ⬜ Not Started |
| 7 | Multiplexer Integration | ⬜ Not Started |
| 8 | Fish Plugin | ⬜ Not Started |
| 9 | Testing & Documentation | ⬜ Not Started |

---

## Context for Fresh Session

To quickly get context in a new session:

1. Read this file (`handoff.md`) for current state
2. Read `docs/architecture.md` for full architecture
3. Read `AGENTS.md` for development patterns
4. Check "Implementation Progress" table above
5. Continue from "Next Session" section

### Key Files Reference
| File | Purpose |
|------|---------|
| `docs/architecture.md` | Full architecture, source of truth |
| `AGENTS.md` | Dev workflow, commands, decisions |
| `handoff.md` | This file - rolling session context |
| `pyproject.toml` | Dependencies, tool config |
| `justfile` | Task runner commands |

---

## Notes

- Target fish 3.2+ for shell integration
- Config stored in `~/.config/fin/config.toml`
- Credentials stored in `~/.local/share/fin/credentials.json`
- System prompt optimized for fish shell syntax