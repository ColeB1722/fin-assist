# Handoff Document

Rolling context for session handoffs. Updated as checkpoints are reached.

**Current state (2026-04-26)**: 694 tests passing, CI green. PR #87 (`feature/tools-plus`) self-review triage complete — all 44 review threads resolved. Phase 1 quick wins, 5 real smells, `Executor.execute()` split, three Phase 3 bug audits, and small follow-ups (`cec3b08`) landed. Phase 4 architectural discussions filed as issues [#89–#94](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+is%3Aissue+89+90+91+92+93+94).

**Core platform status:**

| Area | Status |
|------|--------|
| Executor rework + tool calling | Complete (Phases A + B merged via PR #87) |
| HITL approval | Complete (Phase C — `ApprovalPolicy`, deferred tool flow, approval widget) |
| ContextProviders dual path | Both model-driven (tools) and user-driven (`--file`/`--git-diff`) work; UX redesign deferred |
| Streaming UX (thinking + text deltas, `render_stream`) | Complete |
| Observability / tracing | Design resolved (Phoenix + OTel); implementation deferred (Phase D) |

**Deferred / tracked elsewhere:**

- Context UX redesign — both paths work, user-driven path needs rethinking. See "Context UX" sketch below.
- `@` completion in `FinPrompt` (replaces `--file`/`--git-diff` long-term) — sketch below.
- `fin do` input panel + `--edit` flag + aggregation removal — sketch below.
- AgentBackend protocol simplification ([#80](https://github.com/ColeB1722/fin-assist/issues/80))
- `_CONTEXT_TYPE_MAP` centralization — `AgentSpec._CONTEXT_TYPE_MAP` hardcodes tool→context mappings; tests read the private attribute. Also unblocks `hub/factory.py:124` which mutates private `_tool_registry`.
- CLI capabilities listing ([#88](https://github.com/ColeB1722/fin-assist/issues/88)) — `fin list tools/prompts/output-types/backends`.
- Remove built-in agents — make platform pure infrastructure; all agents defined in `config.toml`. Sketch below.

---

## PR #87 Self-Review Triage (2026-04-26)

45 review comments left on PR #87 as a notetaking mechanism (personal project, no GitHub review workflow). Worked through in phases. Handoff.md is the primary channel going forward — not posting new PR replies.

### Phase 1 — Quick wins (landed, commit `6149a2b`)

- Removed no-op `from __future__ import annotations` from `agents/__init__.py`, `cli/__init__.py`
- Removed stale root-level `hub.log` from `.gitignore` (covered by `.fin/`)
- `_key_arg_for_tool` in `streaming.py` → `match` on `(tool_name, args)` tuples
- Removed 8 redundant `dest=` kwargs in `cli/main.py` argparse
- Two if/elif chains in `cli/client.py::_stream_message` → `match meta.get("type")`
- Added "Env var naming convention" subsection to `AGENTS.md` documenting `FIN_<NAME>` vs `FIN_<SECTION>__<FIELD>` (project-specific, not industry standard)

### Phase 2 — Real smells (all landed)

| # | Smell | Commit | Fix |
|---|-------|--------|-----|
| 1 | Duplicated version envelope (`backend.py` and `context_store.py`) | `3a35e39` | Extracted to new `agents/serialization.py`; both call `wrap_payload`/`unwrap_payload`. |
| 2 | `conditional` approval mode was dead code (never dispatched) | `a30a987` | Dropped mode and `condition` field; `ApprovalPolicy.mode: Literal["never", "always"]`. pydantic-ai `Tool` has only `requires_approval: bool` — per-call predicates would require framework-specific wrapping, breaking platform neutrality. |
| 3 | `deferred_calls: list[dict[str, Any]]` at approval widget boundary | `6196778` | Promoted `DeferredToolCall` through `StreamEvent` → `render_stream` → `run_approval_widget`. |
| 4 | Logging coverage near-zero despite configured `RotatingFileHandler` | `cf2e258` | Lifecycle `logger.info` in executor (execute/cancel/pause/resume/auth) + factory (agent mount); AGENTS.md "Logging" section. |
| 5 | `Executor.execute()` was 90+ lines with interleaved concerns | `b4d788e` | Split into `_setup_task` / `_load_history` / `_start_run` / `_consume_events` / `_pause_for_approval` / `_finalize` + `_ExecutionContext` dataclass. |

### Phase 3 — Real bugs to audit

| # | Issue | Commit | Notes |
|---|-------|--------|-------|
| 1 | Subprocess cleanup in `_run_shell` (`agents/tools.py`) — `subprocess.run()` in `loop.run_in_executor` leaks child processes on asyncio cancellation | `160c6fc` | Rewrote using `asyncio.create_subprocess_shell` with `asyncio.wait_for` for timeout + `_terminate_and_wait` helper. On `CancelledError` we terminate the child and re-raise; on timeout or I/O error we terminate and return a user-visible message. Added tests for spawn failure, I/O error, timeout-terminates-child, and cancellation-terminates-child-and-propagates. |
| 2 | `factory.create_a2a_app` mutates `agent._tool_registry` post-construction (`hub/factory.py:127-128`) to make `AgentSpec.requires_approval` return correct value | `3f18230` | `AgentSpec.requires_approval` was unused in `src/` (only two tests read it). Dropped the property, the `tool_registry` constructor param on `AgentSpec`, and the factory mutation. If static per-agent approval info is ever needed, the right home is `AgentCardMeta` where the factory can compute it correctly. Backend still receives the registry directly via `PydanticAIBackend(tool_registry=...)` — that path is untouched. |
| 3 | Duck-typed `hasattr('content')` dispatch on `event.content` in executor `tool_result` handler (`hub/executor.py`) leaks pydantic-ai types (`ToolReturnPart`, `RetryPromptPart`) into framework-agnostic `Executor` | `5ddeb72` | Normalised `StepEvent.content` to `str` for `tool_result` events. Added `_extract_tool_result_text()` in `PydanticAIBackend` — handles both `ToolReturnPart` (reads `.content`, stringifies if non-string) and `RetryPromptPart` (uses `.model_response()` for a human-readable retry description). Executor now just does `Part(text=event.content)`. Documented the `content` contract per `kind` on the `StepEvent` docstring. Added 5 new tests for the extraction helper + end-to-end verification. |

### Phase 4 — Architectural discussions (filed as GitHub issues)

Each brief contains file/symbol pointers, current-behavior summary, and the specific design questions. Pick one and open a fresh session against it.

| Issue | Topic |
|---|---|
| [#89](https://github.com/ColeB1722/fin-assist/issues/89) | Hardcoded system prompts vs loadable markdown files |
| [#90](https://github.com/ColeB1722/fin-assist/issues/90) | Consolidate scattered CLI rendering constants |
| [#91](https://github.com/ColeB1722/fin-assist/issues/91) | Richer rendering for tool_result output (beyond 120-char truncation) |
| [#92](https://github.com/ColeB1722/fin-assist/issues/92) | Simplify `render_stream` state machine (needs `exa` research spike first) |
| [#93](https://github.com/ColeB1722/fin-assist/issues/93) | Repo-wide convention: protobuf struct `.attr` vs `MessageToDict + .get()` |
| [#94](https://github.com/ColeB1722/fin-assist/issues/94) | `fin do` vs `fin prompt` — clarify semantics |

### Workflow notes

Full review-thread triage complete: all 44 threads resolved (0 unresolved). Approach was reply-with-reference + resolve. Replies link to the commit that addressed the concern (Phase 1–3 landed work, or the `cec3b08` follow-up refactors) or to the Phase 4 issue that captured the design discussion (#89–#94). Threads that were pure investigation/explanation got resolved without a new reply since the earlier investigation reply already answered them.

---

## Next Session

PR #87 triage is complete. Pick from:

1. **Phase 4 design discussions** — open issues [#89–#94](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+is%3Aissue+89+90+91+92+93+94). Each issue body is a session-ready brief. `#92` has a research spike as pre-work.
2. **Deferred feature work** — design sketches below: `fin do` input panel + `--edit`, `@` context completion, remove built-in agents, client artifact-merge fix.
3. **Other open issues** — see `gh issue list` for the broader backlog.

---

## Design Sketches (not started)

### `fin do` Input Panel + `--edit` + Aggregation Removal (2026-04-26)

**Problem.** `fin do` requires a prompt on the CLI — no interactive input path. `fin talk` has `FinPrompt`, but `do` only accepts raw CLI args. Multi-word `nargs="+"` + `" ".join()` creates ambiguity with the optional `agent` positional.

**Goal.** Consistent `do`/`talk`:

| Invocation | `do` | `talk` |
|---|---|---|
| `fin do/talk` | Blank input panel | Blank input panel |
| `fin do/talk "prompt"` | Execute immediately | Send then loop |
| `fin do/talk --agent shell "prompt"` | Execute with agent | Send with agent, loop |
| `fin do/talk --edit "prompt"` | Panel pre-filled | Panel pre-filled |

**Design.**

1. Argparse: `do.prompt: nargs="?"`, `talk.message: nargs="?"`, add `--edit`, change `agent` to `--agent` flag.
2. `_do_command` three branches: no prompt → `FinPrompt.ask("> ")`; `--edit` → `fp.ask(default=prompt)`; prompt only → current. All converge on `render_stream()` → approval → `handle_post_response()`.
3. `_talk_command --edit` routes to `run_chat_loop(edit_message=prompt)`.
4. `FinPrompt.ask(default: str | None = None)` — pass through to `prompt_async()`.
5. `run_chat_loop(edit_message: str | None = None)` — first iteration pre-fills.
6. Slash commands in `do`: `/help` only; `/exit` and `/sessions` don't apply.
7. Keep `--file`/`--git-diff` as scripting fast paths until `@` completion lands.

**Tests to add:** `ask()` with `default`; `run_chat_loop` with `edit_message`; `fin do` no prompt → panel → execute; `fin do --edit`; remove tests relying on `args.prompt = [...]` aggregation.

### Context `@` Completion (2026-04-26)

**Status.** Deferred. Blocked on nothing — start after input panel lands.

**Problem.** Context injection via CLI flags (`--file`, `--git-diff`) isn't discoverable and can't be used from the input panel. `@`-completion would let users type `@file:path.py` or `@git:diff` inline in `FinPrompt`, with fuzzy completion. Works in both `do` and `talk`.

**Plan.**

1. **`@` completer in `FinPrompt`** — new `AtCompleter` (like `SlashCompleter`), triggers on `@`, calls `ContextProvider.search()`.
2. **Inline context injection** — resolve `@type:ref` via matching `ContextProvider.get_item()`, inject content (same format as `_inject_context()`).
3. **Deprecate `--file` / `--git-diff`** — add deprecation warning, remove in a later release.
4. **`/` vs `@`** — slash for actions (`/help`, `/exit`), `@` for content injection. No overlap.

**Why defer.** Input panel + `--edit` is independently valuable. `@` touches `FinPrompt`, `ContextProvider`, `_inject_context()`, and both handlers — better as a separate PR.

### Remove Built-in Agents (2026-04-25)

**Status.** Design sketch, not started. Depends on: nothing (paths sketch already landed — `FIN_DATA_DIR` in place).

**Problem.** The platform ships two hardcoded agents (`default`, `shell`) in `_DEFAULT_AGENTS`. This conflates platform infrastructure with agent design. `fin do "prompt"` hardcodes the default agent name as `"default"` rather than reading from config.

**Goal.** Empty `_DEFAULT_AGENTS`. All agents in `config.toml`. `fin do` routes to `[general] default_agent`. No default → clear error with setup guidance.

**Design.**

1. **Empty `_DEFAULT_AGENTS`** — `{}`. `Config.agents` default is empty.
2. **`[general] default_agent` config field** — CLI resolves default name from config; errors with minimal TOML example if unset.
3. **TOML agent merging — must fix.** pydantic-settings currently replaces `agents` dict wholesale. Fix in `loader.py` — merge TOML `config.agents` into defaults (TOML wins per-key). Add unit test.
4. **Local `config.toml` with `test` agent** — exercises every pluggable axis (text output + thinking + both serving modes + one no-approval tool + one approval-gated tool):

    ```toml
    [general]
    default_agent = "test"

    [agents.test]
    description = "Platform test agent — exercises every pluggable axis."
    system_prompt = "test"
    output_type = "text"
    thinking = "medium"
    serving_modes = ["do", "talk"]
    tools = ["read_file", "run_shell", "git_diff"]
    tags = ["test", "internal"]
    ```

5. **`test` system prompt** — deterministic tool-triggering prompt in `SYSTEM_PROMPTS` registry.
6. **ContextSettings fix in tool callables** — one-line bug: `_read_file`, `_git_diff`, etc. instantiate providers without passing `ContextSettings`. User-driven path passes `config.context`; model-driven uses defaults. Fix: pass settings through.
7. **Zero-agents error** — hub starts fine with no agents; CLI commands error clearly: "No agents configured. Add an `[agents.<name>]` section to your config file."
8. **`CommandResult` and `SHELL_INSTRUCTIONS` stay in the registry** — framework features available to any user agent via config.
9. **No code changes to shell agent** — it just ceases to exist as a built-in.

**Tests to write first:** `test_default_agents_empty`, `test_loader_merges_toml_agents`, `test_loader_toml_agent_keys_merge`, `test_default_agent_from_config`, `test_no_default_agent_error`, `test_no_agents_configured_error`, `test_test_agent_config_parses`, `test_tool_callables_pass_context_settings`; integration `test_test_agent_streams_text`, `test_test_agent_triggers_approval`.

### Context UX (2026-04-25) — Deferred

**Status.** Two paths work today. Model-driven is strictly more capable. Redesigning the user-driven path is a UX decision deserving its own session.

**Current state.**

- **User-driven** (`--file`/`--git-diff` on `do`): CLI reads file/diff, prepends as `Context:\n[FILE: path]\ncontent` — one big string. Model can't distinguish reference from request. Respects `ContextSettings`. Only on `do`.
- **Model-driven** (tools: `read_file`, `git_diff`, `git_log`, `shell_history`): Model decides when to fetch, gets structured results, can iterate. **Bug:** doesn't respect `ContextSettings` (tool callables miss settings). Works in both `do` and `talk`.

**Gaps.**

1. Prompt pollution in user-driven path.
2. `ContextSettings` dual-path inconsistency (bug fix included in "Remove Built-in Agents" sketch).
3. `supported_context_types` published in agent cards, never consumed.
4. `build_user_message`/`format_context` in `llm/prompts.py` are dead code.
5. Talk mode has zero user-driven context (no `@`-completion yet, no flags).
6. `git_status` provider orphaned — not exposed as a tool or flag.
7. `Environment` provider entirely unwired (intentionally, sensitive).

**Key questions for future session:**

- User-driven context as a *hint* (steer the model to call a tool) vs raw injection?
- Does `@`-completion in talk still make sense, or is model-driven sufficient?
- Do `--file`/`--git-diff` survive, evolve, or get replaced?
- How to consume `supported_context_types` — validation, auto-suggestion, both?

### Client Artifact-Merge Fix (2026-04-25)

**Status.** Design sketch, not started. Depends on: Test Agent (for regression test to be agent-driven).

**Problem.** `HubClient.stream_agent()` walks A2A response stream and yields `text_delta`/`thinking_delta` but never appends streamed artifacts into `task.artifacts`. When the task reaches terminal, `_extract_result(task)` walks empty `task.artifacts` and returns `AgentResult(output="")`. `_send_and_wait` (line 413-432) maintains a parallel artifact list and splices it back. Splice dropped in commit `b18f920`.

**Symptoms.** `fin do shell "echo hello"` exits 0 with no rendered output. `default` renders on-screen but `result.output == ""` — session continuity broken. Deferred-approval flow: `input_required` fires but `deferred_calls = []`. Integration tests pass because they only check `kind == "completed"` and `success is True`.

**Design.** Mirror `_send_and_wait`'s pattern: collect artifacts alongside yielding deltas, splice before `_extract_result` with `if not task.artifacts:` guard. Add tests asserting `result.output` and `len(deferred_calls)`.

---

## Implementation Progress

| Phase | Description | Status |
|-------|-------------|--------|
| 1–8b | Core platform (repo setup → CLI REPL) | ✅ Complete |
| — | Config-Driven Redesign | ✅ Steps 1-6 complete, Steps 7-9 deferred (context injection) |
| — | a2a-sdk migration (from fasta2a) | ✅ Complete (2026-04-20) |
| — | Backend Extraction (AgentSpec pure config) | ✅ Complete (2026-04-21) |
| — | Auth-Required Credential Pre-Check | ✅ Complete (2026-04-03) |
| — | Reliable Server Lifecycle (fcntl PID lock) | ✅ Complete (2026-04-09) |
| — | Shared Render Pipeline (`render_agent_output`) | ✅ Complete |
| — | Streaming UX Refactor (thinking in artifacts, `render_stream`) | ✅ Complete (2026-04-23) |
| — | Unified Executor + Tools + HITL (PR #87 Phases A–C) | ✅ Complete (2026-04-24/26) |
| — | `FIN_DATA_DIR` unified path | ✅ Complete |
| — | `fin do` input panel + `--edit` + `@`-completion | ⬜ Sketched above |
| — | Remove built-in agents | ⬜ Sketched above |
| — | PR #87 self-review triage (Phases 1–3) | ✅ Complete (2026-04-26) |
| — | Phase 4 architecture discussions | 📐 Filed as issues #89–#94 |
| 9b | Full SSE Streaming (was blocked on fasta2a) | ✅ Covered by a2a-sdk migration |
| 10 | Non-blocking + interactive tasks | 📐 Sketched (superseded by deferred tools) |
| 11 | Multiplexer Integration | ⬜ Not Started |
| 12 | Fish Plugin | ⬜ Not Started |
| 13 | TUI Client (A2A) | ⬜ Not Started |
| 14 | Testing Infrastructure (Deep Evals) | ⬜ Not Started |
| 15 | Skills + MCP Integration | ⬜ Not Started |
| 16 | Additional Agents | ⬜ Not Started |
| 17 | Multi-Agent Workflows | ⬜ Not Started |
| 18 | Documentation | ⬜ Not Started |
| — | Phoenix/OTel tracing | 📐 Sketched (config + instrumentation path identified) |
| — | Nix/Home Manager packaging | 📐 Sketched |

---

## Historical Reference

Key completed milestones. See git log for full detail; code is the source of truth.

### Unified Executor & Agent Platform (2026-04-24 → 2026-04-26, PR #87)

Unified five structural gaps into one coherent abstraction: executor loop (multi-step turns), tool calling, dual-path context (user-driven `@`/flags + model-driven tools), HITL approval gates, and OTel-ready step boundaries.

**Guiding principle:** the platform owns the abstractions, backends adapt them. Tools, approval, and step events are platform concepts (zero framework imports); `PydanticAIBackend` maps them to pydantic-ai Deferred Tools / Hooks. Future `LangChainBackend` etc. would map the same platform types to their own primitives.

**Phase A (Foundation) shipped.** ContextStore version byte; `StepEvent`/`StepHandle`/`_PydanticAIStepHandle`; Executor rewritten event-driven; all tests updated.

**Phase B (Tool Calling) shipped.** `ToolDefinition`/`ToolRegistry` in `agents/tools.py`; `create_default_registry()` wraps `ContextProvider`s as async callables; `AgentConfig.tools` field; `AgentSpec.supports_context()` derived from tools; `AgentCardMeta.supported_context_types`; `PydanticAIBackend` resolves tools via `tool_registry.get_for_agent(spec.tools)`; CLI `--file`/`--git-diff` flags.

**Phase C (HITL / Approval) shipped.** `ApprovalPolicy` on `ToolDefinition`; deferred tool flow end-to-end; `DeferredToolCall` dataclass; `run_approval_widget` in CLI.

**Phase D (Observability).** Design only — Phoenix + OTel via `Agent.instrument_all()` aligned to step boundaries. Not yet implemented.

### Streaming UX Refactor (2026-04-23)

Backend streams typed `StreamDelta(kind, content)` via pydantic-ai `agent.iter()`. Executor routes thinking deltas as artifacts with `metadata.type = "thinking"` (replacing post-hoc status updates). Client yields `thinking_delta` events. Shared `cli/interaction/streaming.py::render_stream()` uses Rich `Live` with initial spinner, transitions to `Group(thinking_panel?, answer_markdown)`. Both `do` and `talk` use the same pipeline. Deleted: `streamed`/`skip_text`/`was_streamed` flags, `mode == "talk"` markdown branch, post-hoc thinking status-update loop.

### AgentBackend Extraction (2026-04-21)

Extracted pydantic-ai coupling from hub into `AgentBackend` protocol. `AgentSpec` is now pure config (no `build_pydantic_agent`); all pydantic-ai knowledge in `PydanticAIBackend`. ContextStore takes `bytes` in/out — backend owns serialization. Executor takes `AgentBackend` and has zero pydantic-ai imports. `RunResult.new_message_parts: list[Part]` is the A2A domain type. Tracked simplification work as [#80](https://github.com/ColeB1722/fin-assist/issues/80).

### fasta2a → a2a-sdk Migration (2026-04-20)

Full migration from `fasta2a` (pydantic's abandoned A2A impl) to `a2a-sdk` v1.0.0 (Google's official). Hub/executor uses `TaskUpdater` for all state transitions. `InMemoryTaskStore` (ephemeral) + SQLite `ContextStore` (conversation history). Agent card uses `AgentExtension(uri="fin_assist:meta")` replacing the old `Skill(id=...)` workaround. FastAPI parent app. Client uses `ClientFactory` + `send_message` async iterator; `_poll_task()` eliminated. Streaming via `add_artifact(append=True, last_chunk=)`.

### Config-Driven Redesign (2026-04-11)

Agents went from class-hierarchy (`DefaultAgent`, `ShellAgent` subclasses) to a single `ConfigAgent` driven by TOML. `AgentConfig` in `config/schema.py` with `system_prompt`, `output_type`, `thinking`, `serving_modes`, `requires_approval`, `tags`. `ServingMode = Literal["do", "talk"]` replaces `multi_turn: bool`. `OUTPUT_TYPES` and `SYSTEM_PROMPTS` registries. Direct `Worker[list[ModelMessage]]` (closed #68 — removed private `pydantic_ai._a2a` import). Default agent shortcut via `nargs="?"`. Steps 7-9 (context injection, `@`-completion, "add context" in talk) deferred.

### Auth-Required Credential Pre-Check (2026-04-03)

Graceful early detection of missing API keys using A2A `auth-required` state. `MissingCredentialsError` raised in `BaseAgent._build_model()` before any LLM call. `FinAssistWorker` (later replaced by a2a-sdk executor) catches it and sets task state. Client renders yellow panel with provider name, env vars, credentials path. Interactive recovery deferred.

### Reliable Server Lifecycle (2026-04-09)

Server-owned PID file with `fcntl.flock()` for its entire lifetime. `atexit` + custom SIGTERM handler cleans up. Lock-based stale detection — OS releases lock if server is SIGKILL'd. `stop_server` sends SIGTERM, waits up to 10s, escalates to SIGKILL.

### Early Platform Setup (2026-03-25 → 2026-04-08)

Phases 1–8b: repo setup, core package structure, LLM module (pydantic-ai + credentials), credential UI (Textual `ConnectDialog`), context module (FileFinder/GitContext/ShellHistory/Environment providers), agent protocol & registry, agent hub server (fasta2a + SQLite), CLI client (A2A HTTP), CLI REPL mode (`FinPrompt` with prompt_toolkit, slash commands, persistent history).

---

## Context for Fresh Session

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
| `handoff.md` | This file — rolling session context |
| `pyproject.toml` | Dependencies, tool config |
| `justfile` | Task runner commands |

---

## Notes

- Target fish 3.2+ for shell integration
- Config stored in `~/.config/fin/config.toml`
- Credentials stored in `$FIN_DATA_DIR/credentials.json` (0600 permissions)
- Server binds to `127.0.0.1` only (local-only)
- A2A protocol via a2a-sdk v1.0 for multi-client support
- Multi-path routing: N agents at `/agents/{name}/`, each with own agent card
- Conversation threading via A2A `context_id`
- SQLite for context storage; `InMemoryTaskStore` for A2A tasks (ephemeral)
- Server lifecycle: standalone via `fin serve`; auto-start from CLI; fcntl-locked PID file
- `AgentSpec` is a pure config object (zero framework imports); all LLM coupling in `PydanticAIBackend`
- Platform types in `agents/` have zero `hub/` imports by design (platform vs transport separation)
