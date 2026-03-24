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
- [ ] Require CI status checks — deferred to Phase 2

---

## Current Session: CI & Docs Cleanup

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

## Next Session: Phase 2 - Core Package Structure

### Goals
1. Create `src/fin_assist/` package layout
2. Implement config loading (`config/schema.py`, `config/loader.py`)
3. Set up pydantic settings
4. Write initial tests
5. Re-add CI workflow (using `nix shell` approach from `architecture.md`)
6. Re-enable required status checks in branch protections

### Design Sketches

#### Config Schema (initial)
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class GeneralSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FIN_")
    default_provider: str = "anthropic"
    default_model: str = "claude-sonnet-4-5"
    keybinding: str = "ctrl-enter"

class ContextSettings(BaseSettings):
    max_file_size: int = 100_000
    max_history_items: int = 50
    include_git_status: bool = True
    include_env_vars: list[str] = ["PATH", "HOME", "USER", "PWD"]

class Config(BaseSettings):
    general: GeneralSettings = GeneralSettings()
    context: ContextSettings = ContextSettings()
    providers: dict[str, ProviderConfig] = {}
```

#### Directory to Create
```
src/
└── fin_assist/
    ├── __init__.py
    ├── __main__.py
    └── config/
        ├── __init__.py
        ├── schema.py
        └── loader.py
tests/
├── __init__.py
└── test_config.py
```

---

## Implementation Progress

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Repo Setup | ✅ Complete |
| 2 | Core Package Structure | ⬜ Not Started |
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