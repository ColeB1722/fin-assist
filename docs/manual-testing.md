# Manual Testing Checklist

**When to run**: Before merging a change that touches CLI commands, server lifecycle, approval flow, chat loop, agent configuration, tool execution, or the Executor/streaming path. Run the full suite before a big refactor to establish a baseline.

**Purpose**: Verify CLI integration end-to-end in ways automated tests can't — specifically subprocess lifecycle, CLI arg parsing, env var propagation, tool execution with real subprocesses, and TTY interaction. Designed so an AI agent can run the non-interactive tests autonomously, leaving only TTY-dependent tests for the human.

> All commands shown as `fin` can also be invoked as `fin-assist`.
>
> **Architecture note**: All agents are TOML config entries consumed by a single `AgentSpec` class. No per-agent Python subclasses. Agents organize their tools via **skills** — each skill bundles tools, approval rules, context injection, and prompt steering. The `run_shell` tool has `ApprovalPolicy(mode="always")`. The model decides when to call `run_shell`; the platform gates it with in-flight approval (deferred tool flow). New agents are config entries, not code changes.
>
> **Currently-implemented slash commands** in the REPL: `/exit`, `/help`, `/sessions`. Anything else will print `Unknown command: <x>`.
>
> **Context injection**: Use `@`-completion in the input panel: `@file:path.py`, `@git:diff`, `@git:log`, `@history:query`. Works in both `do` and `talk`.

---

## Test Coverage Summary (2026-05-03)

**940 tests passing.** (Latest bumps: Skills API v0.1 + skill loading refactor — `SkillDefinition`, `SkillCatalog`, `SkillLoader`, `SkillManager`, `ApprovalRule`, `ApprovalPolicy.evaluate()`, REPL `/skills` and `/skill:` commands, skill tracing; code review triage — removed `WorkflowConfig`/`--workflow` dead code, bug fixes, style fixes.)

### Coverage by module

| Module | Stmts | Miss | Cover | Key gaps |
|--------|-------|------|-------|----------|
| `agents/tools.py` | 129 | 12 | **91%** | `_terminate_and_wait` edge cases |
| `agents/backend.py` | 253 | 53 | **79%** | Deferred tool path, tool event mapping, `_build_model` multi-provider, `_request_parts_from_a2a` URL/binary paths |
| `cli/interaction/chat.py` | 91 | 10 | **89%** | Deferred approval resume exception paths, `AUTH_REQUIRED` break |
| `cli/interaction/prompt.py` | 123 | 9 | **93%** | `AtCompleter` file completion edge cases, `_CombinedCompleter` fallback |
| `cli/server.py` | 181 | 32 | **82%** | `_spawn_serve`, `_find_server_pid` /proc scanning, SIGKILL escalation, `_kill_and_cleanup` |
| `cli/main.py` | 234 | 31 | **87%** | `_do_command` deferred approval flow, `_talk_command` session resume |
| `hub/executor.py` | 120 | 4 | **97%** | `tool_result` content extraction fallback paths, error path during iteration |
| `cli/interaction/streaming.py` | 43 | 4 | **91%** | `show_thinking=True` rendering path, `input_required` event handling |
| `cli/client.py` | 238 | 7 | **97%** | `_part_struct_data` with struct_value, `_apply_status_update` with message |

### What automated tests cover well

| Layer | Coverage | What's tested |
|-------|----------|---------------|
| **Types / data** | 100% | `StepEvent`, `StepHandle`, `AgentResult`, `AgentCardMeta`, `ApprovalPolicy`, `DeferredToolCall`, `ApprovalDecision`, `ToolDefinition`, `ToolRegistry`, `ServingMode`, `MissingCredentialsError` |
| **Config** | 100% | `AgentConfig`, `Config`, TOML loading, env var overrides, empty default agents |
| **Context providers** | 84-96% | `FileFinder`, `GitContext`, `ShellHistory`, `Environment` — all with mocked subprocesses |
| **Agent spec** | 99% | `AgentSpec` properties, `check_credentials`, `tools` from config, `supports_context` |
| **Context store** | 100% | `ContextStore` load/save, version byte wrap/unwrap, persistence |
| **Factory** | 100% | `AgentFactory.create_a2a_app`, agent card extensions |
| **Credentials** | 96% | `CredentialStore` get/set, env var precedence, keyring fallback |
| **CLI display** | 95% | All `render_*` functions, `render_agent_output` dispatcher |
| **CLI prompt** | 93% | `FinPrompt`, `SlashCompleter`, `AtCompleter`, `resolve_at_references`, slash command registry |
| **CLI response** | 100% | `handle_post_response` auth/error/continue branches |
| **CLI list** | 100% | `fin list tools/skills/prompts/output-types` |

### What automated tests DON'T cover (needs manual or integration testing)

| Gap | Why not covered | Risk | Manual tests |
|-----|-----------------|------|-------------|
| **Deferred approval end-to-end** — backend emits `deferred` → executor pauses → client shows widget → user approves → resume | Spans 8 files with pydantic-ai DeferredToolRequests; no integration test with real LLM | **High** — the entire HITL flow is untested beyond unit mocks and FakeBackend integration | B1-B7, I1-I5 |
| **Full streaming lifecycle** — `stream_agent()` with real A2A protocol, artifact assembly, terminal state dispatch | `stream_agent()` is never called in tests; only internal helpers are unit-tested | **Medium** — covered by integration tests with FakeBackend, but not with real streaming | C1, C16 |
| **Server subprocess lifecycle** — `fin start`/`stop`/`status`, PID files, signal handling, orphan detection | Requires real process spawning and signaling | **Medium** — well-tested in unit with mocks, but /proc scanning and SIGKILL escalation are real OS interactions | A7-A15 |
| **Multi-provider / FallbackModel** — `_build_model` with multiple providers, failover | Requires multiple API keys configured | **Low** — single-provider path is well-tested | — |

### Integration test coverage

`tests/integration/test_client_hub.py` (21 tests) exercises HubClient → ASGI hub → FakeBackend in-process (no subprocesses, no LLM, no network).

| What integration tests cover | Test class |
|------------------------------|------------|
| Agent discovery (both agents, card_meta) | `TestAgentDiscovery` |
| One-shot dispatch (default + shell) | `TestOneShotDispatch` |
| Unknown agent error | `TestUnknownAgent` |
| Auth-required flow + recovery | `TestAuthRequired` |
| Streaming round-trip (text + thinking + auth) | `TestStreamingRoundTrip` |
| Multi-turn context preservation | `TestMultiTurnConversation` |
| Health endpoint | `TestHealthEndpoint` |
| Agent card extensions (serving_modes) | `TestAgentCardExtensions` |
| Deferred approval flow (input_required, approve, deny) | `TestDeferredApprovalFlow` |

**Not covered by integration tests** (would require real LLM or more complex FakeBackend):
- Deferred approval with real pydantic-ai DeferredToolRequests
- Tool execution during a run with real tool callables
- Structured output (CommandResult or other non-str output)
- Error propagation from backend to client mid-stream

---

## Part 1 — Automated Tests (Non-Interactive)

An AI agent can run these from a terminal, verify output, and debug failures. No TTY interaction required.

> If any of these fail, fix before moving to Part 2.
>
> **Skip if `just test` passes**: Tests marked with ~~strikethrough~~ are covered by integration tests. You only need to run them manually if you're changing the process/CLI layer (subprocess management, arg parsing, env vars, Rich rendering). For routine hub/executor/client refactors, `just test` is sufficient.

### 1a. Server Lifecycle — all manual

Integration tests can't cover subprocess management. Run all of these.

| # | Test | Command | Expected |
|---|------|---------|----------|
| A7 | Start server | `fin start` | `[dim]Hub running at http://127.0.0.1:4096[/dim]` |
| A8 | Start when running | `fin start` (already up) | Same message, no restart (idempotent) |
| A9 | Status when running | `fin status` | `Hub running at http://127.0.0.1:4096, PID <n>` |
| A15 | Port already in use | `fin serve --port 4096` | Remediation message suggesting a different port or stop, exit 1 |
| A14 | Orphan-server detection | `rm ~/.local/share/fin/hub.pid` then `fin status` | `Hub running at …(PID file missing — orphaned server)` |
| A11 | Stop server | `fin stop` | `[dim]Hub stopped.[/dim]` |
| A10 | Status when stopped | `fin status` | `Hub is not running.` |
| A12 | Stop when down | `fin stop` (already stopped) | `No running hub found (…)` error, exit code 1 |

> **Debug**: Server startup → `cli/server.py` (PID file, socket binding). Status → `cli/main.py` status command. Orphan detection → `cli/server.py` `_is_orphan`.

### 1b. Agent Listing — protocol covered, process not

| # | Test | Command | Expected | Status |
|---|------|---------|----------|--------|
| ~~A1~~ | List agents (auto-start) | `fin agents` (hub stopped) | Auto-starts server; prints agent cards from config with capability chips | Protocol covered by `TestAgentDiscovery`; run manually only to test subprocess auto-start |
| ~~A2~~ | List agents (reuse) | `fin agents` (hub up) | Same output, no restart | Same as A1 |

> **Debug**: Auto-start failures → run `fin start` manually to see logs. Card rendering → `cli/display.py`.

### 1c. Platform Capabilities — local, no hub needed

| # | Test | Command | Expected |
|---|------|---------|----------|
| L1 | List tools | `fin list tools` | Lists tools: `read_file`, `git`, `gh`, `shell_history`, `run_shell` (with approval notes from skill policies) |
| L1b | List skills | `fin list skills` | Lists skills grouped by agent, plus any SKILL.md files |
| L2 | List prompts | `fin list prompts` | Lists 7 prompts: `chain-of-thought`, `shell`, `test`, `git`, `git-commit`, `git-pr`, `git-summarize` |
| L3 | List output types | `fin list output-types` | Lists 2 types: `text` → str, `command` → CommandResult |
| L4 | Invalid resource | `fin list bogus` | Error from argparse (exit 2) |

> **Debug**: These read from local registries — no hub connection needed. Registry definitions → `agents/registry.py`, `agents/tools.py`.

### 1d. One-Shot Dispatch — protocol covered, CLI not

| # | Test | Command | Expected | Status |
|---|------|---------|----------|--------|
| ~~A4~~ | Do one-shot | `fin do "hello"` | Text panel with response, no approval widget | Protocol covered by `TestOneShotDispatch`; run manually only to test Rich rendering |
| A5 | Default agent from config | `fin do "hello"` (no `--agent`) | Resolves to `[general] default_agent` from config | **Not covered** — CLI arg parsing only |
| ~~A13~~ | Unknown agent | `fin do --agent nonexistent "hi"` | `Unknown agent 'nonexistent'. Available: …`, exit 1 | Protocol covered by `TestUnknownAgent` |

> **Debug**: Dispatch failures → hub logs (`~/.local/share/fin/hub.log`). Empty response → check LLM credentials and `Executor` wiring.

### 1e. Serving Mode Validation — metadata covered, validation not

| # | Test | Command | Expected | Status |
|---|------|---------|----------|--------|
| ~~E3~~ | Agent supports do | `fin do "hello"` | Works — `test.serving_modes = ["do", "talk"]` | Covered by `TestOneShotDispatch` + `TestAgentCardExtensions` |

> E1 (`fin do` with approval-gated tool) requires the approval widget — tested interactively in Part 2a. E4 (`fin talk`) enters the REPL — tested interactively in Part 2b.
> Debug: Validation bypassed → check `_do_command` / `_talk_command` in `cli/main.py`.

### 1f. Credentials / Auth-Required — protocol covered, env var not

| # | Test | Setup | Command | Expected | Status |
|---|------|-------|---------|----------|--------|
| ~~F1~~ | Missing API key | Unset `ANTHROPIC_API_KEY` (and other configured provider env vars) | `fin do "hello"` | Yellow "Authentication required" panel listing missing providers and env-var hints; exit 1 | Protocol covered by `TestAuthRequired`; run manually only to test env var → CredentialStore → AgentSpec propagation |
| ~~F3~~ | Recovery | Restore the env var, repeat F1 | `fin do "hello"` | Normal response | Protocol covered by `TestAuthRequired` |

> F2 (talk mode, missing key) enters the REPL — tested interactively in Part 2b.
> Debug: Auth panel not appearing → check `MissingCredentialsError` propagation and `render_auth_required` in `display.py`.

### 1g. Context Injection (`@`-completion) — unit covered, E2E not

`@`-completion is implemented in `FinPrompt`. Unit tests cover `resolve_at_references` with mocked providers; E2E requires a running LLM.

| # | Test | Command | Expected | Status |
|---|------|---------|----------|--------|
| G1 | File context | `fin do "describe @file:pyproject.toml"` | Response references file contents | **Not covered E2E** — requires LLM + real filesystem |
| G2 | Git diff context | `fin do "review @git:diff"` | Response references `git diff` | **Not covered E2E** — requires LLM + git repo |
| G5 | Missing file | `fin do "describe @file:nonexistent.txt"` | Command still runs; file content shows as error message | **Not covered E2E** |

---

## Part 2 — Interactive Tests (Requires TTY)

These require keyboard input — arrow keys, text entry, or REPL interaction. Human-run only.

> **Prerequisite**: All of Part 1 must pass before starting Part 2.

### 2a. In-Flight Approval Widget

The `test` agent has `tools = ["read_file", "git", "shell_history", "run_shell"]` where `run_shell` has `ApprovalPolicy(mode="always")`. When the model calls `run_shell`, the backend emits a `deferred` StepEvent, the executor sets the task to `INPUT_REQUIRED`, the client receives an `input_required` StreamEvent, and `render_stream` returns with `deferred_calls`. The approval widget (`approve.py`) presents each deferred tool call for Approve/Deny.

> **Critical**: This flow spans 8 files and has NO integration test coverage. It is the highest-risk interactive test.

| # | Test | Action | Expected |
|---|------|--------|----------|
| A3 | Do with approval | `fin do "list files in the current directory"` | Model calls `run_shell`, approval widget appears showing tool name (`run_shell`), args (the command), and reason ("Shell command execution requires approval") |
| B1 | Approve (default) | `fin do "echo hi"`, press Enter immediately at approval | Approve is the default selection; command runs server-side, output displayed, exit 0 |
| B2 | Approve (navigate) | Arrow-key to Approve (already there), press Enter | Same as B1 |
| B3 | Deny | Arrow-down to Deny, press Enter | `[dim]Tool call cancelled[/dim]`, no command execution, exit 0 |
| B4 | Ctrl+C | During approval prompt | Cancels (same as B3), exits cleanly |
| B5 | Ctrl+D | During approval prompt | Cancels (same as B3), exits cleanly |
| B6 | Escape | During approval prompt | Cancels (same as B3), exits cleanly |
| B7 | No text input surface | Observe | Selection-only; no text field, no completions |

> **Debug**: Widget issues → `cli/interaction/approve.py`. Deferred flow → `hub/executor.py:_handle_deferred_event` + `_extract_approval_results`. Client → `cli/client.py:stream_agent` + `_extract_deferred_calls`. Backend → `agents/backend.py:_PydanticAIStepHandle` deferred detection + `build_deferred_results`.

### 2b. REPL (`fin talk`)

Tests the full chat loop with FinPrompt, streaming, session persistence, and resume.

> Run C1 and C2 first to establish a baseline.

| # | Test | Action | Expected |
|---|------|--------|----------|
| A6 | Default agent shortcut (talk) | `fin talk` (no agent arg) | Enters REPL using `[general] default_agent` from config |
| C1 | Basic chat (streaming) | `fin talk`, type a message, Enter | Response streams progressively via `Live` + Markdown; final panel rendered |
| C2 | Exit with /exit | Type `/exit` (after at least one turn) | Chat ends, `[dim]Session saved: <slug>[/dim]` where `<slug>` is a coolname (e.g. `swift-harbor`) |
| C3 | Unknown slash command | Type `/bad` | `[yellow]Unknown command: /bad[/yellow]`, then `Type /help for available commands` |
| C4 | Empty input | Press Enter with nothing typed | No message sent, prompt returns |
| C5 | Multi-turn context | Send 2+ messages referencing earlier turns | Context preserved — replies should acknowledge prior content |
| C6 | Ctrl+C exits | Press Ctrl+C at prompt | `[dim]Exiting chat[/dim]`, chat loop ends |
| C7 | Ctrl+D exits | Press Ctrl+D at prompt | Same as C6 |
| C8 | Exit without chatting | `/exit` immediately after starting `talk` (no turns sent) | Chat ends, **no** `Session saved` message (nothing to save) |
| C9 | Session file exists | After C2, check `~/.local/share/fin/sessions/<agent>/<slug>.json` | File exists, JSON with `context_id` and metadata |
| C10 | Resume session | `fin talk --resume <slug>` (use slug from C2) | Chat resumes; prior context is in history; no new `Session saved` message on exit |
| C11 | Resume nonexistent | `fin talk --resume ghost-banana` | `Error: Session ghost-banana not found`, exit 1 |
| C12 | List sessions (--list) | `fin talk --list` | Lists saved sessions: `<slug> (context: <cid[:8]>...)`. Or `No sessions for <agent>` if empty. |
| C13 | Initial message | `fin talk "what time is it"` | First turn auto-sent, response streams, then enters REPL for follow-up |
| C14 | `/sessions` slash command | Inside REPL, type `/sessions` | Lists saved sessions for the current agent (same format as `--list`) |
| C15 | `/help` slash command | Inside REPL, type `/help` | Prints available slash commands |
| C16 | `--show-thinking` | `fin talk --show-thinking`, chat once | Thinking blocks (if the model emits them) appear in the output |
| F2 | Talk mode, missing key | Unset `ANTHROPIC_API_KEY`, then `fin talk`, send one message | Yellow "Authentication required" panel; then `[dim]Fix credentials and try again.[/dim]`; chat loop exits |

> **Debug**: REPL issues → `cli/interaction/chat.py`, `FinPrompt`. Streaming issues → `_PydanticAIStepHandle` in `agents/backend.py`. Session issues → session persistence code.

### 2c. In-Flight Approval in Talk Mode

Tests the deferred approval flow within the chat loop. When the agent calls a tool requiring approval mid-conversation, the chat loop should show the approval widget, then resume streaming after the decision.

> **Prerequisite**: B1 and C1 must pass first.

| # | Test | Action | Expected |
|---|------|--------|----------|
| I1 | Approval in talk (approve) | `fin talk`, ask it to run a shell command (e.g. "run ls using the run_shell tool") | Model calls `run_shell` → approval widget appears → approve → command runs server-side → output displayed → chat continues |
| I2 | Approval in talk (deny) | Same as I1, but deny | `[dim]Tool call cancelled[/dim]` → chat continues (can send more messages) |
| I3 | Approval in talk (cancel) | Same as I1, but Ctrl+C | `[dim]Tool call cancelled[/dim]` → chat continues |
| I4 | Multi-turn after denial | Deny a tool call, then send another message | Chat loop continues normally; context preserved |
| I5 | Approval + session save | Approve a tool call, then `/exit` | Session saved with the full conversation including the approved tool result |

### 2d. Prompt Completions & History

Tests FinPrompt features: fuzzy slash completion, `@`-completion, and persistent history. Run after C1/C2 confirm the basic REPL works.

| # | Test | Action | Expected |
|---|------|--------|----------|
| D1 | Slash trigger | Type `/` then Tab | Completion menu shows `/exit`, `/help`, `/sessions` + agent names |
| D2 | Fuzzy /exit | Type `/ex`, Tab | Completes to `/exit` |
| D3 | Fuzzy /help | Type `/he`, Tab | Completes to `/help` |
| D4 | Fuzzy /sessions | Type `/se`, Tab | Completes to `/sessions` |
| H1 | `@` trigger | Type `@` then Tab | Shows context-type options (`file:`, `git:diff`, `git:log`, `history:`) |
| H2 | `@file:` completion | Type `@file:` + partial path + Tab | Shows matching files |
| H3 | `@git:` completion | Type `@git:` + Tab | Shows `diff`, `log` |
| H4 | `@history:` completion | Type `@history:` + Tab | Shows recent shell history |
| D5 | History up | Press Up arrow in an empty prompt | Previous input recalled |
| D6 | History down | Press Down after Up | Next/empty |
| D7 | History persists | Exit (`/exit`), re-launch `fin talk`, press Up | Previous session's input available |
| D8 | History file | `cat ~/.local/share/fin/history` | File exists; format is prompt_toolkit `FileHistory` (entries prefixed with `+`, timestamp comments with `#`) — not bare lines |

> Debug: Completion issues → cli/interaction/prompt.py completion config. History issues → FileHistory wiring in same file.
> Note: Slash commands that used to be planned (`/quit`, `/q`, `/switch`) do **not** exist. Don't test them.

### 2e. Skills API

Tests skill listing, skill-driven approval, and dynamic skill loading.

| # | Test | Action | Expected |
|---|------|--------|----------|
| S1 | List skills | `fin list skills` | Skills grouped by agent name. Each agent shows its skills with tool list and description. SKILL.md files section if any exist. |
| S2 | Skill via positional | `fin do git commit` | agent=git, skill=commit (entry_prompt sent, prompt_template injected as [Skill context]) |
| S3 | Skill via --skill flag | `fin do --skill commit --agent git "my changes"` | Same skill activation as S2 |
| S4 | Approval with rules | `fin do git "show me the diff"` | `git diff` matches rule with mode=never → no approval widget |
| S5 | Approval default | `fin do git "push to origin"` | `git push` falls through rules → default=always → approval widget appears |
| S6 | Skill in talk mode | `fin talk --agent git`, ask to commit | Model may call `load_skill("commit")` → confirmation message → commit skill tools available |

### 2f. Shell Agent Exercise

**Goal**: Develop an initial shell agent by using fin-assist interactively to perform real development tasks. This validates the full agent loop end-to-end and surfaces UX issues that automated tests can't catch.

**Setup**: Start from a clean repo state (no staged changes, on a feature branch).

| # | Task | What to try | What to verify |
|---|------|-------------|----------------|
| X1 | Create a PR | `fin do git "create a PR for the current branch"` | Agent uses git/gh skills, reads files, generates PR description, creates PR via `gh` |
| X2 | Generate a commit | Make a small change, then `fin do git commit` | Agent analyzes diff, generates conventional commit message, stages and commits |
| X3 | Summarize changes | `fin do git summarize` | Agent reads diffs without executing mutating commands (summarize skill is read-only) |
| X4 | Explore repo | `fin do "what files are in this project?"` | Agent uses `read_file` skill, lists project structure, no approval needed |
| X5 | Shell command | `fin do "run ls -la"` | Agent uses `run_shell` skill → approval widget appears → approve → output displayed |
| X6 | Multi-skill session | `fin talk --agent git`, alternate between commit/PR/summarize | Skills load dynamically, catalog updates, tools available after loading |

**What to watch for**:
- Does the agent choose the right skill for the task?
- Does `load_skill` work smoothly in multi-turn conversations?
- Are approval rules correct (never for read-only, always for mutating)?
- Does the skill catalog text clutter the system prompt or is it concise?
- Any crashes or error messages when skills are loaded/unavailable?

---

## Test Gap Register

Known gaps in automated test coverage that should be addressed before or alongside manual testing. Ordered by risk.

| Gap | Source lines | Risk | Mitigation |
|-----|-------------|------|------------|
| `_PydanticAIStepHandle` deferred path | `agents/backend.py:186-203` | **High** — the `DeferredToolRequests` detection and `deferred` StepEvent emission is untested with real pydantic-ai | Add unit test that constructs a mock `AgentRun` with `DeferredToolRequests` output. Add integration test with `FakeBackend` that emits deferred events. |
| `chat.py` deferred approval resume | `cli/interaction/chat.py:117-137` | **High** — the `run_approval_widget` → `render_stream(approval_decisions=...)` path is untested | Add unit test with mocked `stream_fn` and `run_approval_widget`. |
| `_do_command` deferred approval resume | `cli/main.py:253-266` | **High** — same as chat.py but for the `do` command path | Add unit test with mocked `client.stream_agent` and `run_approval_widget`. |
| `stream_agent` with `approval_decisions` | `cli/client.py:330-338` | **Medium** — the `approval_result` Part construction is untested | Add unit test verifying Part metadata construction. |
| Executor `tool_call`/`tool_result` dispatch | `hub/executor.py:229-266` | **Low** — unit tests verify artifact content, metadata, and append semantics; `tool_result` content fallback paths untested | Covered by `TestExecutorToolCallDispatch` and `TestExecutorArtifactAppendSemantics` |
| `_CONTEXT_TYPE_HINTS` centralization | `agents/spec.py:43-48` | **Low** — module-level constant hardcodes tool→context mappings | Derive from `ToolRegistry` + `ContextProvider` metadata in a future refactor. |

---

## Running Order

```text
just test  ←  924 tests
               Covers: types, config, context (mocked), agent spec, context store,
                       factory, credentials, display, prompt, @-completion, response,
                       integration: discovery, dispatch, auth, streaming, multi-turn

just test-cov  ←  per-file coverage report (identifies gaps above)

Part 1 (Manual) — agent runs only the uncovered tests
┌──────────────────────────────────────────────────────────┐
│ 1a. Server Lifecycle (A7-A15) — all manual               │
│ 1c. Platform Capabilities (L1-L4) — local, no hub       │
│ A5  (default agent from config — CLI arg parse)          │
│ G1, G2, G5 (@-completion — requires LLM)                │
│ F1/F3 (optional — env var propagation only)              │
└────────────────────────┬─────────────────────────────────┘
                         │ all pass
                         ▼
Part 2 (Interactive) — human at TTY
┌──────────────────────────────────────────────────────────┐
│ 2a. In-Flight Approval (A3, B1-B7)        ← HIGHEST RISK│
│                                                          │
│ 2b. REPL (A6, C1-C16, F2)                               │
│     │                                                    │
│     ├── 2c. Approval in Talk (I1-I5)  ← needs 2a + 2b  │
│     │                                                    │
│     └── 2d. Completions + History (D1-D8, H1-H4)        │
│         (after C1/C2 confirm REPL works)                 │
│                                                          │
│ 2e. Skills API (S1-S6)                                   │
│ 2f. Shell Agent Exercise (X1-X6)                        │
└──────────────────────────────────────────────────────────┘
```

---

## Pre-Refactor Smoke Set

Before a big refactor, run the minimum set most likely to catch regressions:

**Automated** (`just test`): 940 tests covering protocol layer + streaming + multi-turn + card extensions + auth + types + config + @-completion + artifact append semantics + tracing (hub + CLI + pause/resume continuity) + skills API

**Manual (agent runs)**: A7–A15 (server lifecycle), L1–L4 (platform capabilities), A5 (default from config)

**Interactive (human runs)**:
- Approval: B1, B3, B4 (Approve-default, Deny, Ctrl+C) — **highest priority**
- REPL: C1, C5, C10, C13 (streaming, multi-turn, resume, initial-message)
- Credentials: F2 (auth-required in talk mode)

---

## If a Test Fails

1. Note test ID and section.
2. **Automated failures**: the agent can debug and fix inline.
3. **Interactive failures**: file a bug or branch a fix.
4. A second session can work another section in parallel.

---

## Notes

- Server auto-starts on first `do`/`talk`/`agents` via `ensure_server_running` (`cli/server.py`).
- `fin stop` uses PID file; falls back to `/proc` scan for orphans. See A14.
- Session slugs are coolnames from `coolname.generate_slug(2)` — e.g. `swift-harbor`, not UUIDs.
- History file: `~/.local/share/fin/history`. Sessions dir: `~/.local/share/fin/sessions/<agent>/<slug>.json`.
- The "Session saved" message only prints when (a) at least one turn completed, AND (b) the session is not a resume.
- `fin do "prompt"` / `fin talk` (no `--agent`) → `[general] default_agent` from config.
- All agents are config entries. The dev `test` agent uses `output_type = "text"` with skills `files`, `git`, `history`, `shell`.
- Context injection uses `@`-completion in the input panel: `@file:path.py`, `@git:diff`, `@git:log`, `@history:query`. The `--file`/`--git-diff` CLI flags have been removed.
- `fin serve` runs the hub in the foreground (distinct from `fin start` which daemonizes). Useful for development; see A15.
- The approval model uses `ApprovalPolicy` (with per-subcommand `ApprovalRule`s) on `ToolDefinition`, enforced in-flight by the backend (deferred tools), verified by the Executor. Skill-level approval overrides take precedence over tool defaults.
- `fin list tools/skills/prompts/output-types` shows platform registry contents without requiring a hub connection.
