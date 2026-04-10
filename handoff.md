# Handoff Document

Rolling context for session handoffs. Updated as checkpoints are reached.

**Current state (2026-04-09)**: Phases 1-8b complete. Manual testing found Chunk B bugs (fixed), led to regenerate removal, and uncovered a PID file reliability issue (fixed with server-side locking). Resume manual testing from Chunk A6/B (re-verify stop + approval) and continue with Chunks C-D.

---

## Auth-Required Credential Pre-Check (2026-04-03)

**Status**: Complete

### Problem

When API keys were missing, `BaseAgent._build_model()` passed `api_key=None` to the pydantic-ai provider constructor, which silently accepted it. The first actual LLM call then exploded with a cryptic provider-specific 401 error. The task was set to `"failed"` with no indication of *which* provider was misconfigured or how to fix it.

### What Was Implemented

Graceful early detection of missing credentials using the A2A `auth-required` task state, providing clear remediation guidance instead of cryptic provider errors.

**6 layers, bottom-up:**

1. **`MissingCredentialsError`** (`agents/base.py`) — Exception carrying the list of providers missing keys. Message includes env var hints (e.g. `ANTHROPIC_API_KEY`).

2. **`BaseAgent.check_credentials() -> list[str]`** (`agents/base.py`) — Iterates enabled providers, checks `PROVIDER_META.requires_api_key`, calls `credentials.get_api_key()`. Returns names of providers missing keys. Called as a guard at the top of `_build_model()`.

3. **`FinAssistWorker(AgentWorker)`** (`hub/worker.py`) — Custom fasta2a worker subclass. Overrides `run_task()` to catch `MissingCredentialsError` and set task state to `"auth-required"` with an agent message explaining what's missing. Other exceptions still produce `"failed"`.

4. **`AgentFactory` updated** (`hub/factory.py`) — Passes a custom `lifespan` to `to_a2a()` that starts `FinAssistWorker` instead of fasta2a's default `AgentWorker`.

5. **`HubClient._extract_result`** (`cli/client.py`) — When state is `"auth-required"`, sets `metadata["auth_required"] = True` and extracts the agent message from history as output.

6. **`render_auth_required`** (`cli/display.py`) — Yellow panel with provider name, env var hints, and credentials file path. Visually distinct from generic `Error:` rendering.

7. **CLI wiring** (`cli/main.py`, `cli/interaction/chat.py`) — `_do_command` checks `result.metadata.get("auth_required")` and returns 1 with the auth panel. Chat loop breaks with the auth panel and a "fix credentials" message.

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Pre-check location | `_build_model()` guard | Catches before any LLM call attempt; pydantic-ai agent's `run()` triggers `_build_model` lazily |
| Task state | `auth-required` (A2A spec) | Semantically correct; distinct from `failed` (bug) vs `auth-required` (config issue) |
| `auth-required` remains terminal | Stays in `_TERMINAL_STATES` | Interactive recovery (Phase 10) deferred; user fixes credentials out-of-band |
| Worker override | Full `run_task()` override | Can't use `super()` because parent catches `Exception` and sets `failed` before we can intercept |
| Message transport | `new_messages` parameter on `update_task` | Uses existing A2A history mechanism; no storage changes needed |
| Unknown providers | Assumed to not require key | Defensive; avoids false positives for custom/self-hosted providers |

### Test Summary

```text
tests/test_agents/test_credentials_check.py: 12 tests (new)
tests/test_hub/test_worker.py: 5 tests (new)
tests/test_cli/test_client.py: 3 new tests (25 total)
tests/test_cli/test_display.py: 4 new tests (22 total)
Total: 368 tests, all passing (was 344 before)
```

### Files Changed

| File | Change |
|------|--------|
| `src/fin_assist/agents/base.py` | Added `MissingCredentialsError`, `check_credentials()`, guard in `_build_model()` |
| `src/fin_assist/agents/__init__.py` | Export `MissingCredentialsError` |
| `src/fin_assist/hub/worker.py` | **New** — `FinAssistWorker` subclass |
| `src/fin_assist/hub/factory.py` | Custom lifespan using `FinAssistWorker` |
| `src/fin_assist/hub/__init__.py` | Export `FinAssistWorker` |
| `src/fin_assist/cli/client.py` | `_extract_result` handles `auth-required` state |
| `src/fin_assist/cli/display.py` | Added `render_auth_required()` |
| `src/fin_assist/cli/main.py` | `_do_command` checks `auth_required` metadata |
| `src/fin_assist/cli/interaction/chat.py` | Chat loop breaks on `auth_required` |
| `tests/test_agents/test_credentials_check.py` | **New** — 12 tests |
| `tests/test_hub/test_worker.py` | **New** — 5 tests |
| `tests/test_cli/test_client.py` | 3 new `auth-required` extraction tests |
| `tests/test_cli/test_display.py` | 4 new `render_auth_required` tests |

### Future: Interactive Recovery (Phase 10)

The current implementation treats `auth-required` as terminal — the user fixes credentials out-of-band. The Phase 10 design sketch for `InputRequiredError` / `AuthRequiredError` (below) describes the interactive recovery pattern: move `auth-required` to a `_PAUSE_STATES` set, catch it in the client, prompt for credentials inline, write via `CredentialStore`, and resend on the same `context_id`. This builds naturally on top of the current implementation.

---

## CodeRabbit Review Triage (2026-03-31)

**Branch**: `feature/phase-8`

### Addressed (Implemented)

| Finding | File | Description |
|---------|------|-------------|
| Weak assertion | `tests/test_cli/test_client.py:181` | Fixed `test_artifacts_take_precedence_over_history` to have a proper assertion. Note: the actual behavior is "history takes precedence" (reversed scan + first-match wins), so renamed test to `test_history_takes_precedence_over_artifacts`. |
| Missing httpx.RequestError | `src/fin_assist/cli/server.py:37-40` | Added `httpx.RequestError` to `_check_health` exception handling (was only catching `ConnectError` and `TimeoutException`). |
| Missing agent validation for `--list` | `src/fin_assist/cli/main.py:157` | Added guard: if `args.list_sessions` is True and `args.agent` is None, renders error and returns 1. |
| Missing agent validation for `--resume` | `src/fin_assist/cli/main.py:170` | Added guard: if `args.resume` is True and `args.agent` is None, renders error and returns 1. |
| Subprocess PIPE blocking | `src/fin_assist/cli/server.py:118-119` | Changed `stdout=PIPE, stderr=PIPE` to `DEVNULL` since logs go to hub.log. |
| Missing type hint | `src/fin_assist/cli/interaction/chat.py:12` | Added `send_message_fn: Callable[[str, str, str \| None], Awaitable[AgentResult]]` with proper TYPE_CHECKING imports. |
| stop_server wait optional | `src/fin_assist/cli/server.py:197-225` | Added optional `wait_timeout` parameter (default 0 for current behavior). When > 0, polls `_pid_is_running` after SIGTERM. |

### Accepted as-is (Documented)

| Finding | Reason |
|---------|--------|
| capture_console fixture | Nitpick - manual console capture is clear and isolated. Low value-add to extract. |
| Testing private _extract_result | Intentional unit testing of internal helper - no public API to test same behavior without significant test infrastructure. |
| Private constants in test_logging | Using `_DEFAULT_MAX_BYTES` and `_DEFAULT_BACKUP_COUNT` is appropriate here since they are module-internal defaults being tested for correct values. Making them public would expose implementation details. |
| Redundant exception handling | `except (ServerStartupError, Exception)` documents intent even though `Exception` catches everything. Style preference, not a bug. |
| LOG_FILE duplication | `hub/logging.py` owns the constant; `server.py` imports it via `from fin_assist.hub.logging import LOG_FILE`. Acceptable separation. |
| Blocking Prompt.ask | Intentional for CLI TUI - blocking is appropriate for sequential user input. `asyncio.to_thread` would add complexity without benefit for this use case. |
| Missing bash language spec | Nitpick - markdown renders fine without it. |

---

## Previous Session: Architecture Consolidation & Design Direction

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

## Previous Session: Pre-Pivot TUI Cleanup

**Date**: 2026-03-28
**Status**: ✅ Complete

### What Was Accomplished

Removed the pre-pivot TUI code that was wired as the only client, clearing the path for Phase 7 CLI/hub development:

1. **Deleted `src/fin_assist/ui/`** — 9 files (Textual widgets, app, connect dialog)
2. **Deleted `tests/test_ui/`** — 29 tests for removed UI components
3. **Removed from dependencies**:
   - `textual>=3.0` (will be re-added in Phase 11)
   - `pytest-textual-snapshot>=1.0` (dev)
4. **Rewrote `__main__.py`** — stub placeholder for Phase 7 CLI dispatcher

### Rationale

The TUI was built pre-pivot as a direct-call Textual app (instantiating `DefaultAgent` directly, no hub). Post-pivot architecture defines it as a Phase 11 A2A client. Keeping it would:
- Block `__main__.py` rewrite for CLI commands
- Create coupling to old patterns during agent/hub evolution
- Add maintenance burden for dead code

Widget patterns are documented in `docs/architecture.md` under "UI Metadata Flow" and "AgentCardMeta" sections — easy to recreate when needed.

---

## Previous Session: Architecture Pivot — Agent Hub Design

**Date**: 2026-03-27
**Status**: ✅ Complete

### Context

Deep design session to realign the project with an evolved vision: fin-assist as an **expandable agent platform**, not just a shell assistant. The owner's mental model had grown significantly — encompassing ideas for SDD, TDD, code review, shell completion, computer use, journaling, and hyper-agents — while the codebase was still oriented around a TUI-first MVP.

### What Was Accomplished

1. **Full vision analysis** — compared stream-of-consciousness vision against current architecture and phase plan. Identified significant divergence in priorities (hub-first vs TUI-first) and missing concepts (agent metadata protocol, CLI client, conversation store design).

2. **Key architectural decisions made** (interactive Q&A):

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent routing model | Multi-path: N agents, N agent cards, path-based routing | True A2A compliance, enables agent-to-agent workflows |
| CLI strategy | Layered: simple CLI first, then REPL mode | Fast iteration on hub + agent behavior |
| Conversation store | A2A-native `context_id` via fasta2a's `Storage` ABC | Protocol-native, shared across all agents |
| UI metadata transport | Split: static in agent card extensions, dynamic in task artifacts | Agent card declares capabilities; per-response hints in artifacts |
| Parent ASGI framework | Starlette (not FastAPI) | Lighter, stays in pydantic/fasta2a ecosystem |
| First two agents | Shell (one-shot) + Default (multi-turn) | Maximum UI contrast to prove dynamic adaptation |

3. **Architecture doc rewritten** (`docs/architecture.md`):
   - New overview: "expandable personal AI agent platform" with Agent Hub
   - New core vision: hub, dynamic UI via metadata, protocol-native, CLI-first
   - Updated system overview + component diagrams
   - New directory structure with `hub/` and `cli/` packages
   - New key interfaces: `AgentCardMeta`, `AgentHub`, `AgentFactory`, UI metadata flow
   - Updated A2A section with multi-path routing details
   - Complete phase plan rewrite (7-16)
   - Updated open questions, design decisions table

4. **Phase plan reordered** — hub-first development:
   - Phase 7: Agent Hub Server (Starlette + fasta2a + SQLite storage)
   - Phase 8: CLI Client (simple commands + Rich display) ✅
   - Phase 8b: CLI REPL Mode (prompt-toolkit)
   - Phase 9: Streaming (`message/stream` + SSE)
   - Phase 10: Non-blocking + polling agents
   - Phase 11-12: Multiplexer + Fish (deferred)
   - Phase 13: TUI Client (reuse existing widgets as A2A client)
   - Phase 15: Skills + MCP
   - Phase 16: Additional Agents (SDD, TDD, code review, etc.)
   - Phase 17: Multi-agent workflows

### Research Conducted

- fasta2a API: `FastA2A`, `Storage`, `Broker`, `Worker`, `Skill`, `AgentCard` schemas
- pydantic-ai `Agent.to_a2a()` — creates ASGI sub-app from pydantic-ai agent
- A2A protocol: agent cards, `context_id` for multi-turn, `DataPart` artifacts for structured output
- Multi-agent server patterns: path-based routing with separate agent cards per path
- Agent card structure: `skills[]`, `capabilities`, `extensions` for custom metadata

### What Exists But Is Set Aside

- TUI code (`ui/` package) — functional Textual widgets, will be reused as A2A client in Phase 11
- `fasta2a>=0.6` already in dependencies but never imported — ready for Phase 7

---

## Previous Session: Vision Realignment — MVP Focus

**Date**: 2026-03-27
**Status**: ✅ Complete (superseded by Architecture Pivot above)

### Context

After reviewing the long-term vision (AI-Directed-Dev-Pipeline), we realigned on getting fin-assist to a **usable MVP state** rather than continuing with SDD/TDD agent implementation. This session's phase plan was later superseded by the Architecture Pivot session.

### Key Design Decisions

1. **DefaultAgent = Chain-of-Thought Base**
   - Agent = input -> chain-of-thought -> output
   - Multi-turn capable via message history
   - NOT shell-specific initially

2. **Shell Completion = Specialized Agent**
   - A specialized agent that slots into the framework

3. **Per-Agent UI Constraints**
   - TUI should hide irrelevant selectors based on agent capabilities

4. **Testing Focus**
   - Deep evals framework (pytest-compatible, LLM-as-judge by default)

---

## Previous Session: Phase 7 — Agent Hub Server

**Date**: 2026-03-28
**Branch**: `feature/phase-7`
**Status**: ✅ Complete

### What Was Accomplished

1. **`AgentCardMeta` consolidated into `BaseAgent`** (`agents/base.py`)
   - Removed redundant scalar properties (`supports_thinking`, `supports_model_selection`, `supported_providers`)
   - `agent_card_metadata` property returns `AgentCardMeta()` by default; subclasses override

2. **`ShellAgent` implemented** (`agents/shell.py`)
   - One-shot command generation, mirrors `DefaultAgent` pattern exactly
   - `agent_card_metadata`: `multi_turn=False, supports_thinking=False, tags=["shell", "one-shot"]`
   - `run()` returns `AgentResult` with `metadata={"accept_action": "insert_command"}`

3. **`SQLiteStorage` implemented** (`hub/storage.py`)
   - Implements fasta2a `Storage[Any]` ABC — all 5 methods
   - Tables: `tasks` + `contexts`; configurable `db_path`

4. **`AgentFactory` implemented** (`hub/factory.py`)
   - `BaseAgent` → pydantic-ai `Agent` → `.to_a2a()` with shared storage/broker
   - Injects `AgentCardMeta` as `Skill(id="fin_assist:meta")` (JSON-encoded)

5. **Hub app implemented** (`hub/app.py`)
   - Parent Starlette app mounting agents at `/agents/{name}/`
   - `GET /health` and `GET /agents` discovery endpoint
   - Parent lifespan cascades `TaskManager` init to sub-apps

6. **`fin-assist serve` wired** (`__main__.py`)
   - `fin-assist serve [--host] [--port] [--db]` starts hub via uvicorn
   - Defaults: `127.0.0.1:4096`, `~/.local/share/fin/hub.db`

### Test Summary

```text
tests/test_agents/test_base.py: 14 tests
tests/test_agents/test_shell.py: 16 tests
tests/test_hub/test_app.py: 11 tests
tests/test_hub/test_factory.py: 9 tests
tests/test_hub/test_serve.py: 4 tests
tests/test_hub/test_storage.py: 16 tests
Total: 195 tests, all passing (was 146 before Phase 7)
```

### Open Questions Resolved

| Question | Resolution |
|----------|------------|
| `to_a2a()` customisation | Accepts `storage`, `broker`, `name`, `description`, `skills` |
| Agent card extensions | See note below — deliberate workaround, not a library gap |
| SQLite location | Configurable via `--db`; default `~/.local/share/fin/hub.db` |
| Sub-app lifespan | Parent lifespan manually cascades `task_manager.__aenter__` |

### Note: AgentCardMeta transport — `Skill` workaround

`AgentCardMeta` is currently encoded as `Skill(id="fin_assist:meta")` with the metadata JSON-encoded in the `description` field. This is a deliberate workaround, not a library limitation or a mistake.

**Why:** The A2A spec defines `AgentCapabilities.extensions: list[AgentExtension]` as the correct place for this. `AgentExtension` is already defined in `fasta2a.schema`, but `AgentCapabilities` does not yet expose the `extensions` field — because extensions support is bundled with streaming support and is being shipped in pydantic/fasta2a **PR #44** (opened 2026-03-07, not merged as of fasta2a 0.6.0). The pydantic team intentionally held it back until both features were ready together.

**Migration path** (once fasta2a ships PR #44):
1. In `hub/factory.py`: replace the `meta_skill` block with an `AgentExtension` dict passed via `AgentCapabilities(extensions=[...])`
2. In `cli/client.py` (Phase 8): read from `capabilities.extensions` instead of filtering `skills`
3. Bump `fasta2a>=0.7` (or whatever version lands the feature) in `pyproject.toml`

The `factory.py` module docstring documents this in full detail for the next session.

---

## Previous Session: Phase 8 — CLI Client

**Date**: 2026-03-29 / 2026-03-30
**Branch**: `feature/phase-8`
**Status**: ✅ Complete

### What Was Accomplished

1. **`AgentCardMeta` converted to Pydantic `BaseModel`** (`agents/base.py`)
   - Was a `@dataclass`; now `BaseModel` — enables `model_validate(dict)` for hub responses
   - Added `requires_approval: bool` and `supports_regenerate: bool` fields

2. **`ShellAgent` updated** (`agents/shell.py`)
   - Sets `requires_approval=True, supports_regenerate=True` in metadata
   - Adds `regenerate_prompt` to result metadata

3. **`cli/server.py`** — Auto-start server logic
   - `_check_health()` — polls `/health` endpoint
   - `_wait_for_health()` — exponential backoff polling (50ms → 1s, 10s timeout)
   - `_spawn_serve()` — spawns `fin-assist serve` as background subprocess
   - `ensure_server_running()` — checks health, spawns if needed, raises `ServerStartupError`

4. **`cli/client.py`** — A2A HTTP client using fasta2a TypeAdapters directly
   - No custom `models.py` — uses `fasta2a.schema` types (`Task`, `Part`, etc.) + `send_message_response_ta`, `get_task_response_ta`
   - `A2AClient` with `discover_agents()`, `run_agent()`, `send_message()`
   - `_extract_result()` using `match` on `kind` for part discrimination
   - `_poll_task()` — fallback for non-blocking `message/send` (not currently exercised; hub defaults to blocking)
   - `DiscoveredAgent`, `AgentResult` data classes

5. **`cli/display.py`** — Rich rendering
   - `render_command()`, `render_response()`, `render_warnings()`
   - `render_error()`, `render_success()`, `render_info()`
   - `render_agent_card()`, `render_agents_list()`

6. **`cli/interaction/approve.py`** — Approval widget
   - `ApprovalAction` StrEnum (`EXECUTE`, `EDIT`, `CANCEL`)
   - `run_approve_widget()` — shows `[execute] [regenerate] [cancel]` prompt
   - `execute_command()` — runs command via `subprocess.run(shell=True)`

7. **`cli/interaction/chat.py`** — Multi-turn chat loop
   - `run_chat_loop()` — async loop with `/exit`, `/quit`, `/q` to end
   - Propagates `context_id` across turns; continues on error

8. **`cli/main.py`** — CLI dispatch
   - `_hub_client()` async context manager — owns server startup, client lifecycle, unified error rendering
   - `_get_agent_or_error()` — discovers agents, validates name, renders error if not found
   - `do <agent> <prompt>` — one-shot; reads `card_meta` from `discover_agents()` (not result metadata)
   - `talk <agent>` — multi-turn; `--list` runs without server, `--resume <id>` restores context
   - Session IDs are coolname slugs (`"swift-harbor"`) not truncated UUIDs; backend `context_id` stays UUID
   - `match args.command` dispatch replacing `if/elif` chain
   - `serve` — starts hub via uvicorn

9. **`__main__.py`** simplified to thin shim delegating to `cli/main.py`

10. **Tests added** (`tests/test_cli/`)
    - `test_server.py` — 13 tests
    - `test_client.py` — 20 tests
    - `test_display.py` — 18 tests
    - `interaction/test_approve.py` — 9 tests
    - `interaction/test_chat.py` — 11 tests
    - `test_main.py` — 28 tests (includes `TestHubClient`, `TestDoCommandApproval`)

### Test Summary

```text
tests/test_cli/: 99 tests
Total: 303 tests, all passing
```

### Key Implementation Notes

- **No `cli/models.py`**: originally built as Pydantic wrappers for fasta2a TypedDicts. Deleted — fasta2a ships `TextPart`, `DataPart`, `Task`, etc. directly plus `TypeAdapter` instances (`send_message_response_ta`) for `validate_json`. Using those directly eliminates drift risk.
- **`_poll_task` is intentional, not dead code**: The A2A protocol supports non-blocking `message/send` where the hub returns a `Message` acknowledgment and the client polls `tasks/get`. fasta2a currently defaults to blocking mode so this path isn't exercised, but it's correct protocol implementation for future non-blocking/background agent use cases.
- **`card_meta` source**: `requires_approval`/`supports_regenerate` are read from `DiscoveredAgent.card_meta` (fetched via `discover_agents()`), not from `result.metadata`. Static capabilities belong on the agent card; dynamic per-response data belongs in result metadata.
- **`asyncio.run()` in tests**: `main()` calls `asyncio.run()` for async commands. Tests patch it with `loop.run_until_complete()` to avoid "cannot be called from running event loop" error in pytest-asyncio.
- **`_extract_result` scan order**: Items are `reversed([*artifacts, *history])` — history appears at the end of the list so comes first in reversed scan; first non-empty text wins.
- **Transport modalities**: See `docs/architecture.md` Transport Layer section for the full roadmap (streaming Phase 9, gRPC as tracked issue).

---

## Reliable Server Lifecycle: PID File Locking (2026-04-09)

**Status**: Complete

### Problem

`fin stop` was unreliable — it would report "no running hub found" even when the hub was clearly running. Root cause: the CLI spawner wrote the PID file, then `stop_server` sent SIGTERM and immediately deleted the PID file (wait_timeout=0) without confirming the process actually died. The server itself had no awareness of the PID file. This caused orphaned processes that couldn't be stopped.

### Solution: Server-Owned PID File with fcntl Locking

Modeled after daemonocle and PEP 3143 best practices:

1. **Server writes and locks**: The hub server (`fin serve --pid-file <path>`) writes its PID and acquires an exclusive `fcntl.flock()` for its entire lifetime
2. **Server cleans up**: `atexit` handler + custom SIGTERM handler (calls `sys.exit(0)` to trigger atexit) removes the PID file on shutdown
3. **Lock-based stale detection**: If the server crashes (SIGKILL), the OS releases the lock. Clients detect stale files by probing with a non-blocking `flock`
4. **Stop = SIGTERM + wait + SIGKILL**: `stop_server` sends SIGTERM, waits up to 10s for the process to exit, escalates to SIGKILL if needed. Only cleans up PID file as a safety net after confirmed death

### Files Changed

| File | Change |
|------|--------|
| `src/fin_assist/hub/pidfile.py` | **New** — `acquire()`, `release()`, `is_locked()` with fcntl locking |
| `src/fin_assist/cli/server.py` | Refactored: removed `_write_pid`/`_remove_pid`, `_spawn_serve` passes `--pid-file` to server, `stop_server` waits+escalates |
| `src/fin_assist/cli/main.py` | Added `--pid-file` arg to serve command, server calls `acquire_pidfile()` before `uvicorn.run()` |
| `pyproject.toml` | Added `fin` entry point alias |
| `tests/test_hub/test_pidfile.py` | **New** — 11 tests for acquire/release/is_locked |
| `tests/test_cli/test_server.py` | Updated: removed `_write_pid`/`_remove_pid` tests, added SIGKILL escalation test |

### Test Summary

```text
Total: 381 tests, all passing (was 371; +10 new pidfile tests)
```

---

## Manual Testing Bug Fixes + Regenerate Removal (2026-04-09)

**Status**: Complete

### Bugs Found During Chunk B Manual Testing

1. **Ctrl+C/D trapped in approval loop (B6/B7)**: `FinPrompt.ask()` swallowed `KeyboardInterrupt`/`EOFError` and returned `""`, which the approval widget treated as empty input and looped. User could never escape.

2. **Rich markup rendered as literal text**: Prompt text `[bold]Action:[/bold]` was passed to `prompt_toolkit`, which doesn't understand Rich markup. Appeared as literal `[bold]` tags.

3. **Regenerate always broken**: `regenerate_prompt` was never populated in task artifact metadata. Typing `regenerate` always showed "not available".

### What Changed

**Bug fixes:**
- `FinPrompt.ask()` now propagates `KeyboardInterrupt`/`EOFError` instead of swallowing them — callers decide how to handle
- `approve.py` catches both exceptions and returns `CANCEL`
- `chat.py` already caught them (no change needed to its logic)
- Removed Rich markup tags from prompt text passed to `prompt_toolkit`

**Regenerate removal (simplification):**

The regenerate feature was removed entirely. Rationale:
- The implementation was broken (never worked end-to-end)
- Re-rolling the same prompt at default temperature gives the same result
- The client already has the prompt in local scope — the server round-trip was unnecessary indirection
- Removing it eliminated: the `while True` loop in `_do_command`, the `EDIT` action, `supports_regenerate`/`regenerate_prompt` parameters, and the `regenerate` match case
- Can be re-added properly when there's temperature control or prompt-editing support

**Files changed:**

| File | Change |
|------|--------|
| `src/fin_assist/cli/interaction/prompt.py` | Stop swallowing `KeyboardInterrupt`/`EOFError` in `ask()` |
| `src/fin_assist/cli/interaction/approve.py` | Catch Ctrl+C/D, strip Rich markup, remove regenerate |
| `src/fin_assist/cli/interaction/chat.py` | Strip Rich markup from prompt text |
| `src/fin_assist/cli/main.py` | Simplify `_do_command` to linear flow (no while loop) |
| `src/fin_assist/agents/base.py` | Remove `supports_regenerate` from `AgentCardMeta` |
| `src/fin_assist/agents/shell.py` | Remove `supports_regenerate=True` |
| `src/fin_assist/cli/display.py` | Remove `supports_regenerate` rendering |
| `docs/manual-testing.md` | Fix B1, remove B3 (regenerate), renumber |
| `tests/test_cli/interaction/test_prompt.py` | Update: exceptions propagate, not swallowed |
| `tests/test_cli/interaction/test_approve.py` | Rewrite: remove regenerate tests, add Ctrl+C/D/markup tests |
| `tests/test_cli/test_main.py` | Remove regenerate/edit tests, update return types |
| `tests/test_cli/test_display.py` | Remove `supports_regenerate` rendering test |
| `tests/test_cli/test_client.py` | Remove `supports_regenerate` from test fixture |

### Test Summary

```text
Total: 371 tests, all passing (was 368 before; net +3 from new Ctrl+C/D/markup tests minus removed regenerate tests)
```

---

## Previous Session: Phase 8b — CLI REPL Mode

**Date**: 2026-04-08
**Status**: Complete (pending manual testing)

### What Was Accomplished

1. **`FinPrompt` implemented** (`cli/interaction/prompt.py`)
   - `prompt_toolkit`-backed input widget with `FuzzyCompleter(WordCompleter(...))`
   - Slash commands: `/exit`, `/quit`, `/q`, `/switch`, `/help`
   - Agent name tab completion via `agents` parameter
   - Persistent history via `FileHistory` at `~/.local/share/fin/history`
   - Ctrl-C/Ctrl-D keybindings return empty string (handled by callers)
   - Async `ask()` method using `session.prompt_async()`

2. **`chat.py` updated** — accepts optional `FinPrompt`, creates one if not provided, uses `await fp.ask(...)` for input. No `rich.prompt.Prompt` references remain.

3. **`approve.py` updated** — accepts optional `FinPrompt`, creates one if not provided, uses `await fp.ask(...)` for input. Invalid input falls through to `case _` and loops (completion-only, no hard enforcement).

4. **`main.py` updated** — constructs `FinPrompt(agents=[a.name for a in agents])` in both `_do_command` and `_talk_command`, passes down to widgets.

5. **`prompt-toolkit>=3.0`** added as explicit dependency in `pyproject.toml`.

### Design Decision Resolved

| Question | Resolution |
|----------|------------|
| FinPrompt instantiation | Constructed in `main.py`, passed to widgets via parameter. Shared instance for history continuity; testable with mocks. |

### Test Summary

```text
tests/test_cli/interaction/test_prompt.py: 8 tests (new)
Total: 368 tests, all passing
```

### Files Changed

| File | Change |
|------|--------|
| `src/fin_assist/cli/interaction/prompt.py` | **New** — `FinPrompt` class |
| `src/fin_assist/cli/interaction/chat.py` | Accept `FinPrompt`, replace `Prompt.ask` |
| `src/fin_assist/cli/interaction/approve.py` | Accept `FinPrompt`, replace `Prompt.ask` |
| `src/fin_assist/cli/main.py` | Construct `FinPrompt` with agent names, pass to widgets |
| `pyproject.toml` | Added `prompt-toolkit>=3.0` |
| `tests/test_cli/interaction/test_prompt.py` | **New** — 8 tests |

---

## Next Session: Continue Manual Testing + Phase 9

### Goals

1. **Re-verify Chunks A-B** — confirm `fin stop` now works reliably, Ctrl+C/D and markup fixes work
2. **Manual testing Chunks C-D** — chat loop and FinPrompt completions/history
3. **Begin Phase 9** (Streaming + Integration Tests) once manual testing passes

---

## Previous Phase 7 Planning Notes

Build the core "turnstile" of agents: a Starlette server that mounts N specialized agents as A2A sub-apps.

### Implementation Steps (SDD → TDD)

1. **Extend `BaseAgent` with `AgentCardMeta`** (agents/base.py)
   - Add `AgentCardMeta` dataclass: `multi_turn`, `supports_thinking`, `supports_model_selection`, etc.
   - Add `agent_card_metadata` property to `BaseAgent` with sensible defaults
   - Update existing tests

2. **Create `ShellAgent`** (agents/shell.py)
   - One-shot command generation
   - Uses `SHELL_INSTRUCTIONS` prompt
   - Returns `CommandResult` (already exists in `agents/results.py`)
   - `agent_card_metadata`: `multi_turn=False, supports_thinking=False`
   - Dynamic metadata: `{"accept_action": "insert_command"}`

3. **Implement SQLite storage** (hub/storage.py)
   - Implement fasta2a `Storage` ABC with SQLite backend
   - Tables: tasks (A2A task state) + contexts (conversation history)
   - Configurable db path via `[server]` config

4. **Implement agent factory** (hub/factory.py)
   - `BaseAgent` → pydantic-ai `Agent` → `.to_a2a()` sub-app
   - Map `AgentCardMeta` → fasta2a `Skill` + agent card extensions
   - Inject shared storage + `InMemoryBroker`

5. **Implement hub app** (hub/app.py)
   - Parent Starlette app
   - Mount each agent at `/agents/{name}/`
   - `GET /agents` discovery endpoint
   - `GET /health` health check

6. **Wire entry point** (__main__.py)
   - `fin-assist serve` starts hub via uvicorn on 127.0.0.1:4096

7. **Tests**
   - Hub creation + agent mounting
   - Discovery endpoint returns correct agent list
   - Storage CRUD (tasks + contexts)
   - ShellAgent properties + agent_card_metadata
   - Factory creates valid A2A sub-apps

### Key Files to Create/Modify

| File | Action |
|------|--------|
| `src/fin_assist/agents/base.py` | Add `AgentCardMeta`, extend `BaseAgent` |
| `src/fin_assist/agents/shell.py` | Create (one-shot command agent) |
| `src/fin_assist/hub/__init__.py` | Create |
| `src/fin_assist/hub/app.py` | Create (parent Starlette app) |
| `src/fin_assist/hub/factory.py` | Create (BaseAgent → A2A sub-app) |
| `src/fin_assist/hub/storage.py` | Create (SQLite fasta2a Storage) |
| `src/fin_assist/hub/discovery.py` | Create (GET /agents endpoint) |
| `src/fin_assist/__main__.py` | Modify (add `serve` command) |
| `tests/test_hub/` | Create (hub tests) |
| `tests/test_agents/test_shell.py` | Create (ShellAgent tests) |

### Process Notes

- Follow SDD → TDD strictly: write failing tests first
- Investigate `to_a2a()` args early — if it doesn't accept custom skills/name, we may need to use `FastA2A` directly
- Start with `InMemoryStorage` + `InMemoryBroker` to validate the mounting pattern, then swap storage to SQLite

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
| 7 | **Agent Hub Server** | ✅ Complete |
| 8 | **CLI Client** | ✅ Complete |
| 8b | **CLI REPL Mode** | ✅ Complete (manual testing next) |
| 9 | Streaming + Integration Tests | ⬜ Not Started |
| 10 | Non-blocking + interactive tasks | 📐 Sketched (see design sketch) |
| 11 | Multiplexer Integration | ⬜ Not Started |
| 12 | Fish Plugin | ⬜ Not Started |
| 13 | TUI Client (A2A) | ⬜ Not Started |
| 14 | Testing Infrastructure (Deep Evals) | ⬜ Not Started |
| 15 | Skills + MCP Integration | ⬜ Not Started |
| 16 | Additional Agents | ⬜ Not Started |
| 17 | Multi-Agent Workflows | ⬜ Not Started |
| 18 | Documentation | ⬜ Not Started |
| — | gRPC transport | Issue (track fasta2a roadmap) |

---

## Design Sketch: Interactive Task State Machine (Phase 10)

**Status**: Pre-design — no implementation. Depends on Chunks B-D (manual testing) and Phase 9 (streaming) being complete first. Sketched here so the intent is captured.

### Problem

The current `_poll_task` / `_resolve_task` logic in `HubClient` treats the A2A task lifecycle as binary: poll until terminal, then extract the result. This works for agents that run to completion without further input, but the A2A spec supports `input-required` — an agent pausing mid-task to ask the client for more information (e.g., disambiguation, confirmation, missing parameters).

Today, if an agent returned `input-required`, our poll loop would spin forever until timeout because that state isn't in `_TERMINAL_STATES` and we have no mechanism to surface the agent's question to the user.

### A2A Task State Machine

```
submitted → working → completed
                    → failed
                    → canceled
                    → rejected
                    → input-required → (client sends message) → working → ...
                    → auth-required  → (client authenticates) → working → ...
```

`input-required` and `auth-required` are **pause states** — the task is alive but blocked on the client. The client must respond with a new `message/send` using the same `context_id` to resume.

### Where This Hooks In

The changes are concentrated in three places:

**1. `HubClient._resolve_task` (client.py)**

Replace the current poll-or-return logic with a state machine dispatch:

```python
async def _resolve_task(self, agent_name: str, result: Any) -> Task:
    match result:
        case {"kind": "task"} if result["status"]["state"] in _TERMINAL_STATES:
            return result
        case {"kind": "task"} if result["status"]["state"] == "input-required":
            raise InputRequiredError(task=result)
        case {"kind": "task"}:
            return await self._poll_task(agent_name, result["id"])
        case _:
            raise RuntimeError(...)
```

`_poll_task` also needs to raise `InputRequiredError` instead of spinning when it encounters that state. `InputRequiredError` carries the task (including the agent's message asking for input) so the caller can extract what the agent needs.

**2. `run_chat_loop` (chat.py)**

The chat loop already has the interactive prompt. It would catch `InputRequiredError`, display the agent's question (from `task.status.message`), prompt the user, and send the response via `send_message` with the existing `context_id`:

```python
try:
    result = await send_message_fn(agent_name, user_input, ctx_id)
except InputRequiredError as e:
    # Display what the agent is asking
    agent_question = extract_agent_question(e.task)
    console.print(f"[yellow]{agent_question}[/yellow]")
    # Get user's response and retry with same context
    response = await fp.ask("[bold]>[/bold] ")
    result = await send_message_fn(agent_name, response, ctx_id)
```

This may need to loop (agent could ask multiple follow-up questions), so in practice it becomes a nested state machine within the chat loop.

**3. `_do_command` (main.py)**

One-shot `do` commands don't have a chat loop to fall back on. Options:
- Promote to an interactive prompt on `input-required` (breaks the "one-shot" contract)
- Fail with a clear message: "Agent needs more input — use `talk` for interactive sessions"
- The second option is cleaner and keeps `do` truly one-shot

### New Types

```python
@dataclass
class InputRequiredError(Exception):
    """Raised when an agent returns input-required state."""
    task: Task  # Carries the full task so caller can extract the agent's question

def extract_agent_question(task: Task) -> str:
    """Pull the agent's question from task.status.message or last history entry."""
    ...
```

### What Needs to Exist First

- **An agent that uses `input-required`** — without a server-side agent that actually returns this state, the client code can't be tested end-to-end. This likely comes from Phase 16 (additional agents) or Phase 15 (MCP integration where a tool needs user confirmation).
- **Streaming (Phase 9)** — `input-required` is more natural with streaming, where the agent can progressively show its reasoning before pausing for input. Without streaming, the pause is abrupt.
- **Chunks B-D passing** — the existing chat loop and approval flow need to be solid before adding a new interaction pattern on top.

### `auth-required` (deferred)

Same pattern as `input-required` but the client response is authentication rather than a text message. Deferred until there's a concrete need (e.g., an agent that calls an external API requiring OAuth). Would follow the same `AuthRequiredError` pattern.

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
- Server binds to `127.0.0.1` only (local-only)
- A2A protocol via fasta2a for multi-client support
- Multi-path routing: N agents at `/agents/{name}/`, each with own agent card
- Conversation threading via A2A `context_id`
- SQLite for task + context storage (shared across agents)
- Server lifecycle: standalone via `fin-assist serve`; auto-start from CLI deferred
- Existing TUI widgets set aside — will become A2A client in Phase 11

---

## Design Sketch: Tracing Integration (Phoenix Arize)

**Status**: Pre-design — no implementation started. To be addressed when tracing is added (likely alongside Phase 14: Deep Evals or Phase 16: Additional Agents).

### What Phoenix Is

[Arize Phoenix](https://phoenix.arize.com/) is an open-source LLM observability server. Key properties:

- Pure Python — installed via `pip install arize-phoenix`, started with `phoenix serve`
- Runs at `http://localhost:6006` by default
- Exposes OTLP endpoints: gRPC `:4317`, HTTP `:4318`
- SQLite-backed by default; data lives at `~/.phoenix/` (configurable)
- Web UI for trace inspection, evals, prompt management, experiments
- **Zero cost, zero data egress** — fully local, nothing sent to Arize

### devenv Integration Plan

Phoenix starts via `devenv up` using the native `processes` block with an HTTP ready probe:

```nix
# devenv.nix (to add when tracing is implemented)
processes.phoenix = {
  exec = "phoenix serve --port 6006";
  ready = {
    http.get = {
      port = 6006;
      path = "/healthz";  # verify exact path when implementing
    };
    initial_delay = 1;
    period = 2;
    failure_threshold = 15;  # give it ~30s to cold-start
  };
};
```

No Docker needed. Phoenix is a Python process — it lives alongside the existing uv-managed venv.

The `arize-phoenix` package would go in `pyproject.toml` as a dev dependency (not shipped with the app):

```toml
[dependency-groups]
dev = [
  "arize-phoenix>=8.0",
  # ...
]
```

Optionally expose the Phoenix port and OTLP env vars via devenv's `env` block so the app picks them up automatically on `devenv up`:

```nix
env = {
  PHOENIX_COLLECTOR_ENDPOINT = "http://localhost:6006";
  OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4318";
};
```

### fin-assist Integration Points

When tracing is added to the app itself:

| Package | Role |
|---------|------|
| `arize-phoenix-otel` | Lightweight OTEL wrapper with Phoenix-aware defaults (runtime dep) |
| `openinference-instrumentation-pydantic-ai` | Auto-instruments pydantic-ai `Agent` calls (runtime dep) |
| `arize-phoenix` | The server itself (dev dep only — not needed at runtime) |

Instrumentation wires in at hub startup:

```python
# hub/app.py or a new hub/telemetry.py
from phoenix.otel import register
from openinference.instrumentation.pydantic_ai import PydanticAIInstrumentor

def configure_tracing(endpoint: str | None = None) -> None:
    """Register Phoenix OTEL tracing. No-ops if endpoint not configured."""
    if endpoint is None:
        return
    tracer_provider = register(endpoint=endpoint, project_name="fin-assist")
    PydanticAIInstrumentor().instrument(tracer_provider=tracer_provider)
```

Called from hub lifespan with the endpoint read from config (opt-in — if not set, tracing is disabled).

### Open Questions

| Question | Notes |
|----------|-------|
| Exact `/healthz` path | Confirm when implementing — Phoenix docs show UI at `:6006` but health path needs verification |
| Config key for endpoint | Suggest `[server] phoenix_endpoint = ""` — empty string = disabled |
| Trace granularity | Per-agent-run spans at minimum; tool calls and context gathering as child spans later |
| Eval integration | Phoenix ships eval primitives — could power Phase 14 Deep Evals work |
