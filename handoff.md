# Handoff Document

Rolling context for session handoffs. Updated as checkpoints are reached.

---

## Previous Session: Architecture Consolidation & Design Direction

**Date**: 2026-03-26
**Status**: ✅ Complete
**Branch**: `feature/phase-2` (merged)

### What Was Accomplished

1. **Design session completed** — explored expanding fin-assist scope:
   - From: single-purpose shell command generator
   - To: multi-agent personal platform with specialized agents

2. **Key decisions made**:
   - **Agents as code, not declarative** — custom classes, not YAML/TOML configs. The fun is in the implementation.
   - **fasta2a (A2A protocol)** adopted as the server backend — inspired by OpenCode's server/client architecture
   - **OpenCode pattern** — server starts on TUI launch, persists, multiple clients can connect
   - **Local-only** — server binds to 127.0.0.1, no network exposure by default
   - **Agent specialization** — DefaultAgent (shell), SDDAgent (design), TDDAgent (implementation)
   - **Explicit routing** — `/shell`, `/sdd`, `/tdd` command prefixes

3. **Architecture doc consolidated** (`docs/architecture.md`):
   - Absorbed agent specialization design from `docs/agent-specialization.md`
   - Added fasta2a/A2A server architecture section
   - Updated component diagram to show server/client separation
   - Rewrote implementation phases (Phases 1-4 complete, 5-13 redefined)
   - Updated directory structure to include `agents/`, `server/` packages

4. **`docs/agent-specialization.md`** removed — content absorbed into `docs/architecture.md`.

### References

| Resource | Link |
|----------|------|
| OpenCode Architecture | https://opencode.ai/docs/core-concepts/architecture |
| OpenCode Server Docs | https://opencode.ai/docs/server/ |
| fasta2a (GitHub) | https://github.com/pydantic/fasta2a |
| A2A Protocol | https://a2aprotocol.ai/ |

### Open Questions (Unresolved)

| Question | Notes |
|----------|-------|
| Conversation storage | Deferred to Phase 9 — SQLite recommended for multi-turn query capability |
| Server lifecycle | On-demand subprocess vs background daemon (`fin-assist serve`) — both supported |
| File storage format | JSON per conversation — simple for Phase 1; migrate to SQLite if needed |
| Agent-to-agent calls | SDD→TDD handoff — future consideration, not Phase 1 |
| Web/GUI clients | Future consideration — A2A protocol enables any client |

---

## Previous Session: Phase 4 - Credential UI

**Date**: 2026-03-26
**Branch**: `feature/phase-4`
**Status**: ✅ Complete

### What Was Accomplished

1. **UI Module created** (`src/fin_assist/ui/`)
   - `__init__.py` - exports `ConnectDialog`, `PROVIDER_META`, `get_providers_requiring_api_key`
   - `connect.py` - `ConnectDialog` widget with multi-step flow

2. **ConnectDialog implemented** (`ui/connect.py`)
   - Step 1: Provider selection via button grid (anthropic, openai, openrouter, google, ollama, custom)
   - Step 2: API key input (skipped for ollama/custom - no key needed)
   - Step 3: Confirmation with success/error message
   - Optional keyring storage checkbox
   - Cancel dismisses without saving

3. **Design Decisions Made**
   - Provider selection via Buttons in Vertical container (not RadioSet - simpler)
   - Skip API key step for ollama/custom (self-hosted, no API key)
   - `is_mounted` guard in `_update_ui()` for testability
   - Helper functions `keyring_available()` and `set_keyring_key()` at module level

4. **Tests added**
   - `tests/test_ui/__init__.py` - test package
   - `tests/test_ui/test_connect.py` - 19 tests for ConnectDialog

### Test Summary

```text
tests/test_ui/test_connect.py: 19 tests
Total: 82 tests, all passing (was 63 before Phase 4)
```

---

## Previous Session: Phase 3 - LLM Module

**Date**: 2026-03-25
**Branch**: `feature/phase-3`
**PR**: #17
**Status**: ✅ Complete (merged)

### What Was Accomplished

1. **LLM Module implemented** (`src/fin_assist/llm/`)
   - `agent.py` - `LLMAgent` class with `CommandResult` model, FallbackModel support
   - `providers.py` - `ProviderRegistry` with providers (anthropic, openai, openrouter, google, custom)
   - `prompts.py` - `SYSTEM_INSTRUCTIONS` (static, cached) + `build_user_message()` (dynamic)

2. **Credentials Module implemented** (`src/fin_assist/credentials/`)
   - `store.py` - `CredentialStore` with env var → file → keyring fallback chain
   - Keyring functions consolidated into `store.py` (no separate module)

3. **Design Decisions Made**
   - FallbackModel: Hybrid — hardcoded providers, config controls enablement/order
   - Provider Discovery: Static list + CUSTOM for self-hosted
   - Credential Injection: Explicit — pass API keys to provider constructors
   - Output Format: `CommandResult(command: str, warnings: list[str])`
   - Prompt Structure: Static `SYSTEM_INSTRUCTIONS` (cached) + dynamic user message (context + prompt)
   - pydantic-ai structured output via `output_type=CommandResult` handles normalization

### Test Summary

```text
tests/test_llm/test_agent.py: 11 tests
tests/test_llm/test_providers.py: 12 tests
tests/test_llm/test_prompts.py: 6 tests
tests/test_credentials/test_store.py: 10 tests
Total: 63 tests, all passing
```

---

## Previous Session: Phase 2 - Core Package Structure

**Date**: 2026-03-24
**Branch**: `feature/phase-2`
**PR**: #13
**Status**: ✅ Complete (merged)

### What Was Accomplished

- Dependencies aligned (pydantic-ai >=1.0)
- Package layout created with config, tests
- Config schema and loader implemented
- CI workflow added

---

## Previous Session: Phase 1 - Repo Setup

**Date**: 2026-03-22
**Status**: ✅ Complete

### What Was Accomplished

- Architecture finalized in `docs/architecture.md`
- Full dev environment (devenv, pyproject.toml, justfile, treefmt, etc.)
- Branch protections configured

---

## Previous Session: Phase 5 - Context Module

**Date**: 2026-03-26
**Branch**: `feature/phase-5` (to be created)
**Status**: ✅ Complete

### What Was Accomplished

1. **Context Module implemented** (`src/fin_assist/context/`)
   - `base.py` — `ContextItem` dataclass, `ContextProvider` ABC, `ContextType` literal
   - `files.py` — `FileFinder` using `fd` for discovery, `fzf` for filtering
   - `git.py` — `GitContext` with diff, status, log commands
   - `history.py` — `ShellHistory` using `fish -c 'history'` command
   - `environment.py` — `Environment` with PWD, HOME, USER + configurable env vars

2. **ContextItem refactored** (pure refactor, no re-export)
   - Moved from `llm/prompts.py` → `context/base.py`
   - Updated imports in `llm/agent.py`, `llm/__init__.py`
   - Updated tests in `test_llm/test_agent.py`, `test_llm/test_prompts.py`

3. **Tests added** (`tests/test_context/`)
   - `test_base.py` — ContextItem validation, ContextProvider ABC
   - `test_files.py` — FileFinder with mocked fd/fzf
   - `test_git.py` — GitContext with mocked git commands
   - `test_history.py` — ShellHistory with mocked fish
   - `test_environment.py` — Environment with mocked os.environ

4. **Design Decisions Made**
   - `ContextItem` moved (pure refactor, no re-export)
   - Shell history via `fish -c 'history'` command (robust, official interface)
   - File discovery via `fd` when available, graceful degradation
   - `ContextProvider` ABC with `_supported_types()` for agent filtering

### Test Summary

```text
tests/test_context/: 51 tests (new)
Total: 133 tests, all passing (was 82 before Phase 5)
```

---

## Next Session: Phase 6 - Agent Protocol & Registry

### Goals
1. Define `BaseAgent` ABC with `AgentResult` model
2. Create `AgentRegistry` with decorator-based registration
3. Migrate current `LLMAgent` → `DefaultAgent` (shell agent)
4. Add explicit routing via `/shell`, `/sdd`, `/tdd` prefixes

### Relevant Files
- `src/fin_assist/agents/base.py` — BaseAgent ABC, AgentResult (to be created)
- `src/fin_assist/agents/registry.py` — AgentRegistry (to be created)
- `src/fin_assist/agents/default.py` — DefaultAgent (to be created)

---

## Implementation Progress

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Repo Setup | ✅ Complete |
| 2 | Core Package Structure | ✅ Complete |
| 3 | LLM Module (pydantic-ai) | ✅ Complete |
| 4 | Credential Management (UI) | ✅ Complete |
| 5 | Context Module | ✅ Complete |
| 6 | Agent Protocol & Registry | ⬜ Not Started |
| 7 | Specialization — SDDAgent | ⬜ Not Started |
| 8 | Specialization — TDDAgent | ⬜ Not Started |
| 9 | fasta2a Server Integration | ⬜ Not Started |
| 10 | TUI Client → A2A Client | ⬜ Not Started |
| 11 | Fish Plugin (Server-Aware) | ⬜ Not Started |
| 12 | Multiplexer Integration | ⬜ Not Started |
| 13 | Testing & Documentation | ⬜ Not Started |

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
- Credentials stored in `~/.local/share/fin/credentials.json` (0600 permissions)
- System prompt optimized for fish shell syntax
- Server binds to `127.0.0.1` only (local-only)
- A2A protocol via fasta2a for multi-client support
- Server lifecycle: on-demand via TUI, or standalone via `fin-assist serve`
