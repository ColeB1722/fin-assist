# Handoff Document

Rolling context for session handoffs. Updated as checkpoints are reached.

**Current state (2026-03-27)**: Phases 1-6 complete. Architecture pivoted to Agent Hub model. See [Architecture Pivot](#previous-session-architecture-pivot--agent-hub-design) for latest design decisions, [Next Session](#next-session-phase-7--agent-hub-server) for implementation plan, and [Implementation Progress](#implementation-progress) for phase tracker.

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
   - Phase 8: CLI Client (simple commands + Rich display)
   - Phase 8b: CLI REPL Mode (prompt-toolkit)
   - Phase 9-10: Multiplexer + Fish (deferred)
   - Phase 11: TUI Client (reuse existing widgets as A2A client)
   - Phase 13: Skills + MCP (moved up from later)
   - Phase 14: Additional Agents (SDD, TDD, code review, etc.)
   - Phase 15: Multi-agent workflows

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

## Next Session: Phase 7 — Agent Hub Server

### Goals

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
| 7 | **Agent Hub Server** | ⬜ Not Started |
| 8 | CLI Client | ⬜ Not Started |
| 8b | CLI REPL Mode | ⬜ Not Started |
| 9 | Multiplexer Integration | ⬜ Not Started |
| 10 | Fish Plugin | ⬜ Not Started |
| 11 | TUI Client (A2A) | ⬜ Not Started |
| 12 | Testing Infrastructure (Deep Evals) | ⬜ Not Started |
| 13 | Skills + MCP Integration | ⬜ Not Started |
| 14 | Additional Agents | ⬜ Not Started |
| 15 | Multi-Agent Workflows | ⬜ Not Started |
| 16 | Documentation | ⬜ Not Started |

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
