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
   - `model_registry.py` - `ProviderRegistry` with providers (anthropic, openai, openrouter, google, custom)
   - `prompts.py` - `SYSTEM_INSTRUCTIONS` (static, cached) + `build_user_message()` (dynamic)
   - `CommandResult` later moved to `agents/results.py` (Phase 6 refactor)

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
tests/test_llm/test_model_registry.py: 12 tests
tests/test_llm/test_prompts.py: 6 tests
tests/test_credentials/test_store.py: 10 tests
Total: 28 tests (Phase 3 baseline)
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
**Branch**: `feature/phase-5`
**Status**: ✅ Complete

### What Was Accomplished

1. **Context Module implemented** (`src/fin_assist/context/`)
   - `base.py` — `ContextItem` dataclass, `ContextProvider` ABC, `ContextType`, `ItemStatus` literals
   - `files.py` — `FileFinder` using `find` for discovery (no fd dependency)
   - `git.py` — `GitContext` with diff, status, log commands
   - `history.py` — `ShellHistory` using `fish -c 'history'` command, with caching and security filtering
   - `environment.py` — `Environment` with PWD, HOME, USER + configurable env vars, with security filtering

2. **ContextItem refactored** (pure refactor, no re-export)
   - Moved from `llm/prompts.py` → `context/base.py`
   - Added `status` and `error_reason` fields for explicit error handling
   - Updated imports throughout codebase
   - Updated tests in `test_llm/test_prompts.py`, `test_context/test_base.py`

3. **Security hardening**
   - Shell history: filters commands with embedded credentials (API keys, tokens, passwords)
   - Environment: redacts sensitive env vars (API_KEY, TOKEN, SECRET, etc.) with `status="excluded"`

4. **Tests added** (`tests/test_context/`)
   - `test_base.py` — ContextItem validation, ContextProvider ABC
   - `test_files.py` — FileFinder with mocked find
   - `test_git.py` — GitContext with mocked git commands
   - `test_history.py` — ShellHistory with mocked fish
   - `test_environment.py` — Environment with mocked os.environ

5. **CodeRabbit review fixes**
   - Exported `ContextType` and `ItemStatus` from context package
   - Added `_get_history()` caching
   - Fixed hardcoded `type="git_diff"` in git.py error cases
   - Added missing status assertion in test_files.py

### Test Summary

```text
tests/test_context/: 51 tests (new)
Total: 130 tests, all passing (was 82 before Phase 5)
```

---

## Previous Session: Phase 6 - Agent Protocol & Registry

**Date**: 2026-03-27
**Branch**: `feature/phase-6`
**Status**: ✅ Complete

### What Was Accomplished

1. **Agents Package created** (`src/fin_assist/agents/`)
   - `base.py` — `AgentResult` dataclass, `BaseAgent[T]` ABC with abstract properties/methods
   - `registry.py` — `AgentRegistry` with decorator-based registration
   - `default.py` — `DefaultAgent(BaseAgent[CommandResult])` shell agent implementation
   - `__init__.py` — public exports

2. **`AgentResult`** — Result envelope with `success`, `output`, `warnings`, `metadata`

3. **`BaseAgent[T]` ABC** — Abstract base defining agent contract:
   - `@property abstract name() -> str` — agent identifier ('shell', 'sdd', 'tdd')
   - `@property abstract description() -> str` — human-readable description
   - `@property abstract system_prompt() -> str` — agent-specific instructions
   - `@property abstract output_type() -> type[T]` — Pydantic output model
   - `@abstractmethod supports_context(ct: str) -> bool`
   - `@abstractmethod async run(prompt, context) -> AgentResult`

4. **`AgentRegistry`** — Registry with decorator-based registration:
   - `register(agent_cls)` — class decorator for self-registration
   - `get(name) -> BaseAgent | None` — get agent instance by name
   - `list_agents() -> list[tuple[str, str]]` — list all (name, description)

5. **`DefaultAgent`** — Shell command generation agent:
   - Migrated LLMAgent logic into BaseAgent protocol
   - `name='shell'`, supports file/git/history/environment context
   - `run()` returns `AgentResult[CommandResult]`
   - Reuses `SYSTEM_INSTRUCTIONS`, `build_user_message()`, `ProviderRegistry`

6. **Design Decisions Made**
   - `DefaultAgent` NOT auto-registered (requires config/credentials at init)
   - `AgentRegistry.register()` instantiates agent to get name — requires no-arg constructor
   - `LLMAgent` deleted entirely — greenfield, no orphaned code
   - `CommandResult` moved from `llm/agent.py` → `agents/results.py`
   - Routing prefixes (`/shell`, `/sdd`, `/tdd`) deferred to future phase

7. **Tests added** (`tests/test_agents/`)
   - `test_base.py` — AgentResult creation, BaseAgent ABC contract tests
   - `test_registry.py` — AgentRegistry registration, get, list_agents tests
   - `test_default.py` — DefaultAgent properties, run, model building tests

### Test Summary

```text
tests/test_agents/: 41 tests (new)
Total: 158 tests, all passing (was 117 before Phase 6, removed 13 redundant LLMAgent tests)
```

---

## Previous Session: Vision Realignment — MVP Focus

**Date**: 2026-03-27
**Status**: ✅ Complete

### Context

After reviewing the long-term vision (AI-Directed-Dev-Pipeline), we realigned on getting fin-assist to a **usable MVP state** rather than continuing with SDD/TDD agent implementation.

### Key Design Decisions

1. **DefaultAgent = Chain-of-Thought Base**
   - Agent = input → chain-of-thought → output (like OpenCode "thinking" before responding)
   - Multi-turn capable via message history (even if not always used)
   - NOT shell-specific initially — more general-purpose natural language interaction
   - Skills (e.g., brainstorming) and MCP tools can be added as add-ons

2. **Shell Completion = Specialized Agent**
   - A specialized agent that slots into the framework
   - Uses command-centric output elements
   - Can be selected via TUI or config

3. **Per-Agent UI Constraints**
   - Some agents only work with certain models
   - TUI should hide irrelevant selectors based on agent capabilities

4. **Skills + MCP Integration** (future phase)
   - Skills: configurable behaviors (brainstorming, etc.)
   - MCP: natural language interface to configurable tool selection

5. **Testing Focus**
   - Deep evals framework (pytest-compatible, LLM-as-judge by default)
   - Must/must-not/should criteria per agent
   - CI: GitHub Action post-merge runs evals, posts regressions as issues

### Revised Phase Priority

| Phase | Focus | Status |
|-------|-------|--------|
| 7 | TUI Implementation — wire up foundation, agent cycling, per-agent UI | ⬜ Not Started |
| 8 | Multiplexer Integration — tmux, zellij, fallback | ⬜ Not Started |
| 9 | Fish Plugin — keybinding, command insertion, server auto-start | ⬜ Not Started |
| 10 | Testing Infrastructure — deep evals framework | ⬜ Not Started |
| 11 | CI for Evals — GitHub Action, regression issues | ⬜ Not Started |
| 12+ | SDD/TDD Agents — deferred for detailed discussion | ⬜ Not Started |

### SDD/TDD Deferred

- These represent the full AI-Directed-Dev-Pipeline vision
- Want much more detailed design discussion before implementing
- The framework we're building now will enable that later

---

## Next Session: Phase 7 — TUI Implementation

### Goals

1. **Wire up the existing foundation** — DefaultAgent → Textual TUI
2. **Agent cycling** — AgentSelector component, switch between agents
3. **Per-agent UI constraints** — Hide/show selectors based on agent capabilities
4. **Config-driven agent selection** — Global + per-project TOML

### DefaultAgent Refactor (First)

Before TUI work, refactor `DefaultAgent` to be the chain-of-thought base:
- Remove shell-specific `SYSTEM_INSTRUCTIONS`
- Add generic chain-of-thought system prompt
- Multi-turn via `message_history` (pydantic-ai's `ModelMessagesTypeAdapter`)

### TUI Components (MVP)

- `PromptInput` — text area for natural language input
- `AgentOutput` — display agent response (chain-of-thought visible)
- `AgentSelector` — switch between available agents
- `ModelSelector` — dropdown for provider/model selection
- `ConnectDialog` — existing `/connect` flow

### Not in MVP (Deferred)

- ContextPreview (add later)
- ChatHistory (multi-turn for specialized agents)
- Skills/MCP configuration UI

---

## Next Session: Phase 7 - Specialization — SDDAgent

### Goals
1. Create `SDDAgent` class for architectural brainstorming and design
2. Define `SketchResult` model for design output
3. Implement doc-reading tools for SDDAgent
4. Note: Routing prefixes (`/shell`, `/sdd`, `/tdd`) deferred to future phase

### Relevant Files
- `src/fin_assist/agents/sdd.py` — SDDAgent (to be created)
- `src/fin_assist/agents/results.py` — SketchResult model (to be created)

### Process Notes
- **Phase 6 TDD lapse**: Implemented code before tests. Tests served as verification rather than specification. Going forward, must write failing tests BEFORE implementation per AGENTS.md SSD→TDD workflow.
- **Test quality**: Refactored tests to use public API instead of private state, test behavior not implementation details.

---

## Implementation Progress

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Repo Setup | ✅ Complete |
| 2 | Core Package Structure | ✅ Complete |
| 3 | LLM Module (pydantic-ai) | ✅ Complete |
| 4 | Credential Management (UI) | ✅ Complete |
| 5 | Context Module | ✅ Complete |
| 6 | Agent Protocol & Registry | ✅ Complete |
| 7 | TUI Implementation | ⬜ Not Started |
| 8 | Multiplexer Integration | ⬜ Not Started |
| 9 | Fish Plugin | ⬜ Not Started |
| 10 | Testing Infrastructure (Deep Evals) | ⬜ Not Started |
| 11 | CI for Evals | ⬜ Not Started |
| 12 | SDD/TDD Agents | ⬜ Not Started |
| 13 | Skills + MCP Integration | ⬜ Not Started |
| 14 | Documentation | ⬜ Not Started |

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
