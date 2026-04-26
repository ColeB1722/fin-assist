# Handoff Document

Rolling context for session handoffs. Updated as checkpoints are reached.

**Current state (2026-04-25)**: Phases A–C complete, code reviewed, merged via PR #87. Executor `append=True` artifact bug fixed. 635 tests passing, 91% coverage, CI green.

**Two active sketches + one deferred:**

1. **Executor rework + tool calling** — Phase A + Phase B complete. Tools registered, context-as-tools working, CLI flags wired.
2. **ContextProviders → dual path** — **Resolved in Phase B.** Model-driven path (tool calls) and user-driven path (`--file`/`--git-diff` CLI flags) both implemented. Context UX redesign deferred (see sketch below).
3. **HITL approval** — **Phase C complete.** `ApprovalPolicy` on `ToolDefinition`, deferred tool flow, approval widget in CLI.
4. **Observability / tracing** — Design resolved (Phoenix + OTel). Implementation independent (Phase D).

**Next session plan:** remove built-in agents, fix artifact-merge bug, local dev paths. See "Next Session" section below.

**Deferred:**
- Context UX redesign — both paths work, model-driven is strictly more capable, user-driven needs rethinking. See "Context UX" sketch.
- AgentBackend protocol simplification ([#80](https://github.com/ColeB1722/fin-assist/issues/80)) — revisit when a second backend is needed

---

## Next Session (2026-04-25)

Manual test run surfaced a silent-exit bug in `fin do shell "…"`: CLI exits 0 with no output. Root cause is a client-side artifact-merge bug compounded by thin test coverage. A separate design session revised the plan:

**Core decision: remove built-in agents entirely.** The platform ships with zero hardcoded agents. All agents are user-defined via `config.toml`. This kills the "shell migration" loose end (sketch #4 from previous plan — nothing to migrate) and forces the platform to be pure infrastructure.

**Four sketches, in dependency order:**

1. **Local Dev Paths** — quickest win; unblocks ergonomics.
2. **Remove Built-in Agents** — empty `_DEFAULT_AGENTS`, TOML merge fix, `test` agent in local config for manual platform testing, `[general] default_agent` config field, helpful error when no agents exist.
3. **Client Artifact-Merge Fix** — the actual silent-exit bug. Regression test uses whatever agent is in local config.
4. **Context UX** — **deferred to a future session.** Dual-path context (user-driven vs model-driven) has known gaps but both paths work. Document gaps; fix `ContextSettings` bug in tool callables as a one-line fix during sketch #2. Full context UX redesign is its own sketch later.

Each is its own commit (or PR).

---

## Design Sketches

### Local Dev Paths (2026-04-25) — Design Sketch

**Status: Design sketch, not started.**

**Problem.** Runtime state scatters across `~/.local/share/fin/` even during local development, making `rm -rf` cleanup awkward, leaving stale state on the user's machine across branches, and obscuring the relationship between a checkout and its data. `devenv.nix` already localizes `hub.log` via `FIN_SERVER__LOG_PATH = "./hub.log"`, proving the pattern works — but only one path is covered. `src/fin_assist/paths.py` hardcodes the other four (`PID_FILE`, `SESSIONS_DIR`, `HISTORY_PATH`, `CREDENTIALS_FILE`) with no env-var escape hatch. `ServerSettings.db_path` has an env override (`FIN_SERVER__DB_PATH`) but `devenv.nix` doesn't use it.

**Goal.** One env var — `FIN_DATA_DIR` — pins every runtime path under a single directory. `devenv.nix` sets it to `./.fin` (or similar) so a fresh clone gets all runtime state colocated with the repo, trashable with `rm -rf .fin`.

**Design.**

1. **`paths.py` honors `FIN_DATA_DIR`.** Replace the hardcoded `DATA_DIR = Path("~/.local/share/fin").expanduser()` with:

    ```python
    DATA_DIR = Path(os.environ.get("FIN_DATA_DIR", "~/.local/share/fin")).expanduser()
    ```

    All derived paths (`SESSIONS_DIR`, `HISTORY_PATH`, `PID_FILE`, `CREDENTIALS_FILE`) continue to be `DATA_DIR / <name>` and get the override for free. Module-level read is fine — env is set by the shell before import.

2. **`ServerSettings` defaults track `DATA_DIR`.** Change `db_path` and `log_path` defaults from string literals to derive from `paths.DATA_DIR` at class-construction time. Since pydantic defaults are evaluated at import, use a `@model_validator(mode="before")` or a default factory that reads `paths.DATA_DIR`. Env overrides (`FIN_SERVER__DB_PATH`, `FIN_SERVER__LOG_PATH`) still win for per-path tuning.

3. **`devenv.nix` flips to `FIN_DATA_DIR`.** Replace the per-path overrides with:

    ```nix
    FIN_DATA_DIR = "./.fin";
    ```

    Drop `FIN_SERVER__LOG_PATH` — redundant once `log_path` derives from `DATA_DIR`. Add `.fin/` to `.gitignore`.

4. **`AGENTS.md` updated.** New "Local Development Paths" section already added. Update the table's "Env override" column to reflect the unified var once implemented.

**Tests to write first (TDD).**

- `test_paths_honors_fin_data_dir` — set `FIN_DATA_DIR=/tmp/fin-test`, reimport `paths` (via `importlib.reload`), assert every derived path sits under `/tmp/fin-test`.
- `test_server_settings_db_path_follows_data_dir` — same pattern, assert `ServerSettings().db_path` ends with `hub.db` under the custom dir.
- `test_fin_server_log_path_env_overrides_data_dir` — set both; assert the specific override wins.
- `test_paths_default_still_home_local_share` — unset `FIN_DATA_DIR`, assert the old path is preserved.

**Risks / considerations.**

- **Module-level reads.** `paths.py` reads env at import. If any test imports `paths` before setting `FIN_DATA_DIR`, the module caches the wrong value. Mitigation: tests that mess with `FIN_DATA_DIR` must use `importlib.reload(paths)` or be parameterized via monkeypatch + fresh subprocess. The cleanest alternative is to convert `DATA_DIR` etc. to functions (`data_dir() -> Path`), but that changes every call site. Stick with module-level for now; flip to functions only if it causes test pain.
- **`_spawn_serve` child process.** The child inherits the parent's env, so `FIN_DATA_DIR` propagates automatically. No extra wiring needed.
- **User-facing breaking change?** No — the default stays `~/.local/share/fin/`. Only users who set `FIN_DATA_DIR` see the new behavior.

**Out of scope.** Migrating existing data in `~/.local/share/fin/` on first run. We're not doing lifecycle management; this is pure config plumbing.

---

### Remove Built-in Agents (2026-04-25) — Design Sketch

**Status: Design sketch, not started. Depends on: Local Dev Paths (for `./config.toml` to live alongside `./.fin/`).**

**Problem.** The platform ships two hardcoded agents (`default`, `shell`) in `_DEFAULT_AGENTS`. This conflates platform infrastructure with agent design — the platform should be pure infrastructure with zero opinions about what agents exist. The shell agent is half-migrated from the old approval model, creating a phantom "pending migration" that's really a UX decision, not a platform task. Meanwhile, `fin do "prompt"` hardcodes the default agent name as `"default"` rather than reading from config.

**Goal.** Empty `_DEFAULT_AGENTS`. All agents defined in `config.toml`. `fin do "prompt"` routes to `[general] default_agent` in TOML. No default set → clear error with setup guidance. The platform is pure infrastructure — agents are entirely user-defined.

**Design.**

1. **Empty `_DEFAULT_AGENTS`.** Change `_DEFAULT_AGENTS` to `{}`. The `Config.agents` field stays `dict[str, AgentConfig]` with an empty default. All agents come from config.

2. **`[general] default_agent` config field.** Add `default_agent: str | None = None` to `Config` (or the general settings section). CLI resolves the default agent name from config instead of hardcoding `"default"`:
   - `fin do "prompt"` → reads `config.general.default_agent` → uses that agent name
   - No default set → error: "No default agent configured. Set `[general] default_agent = \"myagent\"` in config.toml or use `fin do <agent> \"prompt\"`."
   - Show a minimal TOML example in the error message (one agent + default_agent)
   - Same for `fin talk` (no agent arg → uses default)

3. **TOML agent merging — must fix.** pydantic-settings currently replaces the `agents` dict wholesale when TOML defines any `[agents.<name>]`. So a `config.toml` that only declares `[agents.assistant]` *loses* any other agents defined elsewhere. Fix: merge in `loader.py` — before returning, merge TOML `config.agents` into defaults (TOML wins per-key). Since defaults are now empty, this only matters when users have multiple config sources, but the fix is still needed for correctness. Add a unit test: TOML with `[agents.assistant]` and `[agents.coder]` → config has both.

4. **Local `config.toml` with a `test` agent.** For manual platform testing, a local `config.toml` in the repo root defines a `test` agent that exercises every pluggable axis:

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

    Axes covered: text output + thinking deltas + both serving modes + one no-approval tool (`read_file`) + one approval-gated tool (`run_shell`) + a second no-approval tool for tool-call event coverage (`git_diff`).

5. **`test` system prompt.** New entry in `SYSTEM_PROMPTS` registry (`agents/registry.py` → `llm/prompts.py`). Engineered to make the model deterministically call the requested tool based on the user's prompt:

    ```
    You are a test agent. Your job is to exercise specific platform features on command.

    When the user says "test approval", call the `run_shell` tool with `echo approved`.
    When the user says "test read", call the `read_file` tool with path "/etc/hostname".
    When the user says "test diff", call the `git_diff` tool with no args.
    When the user says "test thinking", think step-by-step for 3 sentences, then reply "done".
    When the user says "test text", reply "hello world" with no tool calls.
    Otherwise, respond naturally.
    ```

6. **ContextSettings fix in tool callables.** One-line bug fix: tool callables in `agents/tools.py` (`_read_file`, `_git_diff`, etc.) instantiate `ContextProvider`s without passing `ContextSettings`. The user-driven path passes `config.context` but the model-driven path uses defaults. Fix: pass settings through. This is a bug, not a design change.

7. **Error message for zero agents.** When the hub starts with no agents configured (empty `config.agents` and no TOML), the startup should still succeed (the platform is valid with zero agents). But any CLI command that tries to use an agent should error clearly: "No agents configured. Add an `[agents.<name>]` section to your config file."

8. **`CommandResult` and `SHELL_INSTRUCTIONS` stay in the registry.** They're framework features, not agent-specific. Any user-defined agent can opt into `output_type = "command"` or `system_prompt = "shell"` via config.

9. **No code changes to `shell` agent config or system prompt.** The shell agent simply ceases to exist as a built-in. If a user wants a shell agent, they define one in TOML. The half-migration question is moot — there's nothing to migrate.

**Tests to write first (TDD).**

- `test_default_agents_empty` — `_DEFAULT_AGENTS` is `{}`.
- `test_loader_merges_toml_agents` — TOML declaring `[agents.assistant]` → `config.agents` has `assistant`.
- `test_loader_toml_agent_keys_merge` — TOML declaring `[agents.assistant]` and `[agents.coder]` → both present.
- `test_default_agent_from_config` — `Config(default_agent="assistant", agents={"assistant": AgentConfig(...)})` → CLI resolves default to "assistant".
- `test_no_default_agent_error` — `Config(default_agent=None, agents={...})` → `fin do "prompt"` → error with TOML example.
- `test_no_agents_configured_error` — `Config(agents={})` → `fin do test "prompt"` → error about no agents.
- `test_test_agent_config_parses` — the actual `./config.toml` block validates into an `AgentConfig`.
- `test_tool_callables_pass_context_settings` — `_read_file` etc. receive and use `ContextSettings`.
- Integration: `test_test_agent_streams_text` — dispatch "test text" → assert output contains "hello world".
- Integration: `test_test_agent_triggers_approval` — dispatch "test approval" → assert `input_required` with `run_shell` deferred call.

**Risks / considerations.**

- **Fresh install experience.** A bare `fin` install with no config has zero agents and no default. Every command errors until the user writes config. This is acceptable — it's a personal platform, not a consumer product. The error message must be excellent (show a complete minimal TOML example).
- **TOML discovery.** The existing cwd-discovery in `loader.py:_resolve_config_path` finds `config.toml` in the current directory. This works for local dev (repo root). For installed use, users need `~/.config/fin/config.toml`. Both paths already work.
- **Prompt determinism.** LLMs aren't 100% deterministic. The `test` prompt must be brittle enough that any reasonable model follows it verbatim. If flakes appear, tighten the prompt or gate the test on a specific model.
- **Breaking change.** Anyone relying on `fin do default "..."` or `fin do shell "..."` will break. Since this is a personal platform with one user, this is fine. The error messages guide migration.

**Out of scope.** Adding agent variants beyond `test` upfront. Deciding the long-term UX for a shell-like agent. That's a separate design decision when the need arises.

---

### Client Artifact-Merge Fix (2026-04-25) — Design Sketch

**Status: Design sketch, not started. Depends on: Test Agent (for the regression test to be agent-driven and realistic).**

**Problem.** `HubClient.stream_agent()` in `cli/client.py:312-394` walks the A2A protocol response stream and, for each `artifact_update`, yields `text_delta` / `thinking_delta` events directly — but never appends the streamed artifact into `task.artifacts`. When the task reaches a terminal state, `_extract_result(task)` walks `task.artifacts` (empty) and returns `AgentResult(output="")`. Compare `_send_and_wait` (line 413-432) which maintains a parallel artifact list and splices it back into `task.artifacts` before extraction. The splice was dropped in commit `b18f920` ("streaming fix") when the streaming path was refactored.

**Symptoms.**

- `fin do shell "echo hello"` exits 0 with no rendered output (shell agent emits a structured `CommandResult` with no `text_delta` events — nothing renders in `render_stream`, and `result.output == ""` so `handle_post_response` prints nothing either).
- `default` agent renders fine on-screen (via `Live` deltas) but `result.output == ""` — session continuity and any post-stream consumer is silently broken.
- Deferred approval flow: `input_required` event still fires (state-based), but `event.deferred_calls = []` because `_extract_deferred_calls(task)` walks the same empty `task.artifacts`. The approval widget receives zero calls → silently no-ops.
- Integration tests pass because `TestStreamingRoundTrip` asserts only `events[-1].kind == "completed"` and `result.success is True`; never checks `result.output`. `TestDeferredApprovalFlow.test_stream_yields_input_required` checks the event kind but not `len(deferred_calls) > 0`.

**Design.**

Mirror `_send_and_wait`'s pattern inside `stream_agent`:

```python
task: Task | None = None
artifacts: list[Any] = []          # NEW
accumulated_thinking: list[str] = []

async for response in client.send_message(request):
    is_terminal, resp_task, artifact = self._process_response(response)
    if artifact is not None:
        artifacts.append(artifact)  # NEW — collect alongside yielding deltas
        for part in artifact.parts:
            ...  # existing delta-yielding logic unchanged
    if resp_task is not None:
        task = resp_task
    if response.HasField("status_update") and task is not None:
        self._apply_status_update(task, response.status_update)
    if is_terminal:
        break

if task is not None:
    if artifacts and not task.artifacts:  # NEW — splice before extract
        for artifact in artifacts:
            task.artifacts.append(artifact)
    state = task.status.state
    result = self._extract_result(task)
    ...  # rest unchanged
```

Minimal and surgical. Matches the existing `_send_and_wait` implementation exactly, so there's a visible consistency invariant between the two methods.

**Tests to write first (TDD).**

Unit tests in `tests/test_cli/test_client.py`:

- `test_stream_agent_populates_result_output_from_artifacts` — mock A2A client yielding `[initial_task, artifact_update(text="hello world"), status_update(COMPLETED)]` → assert `events[-1].result.output == "hello world"`.
- `test_stream_agent_populates_deferred_calls_from_artifacts` — same setup but final state INPUT_REQUIRED with a deferred-metadata part → assert `len(events[-1].deferred_calls) == 1` and fields populated.
- `test_stream_agent_preserves_existing_task_artifacts` — if the final `task` event already has artifacts (non-streaming server variant), don't duplicate. The `if not task.artifacts` guard covers this; test it explicitly.

Integration tests (tighten existing):

- `TestStreamingRoundTrip.test_stream_ends_with_completed` — add `assert events[-1].result.output == "response from default"`.
- `TestDeferredApprovalFlow.test_stream_yields_input_required` — add `assert len(terminal_events[-1].deferred_calls) == 1`.

**Risks / considerations.**

- **Double-append risk.** If the A2A protocol ever sends the final artifacts both as `artifact_update` chunks AND embedded in a later `task` event, the `if not task.artifacts` guard prevents duplication. The guard is already in `_send_and_wait`; keep the invariant consistent.
- **Memory on long streams.** Collecting all artifacts plus yielding deltas means we keep text in memory twice until terminal. For the current single-artifact-per-task pattern this is trivial. If streaming ever produces many artifacts, revisit — but that's a future concern.
- **Doesn't fix the test-integration gap alone.** Tests that assert only on `kind` and `success` will keep passing. Tightening assertions is part of this fix, not a follow-up.

**Out of scope.** Refactoring `_send_and_wait` and `stream_agent` to share artifact-collection logic. They're already similar enough; factoring is cosmetic and risks regressions. Revisit if a third caller appears.

---

### Retire "Phase C Shell Migration" Loose End (2026-04-25) — Moot

**Status: Moot — built-in agents are being removed (see "Remove Built-in Agents" sketch).**

The shell agent won't exist as a built-in anymore, so there's nothing to migrate. The platform supports the deferred-approval flow; whether any user-defined agent uses it is a config decision, not a platform task. `CommandResult` and `SHELL_INSTRUCTIONS` stay in the registry as framework features available to any agent via config.

---

### Context UX (2026-04-25) — Deferred Sketch

**Status: Deferred to a future session. Known gaps documented here. One bug fix (`ContextSettings` in tool callables) included in "Remove Built-in Agents" sketch.**

**Current state.** Two paths for providing context to the model:

**User-driven** (`--file`/`--git-diff` on `fin do`):
- CLI reads file/diff content before sending to the hub
- Prepends to prompt string: `Context:\n[FILE: path]\ncontent\n\nUser request:\nprompt`
- Model sees one big string — can't distinguish reference material from request
- Respects `ContextSettings` (max file size, etc.)
- Only on `do`, not `talk`
- `--git-log` flag not wired (low priority)
- `supported_context_types` published in agent cards but never consumed for validation

**Model-driven** (tool calls: `read_file`, `git_diff`, `git_log`, `shell_history`):
- Model decides when it needs context, calls the tool, gets structured results back
- Can iterate ("now read a different file", "show me more history")
- **Bug:** does not respect `ContextSettings` — tool callables instantiate providers without passing settings (fix included in sketch #2)
- Works in both `do` and `talk`

**Known gaps.**

1. **Prompt pollution.** User-driven context merges everything into one string. The model can't reason about "this is reference, this is my request" separately. Tool-call context doesn't have this problem.

2. **Dual-path `ContextSettings` inconsistency.** `--file` respects `max_file_size` from config; `read_file` tool doesn't. Same provider, different limits depending on how it's invoked. (Bug fix in sketch #2.)

3. **`supported_context_types` dead code.** Published in agent cards, never consumed. `--file` works on any agent regardless of tools list.

4. **`build_user_message`/`format_context` in `llm/prompts.py` are dead code.** Duplicates `_inject_context` logic but nothing calls them from the request path.

5. **Talk mode has zero user-driven context.** No `@`-completion, no flags. Model can only get context via tool calls — which works fine but removes the user-steering benefit.

6. **`git_status` provider orphaned.** `GitContext` provides `git_status` but it's not exposed as a tool or CLI flag.

7. **`Environment` provider entirely unwired.** Intentionally not exposed (sensitive), no CLI flag.

**Why defer.** Both paths work today. The model-driven path is strictly more capable. Redesigning the user-driven path is a UX decision that deserves its own focused session. Key questions for that session:

- Should user-driven context be a *hint* (steer the model to read a file via tool) rather than raw injection?
- Should `@`-completion in talk mode still happen, or is model-driven context sufficient?
- Should `--file`/`--git-diff` survive, evolve, or be replaced?
- How should `supported_context_types` be consumed — validation, auto-suggestion, both?

**What's happening this round.** Fix the `ContextSettings` bug in tool callables. Everything else waits.

---

### Streaming UX Refactor (2026-04-23) — Complete

**Status: All phases (A–E) complete. 510 tests passing, CI green.**

**Problem.** Agent output is half-streamed: text deltas stream, but thinking appears *after* the answer, as post-hoc a2a status-update messages. There's no spinner while waiting for the first token. Markdown doesn't render inside thinking blocks or inside `do`-mode panels. `fin do` is fully blocking — no streaming at all. The half-streamed state has leaked into the rendering layer as `streamed`/`skip_text` flags.

**Design.**

1. **`StreamDelta`** — typed stream chunks from backend: `kind: Literal["text", "thinking"]`, `content: str`. Replaces raw `str` deltas in `StreamHandle.__aiter__`.
2. **pydantic-ai `agent.iter()`** — backend rewritten to walk the agent graph node-by-node. For each node that exposes `.stream(ctx)`, iterate `PartStartEvent`/`PartDeltaEvent` and map `TextPart`/`TextPartDelta` → `StreamDelta("text", ...)` and `ThinkingPart`/`ThinkingPartDelta` → `StreamDelta("thinking", ...)`. After iteration, `AgentRun.result` supplies `output` + `all_messages` + `new_messages` for `RunResult`. Chosen over `event_stream_handler` + queue to avoid async-bridge complexity.
3. **Executor thinking-in-artifacts** (Phase B) — branch on `delta.kind` and send thinking deltas as artifact chunks with `metadata.type = "thinking"`. Remove the post-hoc status-update loop at `executor.py:134-140`.
4. **Client `thinking_delta` event** (Phase C) — `StreamEvent.kind` gains `"thinking_delta"`; `stream_agent` accumulates thinking client-side and injects into terminal `AgentResult.thinking`.
5. **Shared `render_stream`** (Phase D) — new `cli/interaction/streaming.py`. Rich `Live` widget with initial `Status("Processing…")` spinner, replaced by `Group(thinking_panel?, answer_markdown)` once deltas arrive. Thinking panel only in the Group when `show_thinking=True`; otherwise thinking is silently dropped. Returns final `AgentResult` with thinking buffer applied.
6. **Wire into talk + do + display cleanup** (Phase E) — both modes use `render_stream`. Delete `streamed`/`skip_text`/`was_streamed` flags. `handle_post_response` narrows to auth/error/approval. `render_response` and `render_thinking` wrap with `Markdown(...)` inside their panels.
7. **Branches deleted.** `stream_fn is not None` in chat; `was_streamed` in chat; `streamed`/`skip_text` in response/display; `mode == "talk"` markdown branch in display; post-hoc thinking status-update loop in executor.

**Branches kept (necessary).** `auth_required`/`error`/`success` in `handle_post_response`; `card_meta.requires_approval` for approval widget; `kind == "text"` vs `"thinking"` in `render_stream`; `show_thinking` toggle.

**Phase A accomplished (2026-04-23).**

- `StreamDelta` dataclass added to `backend.py` with `kind`/`content` fields.
- `StreamHandle.__aiter__` protocol updated to `AsyncIterator[StreamDelta]`.
- `_PydanticAIStreamHandle` rewritten to use `agent.iter()` + per-node `.stream(ctx)`. Event-to-delta mapping in a pure `_event_to_delta` helper, easily testable.
- Executor gets a minimal shim (`if delta.kind != "text": continue; text += delta.content`) to keep pre-existing integration tests green. Phase B will do the proper thinking-through-artifacts routing.
- Executor tests' `_FakeStreamHandle` updated to use `StreamDelta`; `_as_text_deltas` helper lifts plain strings for existing test call sites.
- Added `StreamDelta` tests + event-handling tests (text-only deltas, thinking-and-text interleaved, `result()` before iteration raises).
- Full CI green: 496 tests passing, lint/typecheck/fmt clean.

**Phase B accomplished (2026-04-23).**

- Executor routes thinking deltas through `add_artifact` with `metadata.type = "thinking"` via `Struct`.
- Deleted the post-hoc status-update loop that sent `new_message_parts` as WORKING status updates.
- Updated docstring to reflect new step numbering (thinking now in artifacts, not messages).
- Added `TestExecutorThinkingViaArtifacts` test class: thinking delta produces artifact with metadata, text delta has no thinking metadata, no post-hoc WORKING-with-message status updates.
- Updated `test_sends_new_message_parts` → `test_no_working_status_updates_for_message_parts`.
- Full CI green: 499 tests passing.

**Phase C accomplished (2026-04-23).**

- `StreamEvent.kind` now includes `"thinking_delta"` alongside `"text_delta"`, `"completed"`, `"failed"`, `"auth_required"`.
- `stream_agent()` checks `_is_thinking(part)` on artifact parts and yields `thinking_delta` events for thinking, `text_delta` for text.
- Accumulates thinking client-side and injects into terminal `AgentResult.thinking` when the result doesn't already have thinking.
- `_extract_from_artifacts` now skips thinking parts (so they don't pollute output).
- `_extract_thinking` now checks both artifacts and history (artifacts first).
- Added tests: `TestStreamEventThinkingDelta`, `TestExtractFromArtifactsSkipsThinking`, `TestExtractThinkingFromArtifacts`.
- Full CI green: 505 tests passing.

**Phase D accomplished (2026-04-23).**

- New `cli/interaction/streaming.py` with `render_stream()` function.
- Uses Rich `Live` with initial `Status("Processing…")` spinner while waiting for first delta.
- Transitions to `Group(thinking_panel?, answer_markdown)` once deltas arrive.
- Thinking panel only rendered when `show_thinking=True`; otherwise thinking silently accumulated into result.
- Returns terminal `AgentResult` with accumulated thinking applied.
- New `tests/test_cli/interaction/test_streaming.py`: text-only, thinking accumulation, failed/auth events, interleaved thinking+text.
- Updated `cli/interaction/__init__.py` to export `render_stream`.
- Full CI green: 514 tests passing.

**Phase E accomplished (2026-04-23).**

- `display.py::render_response` now uses `Panel(Markdown(text), ...)` instead of `Panel(text, ...)`.
- `display.py::render_thinking` now uses `Markdown(block)` inside Panel instead of `Text(block, style="dim italic")`.
- `display.py::render_agent_output` simplified: removed `mode` and `skip_text` params. No more `mode == "talk"` markdown branch or `skip_text` double-render guard.
- `response.py::handle_post_response` narrowed to auth/error/approval only. Removed `show_thinking` and `streamed` params. Removed `render_agent_output` call and `console.print()` spacer.
- `chat.py::run_chat_loop` now takes `stream_fn` as first arg (was `send_message_fn`). Always streams via `render_stream`. Deleted `_stream_and_render` helper, `was_streamed` tracking, and `send_message_fn` fallback.
- `main.py::_do_command` now uses `render_stream(client.stream_agent(...), show_thinking=args.show_thinking)` instead of `client.run_agent(...)`.
- `main.py::_talk_command` passes `client.stream_agent` as `stream_fn` to `run_chat_loop`.
- Updated all test files for the API changes.
- Full CI green: 510 tests passing, lint/typecheck/fmt clean.

**Branches deleted (per design).**
- `stream_fn is not None` / `was_streamed` in `chat.py`
- `streamed`/`skip_text` in `response.py` and `display.py`
- `mode == "talk"` markdown branch in `display.py::render_agent_output`
- Post-hoc `new_message_parts` status-update loop in `executor.py`
- `send_message_fn` fallback in `chat.py::run_chat_loop`

**Branches kept (per design).**
- `auth_required`/`error`/`success` in `handle_post_response`
- `card_meta.requires_approval` for approval widget
- `kind == "text"` vs `"thinking"` in `render_stream`
- `show_thinking` toggle

---

### Unified Executor & Agent Platform Sketch (2026-04-24) — Design Sketch

**Status: Design sketch (revised). Do not implement without a review pass.**

This sketch replaces the previous "Executor Loop Rework (2026-04-22)" entry. It unifies five structural gaps into one coherent abstraction:

1. Executor loop (multi-step turns)
2. Tool calling (core capability)
3. ContextProviders — dual path: user-driven (`@`/flags) + model-driven (tool calls)
4. HITL approval gates (platform-level, backend-agnostic)
5. Observability / tracing (OpenTelemetry spans aligned with step boundaries)

**Guiding principle: the platform owns the abstractions, backends adapt them.**

fin-assist is a **pluggable agentic experimentation platform**. It exposes shared agentic capabilities (tools, approval, context, tracing) in a framework-agnostic way, and different LLM frameworks or providers plug in via backend implementations. This mirrors how the project already uses open protocols (A2A for transport, OTel for observability) — the platform defines the shape, backends fill in the framework-specific details.

This principle drives every design decision below: tools, approval, and step events are platform concepts, not pydantic-ai concepts. PydanticAIBackend implements them for pydantic-ai; a future LangChainBackend or AnthropicBackend would implement them for its framework.

**Key insight: the executor loop is the spine, and everything else hangs off its step boundaries.** Tools are the reason the loop iterates. Approval gates hook into tool execution. Tracing spans align with steps. This is better than designing each gap in isolation because they share the same shape — they're all "things that happen between LLM calls."

---

#### Research Summary

**LangGraph** — `interrupt()` + `Command(resume=...)` pattern. Execution genuinely pauses at a graph node, state is check pointed, caller resumes with a value. No custom state management. The graph IS the loop; nodes are steps. HITL is native, not retrofitted. Our takeaway: the step boundary is the right abstraction for gates, and resume semantics (not polling) are the right model.

**pydantic-ai** — Has native tool calling via `@agent.tool` / `@agent.tool_plain`. `agent.iter()` walks the graph node-by-node (ModelRequestNode → CallToolsNode → …). **Deferred Tools** (`requires_approval=True` / `ApprovalRequired` exception / `CallDeferred` exception) end the run with `DeferredToolRequests`, then you resume with `DeferredToolResults`. This is pydantic-ai's HITL story — useful as a backend implementation, but not our platform abstraction. **Hooks** (`Hooks` capability) intercept at every lifecycle point: `before_model_request`, `before_tool_execute`, `after_tool_execute`, etc. — perfect for tracing. **OpenTelemetry** is built-in: `Agent.instrument_all()` emits spans for each model request and tool call; compatible with any OTel backend (Logfire, Phoenix, Jaeger, etc.).

**Arize Phoenix** — Python-native, self-hosted, OpenTelemetry-compatible. Uses `OpenInference` semantic conventions (extends OTLP). `auto_instrument=True` captures traces. Sessions track multi-turn conversations. Free and open-source; fits local-first philosophy.

**Claude Code** — Tool-approval prompts per tool type. `--dangerously-skip-permissions` for CI. Hooks run before/after actions. Not protocol-native — approval is client-side, not A2A-integrated.

**Pattern that emerges across all frameworks:**

| Concept | LangGraph | pydantic-ai | fin-assist (platform) |
|---------|-----------|-------------|----------------------|
| Step boundary | Graph node | `agent.iter()` node | **Platform `StepEvent`** (backend adapts) |
| Tool calling | Native | Native (`@agent.tool`) | **Platform `ToolRegistry`** (backend registers) |
| HITL | `interrupt()` + resume | Deferred Tools | **Platform `ApprovalPolicy`** (backend may optimize) |
| Tracing | OTel spans per node | `Hooks` + OTel | **OTel spans at step boundaries** (backend may add detail) |
| Loop strategy | Graph topology | Agent graph (built-in) | Executor drives loop via StepEvents |

---

#### Architecture: Platform Layer / Backend Layer

```text
┌─────────────────────────────────────────────────────────────────┐
│  Platform Layer (fin-assist owns these — framework-agnostic)    │
│                                                                 │
│  ToolRegistry     — tool definitions: name, schema, callable,   │
│                     approval_policy. Shared across agents.      │
│  ApprovalPolicy   — what needs approval, how. Evaluated by      │
│                     the Executor at step boundaries.             │
│  ContextProviders — existing (files, git, history, env).        │
│                     Serve both user-driven and model-driven.    │
│  StepEvent        — universal step boundary events. Any backend  │
│                     emits the same event types.                 │
│  OTel spans       — at Executor step boundaries. Backend may    │
│                     add framework-specific child spans.          │
└──────────────────────────┬──────────────────────────────────────┘
                           │  Backend adapts platform concepts
                           │  to its framework
┌──────────────────────────┴──────────────────────────────────────┐
│  Backend Layer (framework-specific)                              │
│                                                                 │
│  PydanticAIBackend:                                             │
│    - Registers tools from ToolRegistry as @agent.tool /         │
│      @agent.tool_plain (or via toolsets)                        │
│    - Implements ApprovalPolicy via pydantic-ai's                 │
│      requires_approval / ApprovalRequired (optimization —       │
│      lets pydantic-ai handle deferral natively when possible)   │
│    - Wraps ContextProviders as tool functions for model-driven   │
│      context; user-driven context injected via user message      │
│    - Emits StepEvents from agent.iter() nodes                    │
│    - Adds pydantic-ai Hooks for detailed OTel child spans       │
│                                                                 │
│  FutureBackend (LangChain, raw Anthropic, etc.):                │
│    - Same ToolRegistry, different registration mechanism         │
│    - Same ApprovalPolicy, different enforcement mechanism        │
│    - Same StepEvents, different event source                     │
│    - Same OTel spans, different child span detail               │
└─────────────────────────────────────────────────────────────────┘
```

The key boundary: **platform types never import from backends.** `StepEvent`, `ToolRegistry`, and `ApprovalPolicy` live in `agents/` alongside `AgentSpec`. They have zero pydantic-ai imports. The backend implements them, but the platform doesn't depend on the implementation.

---

#### Architecture: The Step-Driven Executor

**Current state (single-pass):**

```text
load_history → convert_messages → run_stream → drain_deltas → save_history → complete
```

**Proposed state (step-driven loop):**

```text
load_history → convert_messages → [STEP LOOP] → save_history → complete

STEP LOOP:
  1. Run backend (one model call) → get response
  2. Emit streaming deltas (text/thinking) as artifacts
  3. If response contains tool calls:
     a. For each tool call:
        i.   Emit tool_call StepEvent (artifact with metadata)
        ii.  Evaluate ApprovalPolicy → if deferred, pause task
        iii. Execute tool → emit tool_result StepEvent
     b. Feed tool results back to backend → go to 1
  4. If response is final (no tool calls) → exit loop
```

The Executor drives the loop. The backend produces `StepEvent`s. The Executor dispatches based on event kind — the loop logic lives in the Executor, not the backend.

---

#### Component Changes

**1. `StreamHandle` → `StepHandle` (platform-level)**

The current `StreamHandle` yields `StreamDelta` values and returns one `RunResult`. This collapses the entire agent graph into one stream. Instead, we need a handle that yields **step events**, not just text deltas:

```python
@dataclass
class StepEvent:
    """Platform-level event emitted during one step of the agent loop.

    Any backend must emit these same event types. The content field
    carries framework-specific payloads (e.g., pydantic-ai ToolCallPart)
    but the Executor treats them opaquely — it only dispatches on kind.
    """
    kind: Literal[
        "text_delta",       # incremental text
        "thinking_delta",   # incremental thinking
        "tool_call",        # model requests a tool
        "tool_result",      # tool execution result
        "step_start",       # beginning of a new model request
        "step_end",         # model response complete for this step
        "deferred",         # run paused for approval / external execution
    ]
    content: Any           # framework-specific payload
    step: int              # which step in the loop (0-indexed)
    tool_name: str | None  # set for tool_call / tool_result / deferred events
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class StepHandle(Protocol):
    def __aiter__(self) -> AsyncIterator[StepEvent]: ...
    async def result(self) -> RunResult: ...
```

This replaces `StreamHandle`. The Executor iterates `StepHandle` and dispatches based on `kind`. The `content` field is opaque at the platform level — only the backend knows the framework-specific type.

**2. `AgentBackend` contract update**

```python
@runtime_checkable
class AgentBackend(Protocol):
    def check_credentials(self) -> list[str]: ...
    def convert_history(self, a2a_messages: Sequence[Any]) -> list[Any]: ...
    def run_steps(self, *, messages: list[Any], model: Any = None) -> StepHandle: ...
    def serialize_history(self, messages: list[Any]) -> bytes: ...
    def deserialize_history(self, data: bytes) -> list[Any]: ...
    def convert_result_to_part(self, result: Any) -> Part: ...
    def convert_response_parts(self, parts: Sequence[Any]) -> list[Part]: ...
    def register_tools(self, registry: ToolRegistry) -> None: ...
    def set_approval_policy(self, policy: ApprovalPolicy) -> None: ...
```

Changes from current:
- `run_stream()` → `run_steps()`: returns `StepHandle` instead of `StreamHandle`
- New `register_tools()`: backend registers platform tools onto its framework (pydantic-ai: `@agent.tool`; future: different mechanism)
- New `set_approval_policy()`: backend adapts platform approval policy to its framework (pydantic-ai: maps to `requires_approval` / `ApprovalRequired`; future: different mechanism)
- Removed `execute_tool()` from the protocol — tool execution is framework-internal. The Executor gates execution via the `tool_call` event + `ApprovalPolicy` check, but the backend owns *how* the tool runs.

**3. `ToolRegistry` (platform-level, in `agents/`)**

Framework-agnostic tool registry. Maps tool names to definitions:

```python
@dataclass
class ToolDefinition:
    """A platform-level tool definition. Framework-agnostic."""
    name: str
    description: str
    callable: Callable[..., Awaitable[str] | str]
    parameters_schema: dict[str, Any]   # JSON Schema for parameters
    approval_policy: ApprovalPolicy | None  # None = no gate required


class ToolRegistry:
    """Global registry of tool definitions. Shared across all agents."""

    def register(self, definition: ToolDefinition) -> None: ...
    def get(self, name: str) -> ToolDefinition | None: ...
    def list_tools(self) -> list[ToolDefinition]: ...
```

Tools are **shareable between agents** — agents opt-in via config (`tools = ["read_file", "git_diff"]`). The registry is global; each agent's `AgentSpec` references tool names, and the backend registers only the tools the agent needs.

**MCP integration** (#84): A future `MCPToolset` would wrap an MCP client and register discovered tools into the `ToolRegistry` with appropriate schemas and approval policies. The platform abstraction doesn't need to know about MCP — it's just another tool source.

**4. `ApprovalPolicy` (platform-level, in `agents/`)**

Framework-agnostic approval specification. The Executor evaluates it at the `tool_call` step boundary:

```python
@dataclass
class ApprovalPolicy:
    """Declares what approval a tool call requires.

    The Executor checks this before allowing tool execution.
    If a gate fails, the task pauses (A2A input-required state).
    The backend may use this to optimize (e.g., pydantic-ai
    Deferred Tools natively support deferral), but the Executor's
    check is the canonical gate.
    """
    mode: Literal["never", "always", "conditional"]
    # For "conditional" mode: a callable that returns True if approval is needed
    condition: Callable[[str, dict[str, Any]], bool] | None = None
    reason: str | None = None  # human-readable reason shown in approval UI
```

The Executor's approval flow:
1. On `tool_call` event, look up the tool's `ApprovalPolicy` from `ToolRegistry`
2. If `mode == "never"` → proceed to execution
3. If `mode == "always"` → pause task, emit deferred event
4. If `mode == "conditional"` → evaluate `condition(tool_name, args)` → pause or proceed
5. When paused, set A2A task to `TASK_STATE_INPUT_REQUIRED`, include tool call details in artifact metadata
6. Client shows approval UI, sends decision back via `SendMessage` with same `context_id`
7. Executor resumes: if approved, backend executes tool; if denied, model gets denial message

**Backend optimization:** If the backend natively supports approval (pydantic-ai's `DeferredToolRequests`), it can handle the deferral internally and emit a `deferred` StepEvent. If the backend doesn't support it natively, the Executor's gate is the enforcement point. Either way, the platform `ApprovalPolicy` is the source of truth.

**5. Context: dual path (user-driven + model-driven)**

Context is accessible via two complementary paths:

**User-driven** (the user knows what the model needs):
- `@file:path.py` in talk mode → `FinPrompt` calls `ContextProvider.search()`, injects result into user message
- `--file path.py` / `--git-diff` / `--git-log` on `do` → injects `ContextItem` content into user message
- Pre-injection: context is in the prompt before the model sees it

**Model-driven** (the model discovers what it needs):
- `read_file`, `git_diff`, `git_log`, `shell_history` registered as tools in `ToolRegistry`
- The model calls them on demand during the step loop
- On-demand: context is fetched at tool-call time, always fresh

Both paths use the **same `ContextProvider` classes**. For user-driven, the CLI calls the provider and injects the result. For model-driven, the tool callable wraps the provider:

```python
# Platform-level tool definition wrapping a ContextProvider:
async def read_file(path: str) -> str:
    """Read a file and return its contents."""
    items = FileFinder(max_file_size=...).search(path)
    return items[0].content if items else f"File not found: {path}"

registry.register(ToolDefinition(
    name="read_file",
    description="Read a file and return its contents.",
    callable=read_file,
    parameters_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    approval_policy=None,  # read-only, no gate
))
```

The user-driven path was the original design (Steps 7-8 in config redesign). It stays. The model-driven path is new and additive — it doesn't replace user-driven context, it supplements it.

**6. `_PydanticAIStepHandle` (replaces `_PydanticAIStreamHandle`)**

Uses `agent.iter()` to walk the graph node-by-node. Currently we only stream from `ModelRequestNode` and skip everything else. The new handle emits platform `StepEvent`s for every node type:

- `ModelRequestNode` → `step_start`, then stream `text_delta`/`thinking_delta`, then `step_end`
- `CallToolsNode` → for each `ToolCallPart`, emit `tool_call`; for each `ToolReturnPart`, emit `tool_result`
- If `ApprovalRequired` / `CallDeferred` is raised → emit `deferred`

**7. Executor rework (event-driven with approval verification)**

```python
class Executor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # ... setup, credential check, load history (unchanged) ...

        expecting_deferral: str | None = None  # tool name if approval required

        handle = self._backend.run_steps(messages=message_history)
        async for event in handle:
            match event.kind:
                case "text_delta" | "thinking_delta":
                    await self._emit_delta(event, updater, artifact_id)
                case "tool_call":
                    policy = self._tool_registry.get(event.tool_name).approval_policy
                    if policy and policy.mode != "never":
                        expecting_deferral = event.tool_name
                    await self._emit_tool_call(event, updater)
                case "tool_result":
                    if expecting_deferral == event.tool_name:
                        # Backend bug: tool executed without required approval
                        logger.warning("Tool %s executed without required approval", event.tool_name)
                    expecting_deferral = None
                    await self._emit_tool_result(event, updater)
                case "step_start":
                    self._start_step_span(event)
                case "step_end":
                    self._end_step_span(event)
                case "deferred":
                    expecting_deferral = None
                    await self._handle_deferred(event, updater)
                    return  # task pauses; client will resume

        result = await handle.result()
        # ... save history, emit structured output, complete (unchanged) ...
```

The backend is the primary enforcer of `ApprovalPolicy`. When a tool needs approval, the backend emits `tool_call` followed by `deferred` (not `tool_result`). The Executor verifies this: if a `tool_result` arrives for a tool that should have been deferred, it logs a warning. This is **defense in depth** — the platform catches backend bugs without being the primary gate.

**8. Observability: OTel at platform step boundaries**

The Executor wraps each step in an OTel span (`fin_assist.executor.step`). This is platform-level — any backend produces the same span structure. The backend may add framework-specific child spans (pydantic-ai: `Agent.instrument_all()` + `Hooks`; future backends: their own instrumentation).

Configuration in `config.toml`:

```toml
[observability]
backend = "phoenix"   # "phoenix", "logfire", "otlp", or "none"
endpoint = "http://127.0.0.1:6006"  # Phoenix default
auto_instrument = true
```

**9. ContextStore format versioning**

Before the loop rework lands, add a version byte prefix to stored history:

```python
_CONTEXT_STORE_VERSION = 1  # increment when format changes

def serialize_history(self, messages: list[Any]) -> bytes:
    payload = _message_ta.dump_json(messages)
    return struct.pack("!B", _CONTEXT_STORE_VERSION) + payload

def deserialize_history(self, data: bytes) -> list[Any]:
    version = struct.unpack("!B", data[:1])[0]
    if version != _CONTEXT_STORE_VERSION:
        raise ValueError(f"Unsupported context store version {version}")
    return _message_ta.validate_json(data[1:])
```

Existing stores without a version prefix need a migration path (try deserializing without prefix on version mismatch, then re-save with prefix).

---

#### Implementation Phases

**Phase A: Foundation (must land first)**
1. Add `ContextStore` version byte (tiny, low-risk)
2. Add `StepEvent` dataclass to `agents/` (platform-level, not backend.py)
3. Add `StepHandle` protocol to `agents/`
4. Implement `_PydanticAIStepHandle` in `backend.py` (replaces `_PydanticAIStreamHandle`)
5. Update `AgentBackend` protocol: `run_stream()` → `run_steps()`, add `register_tools()` + `set_approval_policy()`
6. Update `Executor` to iterate `StepHandle` and dispatch on `StepEvent.kind`
7. Update all tests

**Phase B: Tool Calling (depends on Phase A)**
1. Create `ToolRegistry` + `ToolDefinition` in `agents/` (platform-level)
2. Add `tools` field to `AgentConfig` + `AgentSpec`
3. Wire `PydanticAIBackend.register_tools()` to register platform tools as pydantic-ai tools
4. Implement context-as-tools: `read_file`, `git_diff`, `git_log`, `shell_history` in ToolRegistry
5. Wire CLI `--file` / `--git-diff` flags as user-driven context injection (existing design)
6. Update `AgentCardMeta` with `supported_context_types` (architecture doc already plans this)
7. End-to-end test: default agent reads a file via tool call

**Phase C: HITL / Approval (depends on Phase B)**
1. Create `ApprovalPolicy` in `agents/` (platform-level)
2. Wire `PydanticAIBackend.set_approval_policy()` to map platform policy to pydantic-ai Deferred Tools
3. Implement `deferred` event handling in Executor → A2A task pause (`TASK_STATE_INPUT_REQUIRED`)
4. Implement client-side approval flow (resume with `SendMessage` on same `context_id`)
5. Test: shell agent proposes command → approval widget → approve/deny
6. Generalize: any tool can declare `ApprovalPolicy` via config or registration

**Phase D: Observability (can proceed in parallel with B/C)**
1. Add `[observability]` config section
2. Wire Arize Phoenix (or generic OTLP) in `hub/app.py` startup
3. Add Executor-level step spans (platform-level, any backend)
4. Enable `Agent.instrument_all()` for pydantic-ai-specific child spans
5. Verify traces appear in Phoenix UI

---

#### Open Issues Addressed

| Issue | How this sketch addresses it |
|-------|----------------------------|
| [#79](https://github.com/ColeB1722/fin-assist/issues/79) (commit agent) | Directly enabled: `git_diff` tool + `CommandResult` output + approval. Great first vertical slice for Phase B+C. |
| [#80](https://github.com/ColeB1722/fin-assist/issues/80) (backend protocol) | Protocol reworked: tools, approval, and step events move to platform layer, simplifying the backend contract. The backend now adapts platform concepts instead of exposing pydantic-ai shapes. |
| [#84](https://github.com/ColeB1722/fin-assist/issues/84) (MCP toolset) | Natural enhancement: MCPToolset registers into ToolRegistry. ToolRegistry interface designed so MCP is a natural plugin. |
| [#65](https://github.com/ColeB1722/fin-assist/issues/65) (private pydantic-ai access) | Resolves organically as we push framework coupling into the backend. Platform types have zero pydantic-ai imports. |
| [#63](https://github.com/ColeB1722/fin-assist/issues/63) (workflow chaining) | Enabled by step boundaries — the loop is the foundation for per-step handoffs between agents. |

---

#### Open Questions

1. ~~**StepHandle vs. two-pass.**~~ **RESOLVED: Event-driven (Option A) with Executor verification.**

   Two approaches were evaluated:

   **Option A: Event-driven (chosen)** — Single `run_steps()` call, backend walks the full agent graph, emits `StepEvent`s continuously. The Executor iterates and dispatches. Approval: backend enforces `ApprovalPolicy` (emits `deferred` for gated tools). Executor verifies compliance (defense in depth).

   **Option B: Two-pass (rejected)** — Multiple `run_steps()` calls, one per model response. Executor feeds tool results between calls. Approval: Executor owns the gate entirely.

   | Dimension | Event-driven (A) | Two-pass (B) |
   |-----------|-------------------|--------------|
   | Streaming | Seamless within and across tool calls | Round-trip gaps between steps |
   | Approval ownership | Backend enforces, Executor verifies | Executor enforces exclusively |
   | Backend contract | Richer — full graph walk, event emission, approval deferral | Simpler — one model request per call |
   | pydantic-ai alignment | Natural — `agent.iter()` does this | Unnatural — must stop/resume manually, fights the framework |
   | Non-pydantic-ai backends | More work per backend (must implement graph walk) | Less work per backend |
   | Latency between tool call and tool result | Zero (inline execution) | One round-trip per tool call |
   | Error recovery | Backend handles within graph walk | Executor has more control |

   **Why A:** Fighting pydantic-ai is the worse outcome (coupling, private imports, #68/#80 repeat risk). Latency matters — agents that call 5-10 tools per turn would have 5-10 unnecessary round-trips under B. Streaming is non-negotiable for UX. The approval guarantee is strengthened by the Executor's verification layer (logs warning if `tool_result` arrives for a tool that should have been deferred).

   **Contract for backends:** `set_approval_policy(policy)` — backend MUST check the policy before executing any tool. If a tool needs approval, emit `deferred` instead of executing. The Executor verifies compliance.

2. **~~A2A task pause for deferred tools.~~ RESOLVED: Use `TASK_STATE_INPUT_REQUIRED` (value 6) via `updater.requires_input()`. Protocol-native, any A2A client handles it. `TASK_STATE_AUTH_REQUIRED` (value 8) stays for credential-gated tasks — semantically distinct (can't proceed at all vs. need decision to proceed).**

3. **~~Deferred tool resume protocol.~~ RESOLVED: `SendMessage` with same `context_id`, detected via `Part` with `metadata.type = "approval_result"`. Protocol-native, stays within A2A multi-turn semantics. Executor detects resume by checking last messages for `DeferredToolRequests` markers AND incoming message containing `approval_result` part. Reconstructs `DeferredToolResults` and re-invokes backend with `message_history + deferred_tool_results`.**

4. **~~StepHandle `deferred` event semantics.~~ RESOLVED: Iteration ends on `deferred`. Run is over; resume is a new `run_steps()` call. pydantic-ai ends the run with `DeferredToolRequests` as output — the `async with agent.iter()` context closes. Fighting this would require intercepting inside the graph walk, which is exactly the coupling we've been extracting. All backends follow the same pattern: `deferred` ends the iteration, resume = new `run_steps(messages, deferred_tool_results=...)`.**

5. ~~**Tool dependencies injection.**~~ **RESOLVED in Phase B: No `ToolDeps` needed yet. Built-in tools construct their own provider instances. When config-dependent tools are needed, a `ToolDeps` dataclass can be added then.**

6. ~~**ToolRegistry scoping.**~~ **RESOLVED in Phase B: Global registry with `get_for_agent()` filtering. One `read_file` definition shared by all agents; agents opt in via config `tools = [...]`.**

7. **`ApprovalPolicy(mode="conditional")` enforcement.** The type exists but no runtime path invokes the `condition` callable or branches on `mode="conditional"`. Currently, `_build_pydantic_agent` maps `mode != "never"` → `requires_approval=True` (binary). pydantic-ai's `requires_approval` is a `bool`, not a callable. Three implementation options:

   - **A. Always defer, client-side auto-approve** — Set `requires_approval=True`; the approval widget checks the condition and auto-approves if it returns `False`. Reuses the full deferred flow but adds latency for auto-approved calls.
   - **B. Wrap the tool callable** — Replace the callable with a wrapper that checks the condition first, raising to trigger deferred flow when needed. Cleaner but requires deeper pydantic-ai tool lifecycle integration.
   - **C. Wait for upstream** — If pydantic-ai makes `requires_approval` accept `bool | Callable`, this becomes trivial. May never happen.

   **Recommendation**: Design sketch in `handoff.md` before implementation. Option A is the simplest with current architecture. If `conditional` is never needed, the dead code (`condition` field, `conditional` mode variant) should be removed rather than maintained.

---

#### Scope Explicitly Excluded

- **LoopStrategy pluggability.** For now, the Executor IS the loop. If we later need different loop behaviors (plan-execute, self-critique), we can extract a strategy then. Premature abstraction.
- **Multi-agent orchestration.** One agent calling another agent as a tool. Interesting but out of scope — this is a future A2A-level feature (#63), not an Executor feature.
- **Sandboxing / tool isolation.** Tool functions run in the hub process. Sandboxing (containers, Nix shells) is a future concern for the QA/testing agent.
- **Tool result streaming.** Tool results are currently atomic (one `tool_result` event). Streaming tool results (e.g., a long-running bash command) is a future enhancement.

---

#### Supersedes

This sketch supersedes the following previous entries:
- "Executor Loop Rework (2026-04-22)" — the loop design is now specified here, with platform/backend separation
- "HITL Approval Model (2026-04-22)" — HITL is now a platform-level `ApprovalPolicy`, not backend-specific
- "ContextProviders Integration (Steps 7-8, parked)" — context has a dual path: user-driven (existing design) + model-driven (tool calls)

---

### Phase C: HITL / Approval — Design Sketch (2026-04-24)

**Status: Design sketch, implementation starting.**

#### Core Principle

**In-flight, server-side deferral replaces post-response, client-side approval.** The current `requires_approval: bool` is a client-side gate that runs *after* the model finishes. The new system pauses the model *mid-run* when it calls a tool that needs consent. This is more powerful and more correct — the model can't produce output from a tool that wasn't approved.

#### What Gets Removed

| Remove | Why |
|--------|-----|
| `AgentConfig.requires_approval` | Replaced by `ApprovalPolicy` on `ToolDefinition` |
| `AgentCardMeta.requires_approval` | Derived: agent has tools with `mode != "never"` |
| `handle_post_response()` approval branch | In-flight deferred flow via `INPUT_REQUIRED` replaces it |
| `execute_command()` in `approve.py` | Tool execution happens server-side after approval |
| `ApprovalAction` enum | Replaced by `ApprovalDecision` type for deferred results |
| `PostResponseAction.EXECUTED` / `.CANCELLED` | No longer needed — approval is in-flight |

#### What Gets Added

| Add | Where | Purpose |
|-----|-------|---------|
| `ApprovalPolicy` dataclass | `agents/tools.py` | Platform-level approval spec on `ToolDefinition` |
| `DeferredToolCall` dataclass | `agents/tools.py` | Serializable deferred tool call info (name, args, call_id, reason) |
| `ApprovalDecision` dataclass | `agents/tools.py` | Client decision: approved/denied + optional override_args |
| `deferred` StepEvent handling | `hub/executor.py` | Pause task on `deferred`, resume on `approval_result` |
| `run_shell` tool with `ApprovalPolicy(mode="always")` | `agents/tools.py` | Shell command execution tool (replaces client-side `execute_command`) |
| `approval_result` Part metadata convention | `hub/executor.py` | How the client sends approval decisions back |
| `DeferredToolResults` passthrough | `agents/backend.py` | `run_steps()` accepts `deferred_tool_results` for resume |
| Approval widget in streaming | `cli/interaction/` | Render deferred tool calls, collect approve/deny, resume |

#### ApprovalPolicy (Platform Type)

```python
@dataclass
class ApprovalPolicy:
    """Platform-level approval specification. Framework-agnostic.
    
    Lives on ToolDefinition. The backend enforces it (emits 'deferred'
    for gated tools). The Executor verifies compliance (defense in depth).
    """
    mode: Literal["never", "always", "conditional"]
    condition: Callable[[str, dict[str, Any]], bool] | None = None
    reason: str | None = None
```

- `mode="never"`: Tool is safe, no gate required. All current built-in tools.
- `mode="always"`: Every call needs approval. The `run_shell` tool.
- `mode="conditional"`: The `condition(tool_name, args)` callable decides. E.g., `run_shell` with a condition that auto-approves read-only commands.

`ToolDefinition.approval_policy` field (currently `Any | None`, reserved) becomes `ApprovalPolicy | None` where `None` means `mode="never"`.

#### DeferredToolCall (Platform Type)

```python
@dataclass
class DeferredToolCall:
    """A tool call that was deferred pending human approval.
    
    Carried in the 'deferred' StepEvent's content and in the
    deferred artifact metadata. Serializable for A2A transport.
    """
    tool_name: str
    tool_call_id: str
    args: dict[str, Any]
    reason: str | None = None
```

#### ApprovalDecision (Platform Type)

```python
@dataclass
class ApprovalDecision:
    """Client's decision on a deferred tool call.
    
    Sent back via 'approval_result' Part metadata when resuming.
    """
    tool_call_id: str
    approved: bool
    override_args: dict[str, Any] | None = None
    denial_reason: str | None = None
```

#### Backend Changes

**`AgentBackend` protocol** gains `deferred_tool_results` parameter:

```python
class AgentBackend(Protocol):
    def run_steps(
        self,
        *,
        messages: list[Any],
        model: Any = None,
        deferred_tool_results: Any = None,  # framework-specific
    ) -> StepHandle: ...
```

**`PydanticAIBackend`** changes:

1. `_build_pydantic_agent()` adds `DeferredToolRequests` to `output_type`:
   ```python
   output_type=[self._spec.output_type, DeferredToolRequests]
   ```
2. `_build_pydantic_agent()` registers tools with approval:
   - Tools with `ApprovalPolicy(mode="always")` → `requires_approval=True` on the pydantic-ai `Tool`
   - Tools with `ApprovalPolicy(mode="conditional")` → `approval_required()` toolset wrapper
   - Tools with `ApprovalPolicy(mode="never")` or `None` → no change
3. `run_steps()` passes `deferred_tool_results` through to `agent.iter()` / `agent.run()`
4. `_PydanticAIStepHandle` detects `DeferredToolRequests` in result and emits `deferred` StepEvent

**`_PydanticAIStepHandle` deferred detection:**

```python
async def __aiter__(self) -> AsyncIterator[StepEvent]:
    # ... existing iteration for ModelRequestNode, CallToolsNode ...
    
    final = run.result
    if isinstance(final.output, DeferredToolRequests):
        # Emit deferred events for each approval request
        for call in final.output.approvals:
            yield StepEvent(
                kind="deferred",
                content=DeferredToolCall(
                    tool_name=call.tool_name,
                    tool_call_id=call.tool_call_id,
                    args=call.args_as_dict(),
                    reason=self._get_approval_reason(call.tool_name),
                ),
                step=step,
                tool_name=call.tool_name,
            )
        self._result = RunResult(
            output=final.output,
            serialized_history=self._backend.serialize_history(final.all_messages()),
        )
        return  # iteration ends
```

#### Executor Changes

**Deferred event handling:**

```python
case "deferred":
    # Emit deferred tool call as artifact
    deferred_meta = Struct()
    deferred_meta.update({
        "type": "deferred",
        "tool_name": event.tool_name or "",
        "tool_call_id": event.content.tool_call_id,
        "reason": event.content.reason or "",
        "args": event.content.args,
    })
    await updater.add_artifact(
        parts=[Part(text=str(event.content.args), metadata=deferred_meta)],
        artifact_id=artifact_id,
        name="result",
        append=True,
        last_chunk=False,
    )
    # Don't complete the task — pause for input
    # (we'll call requires_input after the loop)
    has_deferred = True
```

After the iteration loop:

```python
if has_deferred:
    # Save history so resume can pick up where we left off
    if raw_context_id:
        await self._context_store.save(raw_context_id, result.serialized_history)
    deferred_msg = updater.new_agent_message(parts=[...])
    await updater.requires_input(message=deferred_msg)
    return  # task pauses — client will resume
```

**Resume detection** (at the start of `execute()`):

```python
# After loading history, check for resume
deferred_results = self._extract_approval_results(context.message)
if deferred_results is not None and serialized_history is not None:
    # This is a resume — pass deferred results to backend
    handle = self._backend.run_steps(
        messages=message_history,
        deferred_tool_results=deferred_results,
    )
else:
    # New request — append user message and run
    if context.message:
        a2a_history = [context.message]
        message_history.extend(self._backend.convert_history(a2a_history))
    handle = self._backend.run_steps(messages=message_history)
```

**`_extract_approval_results()`** reads the incoming message for `approval_result` parts:

```python
def _extract_approval_results(self, message) -> Any | None:
    """Check if an incoming A2A message contains approval decisions."""
    if not message or not message.parts:
        return None
    for part in message.parts:
        meta = _struct_to_dict(part.metadata) if part.metadata else {}
        if meta.get("type") == "approval_result":
            decisions = meta.get("decisions", [])
            return self._backend.build_deferred_results(decisions)
    return None
```

The backend's `build_deferred_results()` converts platform `ApprovalDecision` dicts into framework-specific `DeferredToolResults` (pydantic-ai) or equivalent.

#### Client Changes

**`StreamEvent` gains `input_required` kind:**

```python
class StreamEvent(BaseModel):
    kind: Literal[
        "text_delta", "thinking_delta", "completed", "failed",
        "auth_required", "input_required",
    ]
    text: str = ""
    result: AgentResult | None = None
    deferred_calls: list[dict] | None = None  # for input_required events
```

**`HubClient.stream_agent()`** handles `INPUT_REQUIRED`:

```python
# In _process_response or the streaming loop:
if state == TaskState.TASK_STATE_INPUT_REQUIRED:
    # Extract deferred tool calls from artifacts
    deferred = self._extract_deferred_calls(task)
    yield StreamEvent(kind="input_required", deferred_calls=deferred, result=result)
    break
```

**`render_stream()`** returns on `input_required` — the chat loop or do command handles the approval widget.

**New approval flow in CLI:**

```python
# In do command or chat loop, after render_stream:
if result deferred:
    decision = await run_approval_widget(deferred_calls)
    # Send resume message with approval_result Part
    resume_result = await render_stream(
        client.stream_agent(agent_name, prompt, context_id=ctx_id,
                           approval_decisions=decision),
        show_thinking=show_thinking,
    )
```

**`HubClient`** gains ability to send `approval_decisions` as `Part` metadata:

```python
async def stream_agent(
    self,
    agent_name: str,
    prompt: str,
    context_id: str | None = None,
    approval_decisions: list[ApprovalDecision] | None = None,
) -> AsyncIterator[StreamEvent]:
    parts = [Part(text=prompt)]
    if approval_decisions:
        meta = Struct()
        meta.update({
            "type": "approval_result",
            "decisions": [
                {
                    "tool_call_id": d.tool_call_id,
                    "approved": d.approved,
                    "override_args": d.override_args,
                    "denial_reason": d.denial_reason,
                }
                for d in approval_decisions
            ],
        })
        parts.append(Part(text="", metadata=meta))
    msg = Message(role=Role.ROLE_USER, message_id=str(uuid.uuid4()), parts=parts)
    if context_id:
        msg.context_id = context_id
    # ... rest of streaming logic ...
```

#### AgentCardMeta.requires_approval → Derived

`requires_approval` is removed from `AgentCardMeta`. Instead, clients check whether any of the agent's tools have `mode != "never"`:

```python
# In AgentSpec.agent_card_metadata:
# Instead of requires_approval=cfg.requires_approval
# Derive from tool registry:
requires_approval = any(
    td.approval_policy is not None and td.approval_policy.mode != "never"
    for td in (self._tool_registry.get_for_agent(self.tools) if self._tool_registry else [])
)
```

Wait — `AgentSpec` doesn't have access to `ToolRegistry` currently. The factory passes it to `PydanticAIBackend`, not to `AgentSpec`. Two options:

(a) Pass `ToolRegistry` to `AgentSpec` — makes `AgentSpec` aware of tools, which is conceptually correct (the spec declares "what tools this agent has" and the registry resolves them).

(b) Compute `requires_approval` in the factory and set it on `AgentCardMeta` before building the card.

**Choice: (a).** `AgentSpec` already has a `tools` list (tool name strings). Giving it the `ToolRegistry` lets it resolve those names and answer questions like "does this agent have any tools requiring approval?" — which is exactly what `agent_card_metadata` needs. The registry is already created before `AgentSpec` in the factory flow.

This means `AgentSpec.__init__` gains an optional `tool_registry: ToolRegistry | None = None` parameter. The factory passes it. Tests that construct `AgentSpec` without it continue to work (default `None` → no tools → `requires_approval=False`).

#### run_shell Tool

The shell agent currently produces a `CommandResult` with the command string, and the client decides whether to execute it. With `ApprovalPolicy`, the shell agent gets a `run_shell` tool:

```python
async def _run_shell(command: str) -> str:
    """Execute a shell command and return its output."""
    import subprocess
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    output = result.stdout
    if result.stderr:
        output += f"\nSTDERR: {result.stderr}"
    if result.returncode != 0:
        output += f"\nExit code: {result.returncode}"
    return output or "(no output)"

registry.register(ToolDefinition(
    name="run_shell",
    description="Execute a shell command and return its output.",
    callable=_run_shell,
    parameters_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
        },
        "required": ["command"],
    },
    approval_policy=ApprovalPolicy(mode="always", reason="Shell command execution requires approval"),
))
```

The shell agent config changes: `output_type = "text"` (not `"command"`), `tools = ["run_shell"]`. The model decides when to call `run_shell`, the tool requires approval, the Executor defers, the client shows the approval widget, and on approval the tool runs server-side.

**This is the key migration:** shell agent goes from "produce command string, client decides" to "produce text, but when the model calls `run_shell`, the platform gates it."

#### handle_post_response Simplification

With `requires_approval` removed and approval happening in-flight:

```python
async def handle_post_response(
    result: AgentResult,
    card_meta: AgentCardMeta | None = None,
    *,
    mode: str = "talk",
) -> PostResponseResult:
    if result.auth_required:
        render_auth_required(result.output)
        return PostResponseResult(action=PostResponseAction.AUTH_REQUIRED, exit_code=1)

    if not result.success:
        render_error(result.output or "Unknown error")
        return PostResponseResult(action=PostResponseAction.ERROR, exit_code=1)

    return PostResponseResult(action=PostResponseAction.CONTINUE, exit_code=0)
```

The approval branch is gone — `PostResponseAction.EXECUTED` and `.CANCELLED` are removed. The `approve.py` module's `run_approve_widget()` and `ApprovalAction` are repurposed for the in-flight approval widget (called from the streaming/chat layer when `input_required` is received).

#### Implementation Sub-Phases

**C.1: Platform types** — `ApprovalPolicy`, `DeferredToolCall`, `ApprovalDecision` in `agents/tools.py`. Remove `requires_approval` from `AgentConfig`, `AgentCardMeta`, `AgentSpec`. Update `AgentSpec` to accept `ToolRegistry` and derive `requires_approval`. Update all tests.

**C.2: Backend enforcement** — `PydanticAIBackend` registers tools with `requires_approval=True` / `approval_required()` based on `ApprovalPolicy`. Add `DeferredToolRequests` to `output_type`. `run_steps()` accepts `deferred_tool_results`. `_PydanticAIStepHandle` emits `deferred` StepEvent. Add `run_shell` tool. Update shell agent config.

**C.3: Executor deferred handling** — `deferred` event → emit artifact + `requires_input()`. Resume detection via `approval_result` Part. `build_deferred_results()` method on backend. Remove `handle_post_response()` approval branch.

**C.4: Client approval flow** — `StreamEvent` gains `input_required`. `HubClient` sends `approval_result` Parts on resume. Approval widget in streaming/chat layer. Update `render_stream()` and `run_chat_loop()`.

**C.5: Tests** — Unit tests for all new types and flows. Integration test: shell agent proposes command → deferred → client approves → command executes server-side.

---

**Status: Unstarted. Research spike required before design sketch.**

**Problem.** The current approval model is a single `requires_approval: bool` on `AgentCardMeta`. The client (CLI) reads that flag and shows an approval widget on structured output. That's adequate for the shell agent's "execute/cancel" gate. It's nowhere near enough for the experimentation patterns the project wants to support.

**Examples of approval needs we'll encounter:**

- **Per-tool-call approval.** "Agent wants to run `rm -rf /tmp/x`. Approve?" Different gate than agent-level approval.
- **Plan approval.** Agent produces a multi-step plan; human approves the plan, then steps execute without further approval.
- **Approval with edit.** Agent proposes a command; human edits it before it runs.
- **Destructive-effect approval.** Any write to disk, any network call, any `git push`, any DB write.
- **Approval thresholds.** Auto-approve reads, gate writes, always-prompt for deletes.
- **Batch approval.** Agent proposes 10 edits; human approves/rejects per file, or approves all.
- **Provisional execution.** Run in a sandbox, show diff, approve merge.

**Why it's trap-prone.** Each of these examples could be implemented as "just another flag", and if we do that six times we end up with a `requires_approval` bool, a `tool_approval_policy` enum, a `plan_approval_hook`, a `destructive_effect_checker`, etc. — a pile of unrelated mechanisms that don't compose. The right abstraction is almost certainly a **single `ApprovalGate` protocol** with well-defined hook points in the loop, but the exact shape depends on:

- What granularity does the loop actually expose? (→ answered by Executor Loop Rework)
- How does a gate return control — sync, async, via the event queue back to the client?
- How are gate decisions serialized for resumability / replay?
- Do gates compose (chain of `ApprovalGate`s)? What's the resolution semantics?

**Recommended research spike.** Before any design sketch, spend a session reading how other projects handle this:

- **Claude Code** — its tool-approval prompts, settings (`--dangerously-skip-permissions`, `allowed_tools`, etc.)
- **opencode** — permission/approval model
- **AutoGen / LangGraph** — their `HumanMessage` / interrupt patterns
- **Cursor / Aider** — diff-and-approve flows
- **Copilot Workspace, Devin, others** — plan-approval UX

Write up findings as a comparison matrix. From that, identify the minimum gate primitive that composes cleanly. Only then sketch.

**Dependency note.** HITL design is loosely coupled to Executor Loop Rework. The loop refactor defines *where* gates fire (hook points); HITL research defines *what gates do when they fire*. Execute in that order.

**Do not bake gate semantics into the loop refactor.** The temptation will be to design approval in the same session as the loop. Resist — they compose better if designed independently and then reconciled.

---

### QA/Testing Agent (2026-04-22) — Idea Capture

**Status: Idea capture, no design yet.**

**Concept.** A specialized agent designed to test software — not unit tests, but exploratory and integration testing from a user's perspective. The agent is given documentation (README, API docs, CLI help), creates a test plan, then executes it against a live system.

**Core capabilities envisioned:**

- **Interactive REPL testing.** Agent can drive REPL sessions (Python, Node, custom CLIs) — send input, read output, assert on response content. Not just "run a script and check exit code" but actual interactive dialogue with a running process.
- **Scoped bash access.** Agent can run shell commands within a scoped working directory (and possibly a container/sandbox). Reads are unrestricted; writes and destructive operations go through HITL gates (→ depends on HITL Approval Model design).
- **Documentation ingestion.** Agent accepts documentation as context — README, man pages, API specs, CLI `--help` output. It uses this to understand what the software *should* do before testing what it *actually* does.
- **Plan-and-execute workflow.** Agent produces a test plan (list of scenarios, expected behaviors), presents it for approval, then executes step-by-step. Plan is a first-class artifact — human can review, edit, approve before execution begins.

**Why this is interesting for fin-assist.**

- Proves the executor loop can support plan-and-execute (not just one-shot chat).
- Exercises tool calling (REPL I/O, bash) end-to-end.
- Exercises HITL gates at plan-approval and destructive-action boundaries.
- Distinct from the shell agent: shell is "tell me a command", this is "here's software, test it."
- Natural fit for the A2A agent card model — its capabilities (REPL driver, bash, plan output) would be declared as metadata.

**Open design questions:**

1. **REPL session management.** How does the agent hold an open REPL session? Options: (a) a `REPLSession` tool that starts a subprocess, sends lines, reads stdout/stderr; (b) delegate to a tmux/zellij pane via the existing multiplexer concept; (c) use `pexpect`/`pty` for pseudo-terminal control. Each has tradeoffs around reliability, timeout handling, and output parsing.
2. **Scoping / sandboxing.** How far does "scoped bash" go? Working directory restriction is trivial. Container isolation (Docker, Nix) is safer but adds latency and config complexity. Is a chroot or Nix shell sufficient for MVP?
3. **Test plan schema.** What does a test plan look like as a structured artifact? Needs to be machine-readable (for step-by-step execution tracking) and human-readable (for approval). Probably a list of `{scenario, steps[], expected_outcomes[]}` objects surfaced as an A2A artifact.
4. **Assertion language.** How does the agent express "the output should contain X" or "the exit code should be 0"? Inline in the plan? A mini assertion DSL? Plain English that the LLM evaluates?
5. **Result reporting.** How are test results surfaced? Per-step pass/fail in artifacts? A summary artifact at the end? Both? How does a client render a test run in progress vs. completed?
6. **Relationship to SDD/TDD agents.** The architecture doc lists SDD and TDD agents as future work (Phase 16). Is the testing agent *the* TDD agent, a separate thing, or do they share a base? TDD implies "write tests for code I'm building"; this agent is "test software that already exists." Different scope, possibly shared tooling.

**Dependencies (must land before implementation):**

- Executor Loop Rework (tool calling, multi-step turns)
- HITL Approval Model (plan approval, destructive-action gates)
- ContextProviders integration (documentation ingestion)

**Recommended next action.** Research spike: survey existing tools in this space (SWE-agent, OpenHands, Aider's test runner, Codex's eval harness). Identify which REPL/session management pattern they use and what works. Then sketch the tool interface (`REPLSession`, `BashRunner`, etc.) and test plan artifact schema.

**Status: Phase B integrated — model-driven path complete, user-driven path partially complete.**

**What exists.** `FileFinder`, `GitContext`, `ShellHistory`, `Environment` in `src/fin_assist/context/`. Each implements the `ContextProvider` protocol (`base.py`). Full unit test coverage under `tests/test_context/`. Supporting types: `ContextItem`, `ContextType` enum, `ItemStatus` lifecycle.

**What's wired (Phase B):**
- Model-driven path: `read_file`, `git_diff`, `git_log`, `shell_history` registered as tools in `ToolRegistry` via `create_default_registry()`. Default agent config includes all four. `PydanticAIBackend` resolves agent tools and registers them as pydantic-ai `Tool` objects.
- User-driven path (partial): `--file` and `--git-diff` CLI flags on `do` command inject context into the prompt via `_inject_context()`. `AgentCardMeta.supported_context_types` derived from agent's tool list.
- `AgentSpec.supports_context()` now driven by agent's `tools` config via `_CONTEXT_TYPE_MAP`.

**What's still not wired:**
- `--git-log` CLI flag (low priority — model can call the `git_log` tool).
- `Environment` context provider not registered as a tool (intentional — env vars are sensitive).
- `@`-triggered completion in `FinPrompt` for talk mode.
- `llm/prompts.py`'s `build_user_message`/`format_context` helpers still not called from the request path (CLI injection bypasses them).

**Why parked, not deleted.** The classes encode design decisions (context taxonomy, item lifecycle, provider interface) that the CLI and Executor will consume when Steps 7-8 land. Rewriting them when needed is strictly more work than keeping them. The alternative — delete now, recreate later — would also lose the tests.

**When to pick up.** After the Executor loop rework (see above). The loop rework changes the shape of what "inject context" means, so wiring context providers before the loop exists would lock in the wrong API.

**In-code marker.** `src/fin_assist/context/__init__.py` has a module docstring pointing here, so a future session reading the code sees the parked status without having to grep the handoff.

**The session that picks this up should:**

1. Re-read this entry + the in-code docstring.
2. Confirm the Executor loop rework has landed (otherwise, don't start).
3. Choose one provider (probably `FileFinder`) and wire it end-to-end as a vertical slice — CLI flag → Executor injection → system prompt. Ship it. Then generalize for the others.
4. Update `AgentSpec.supports_context()` to read from `AgentConfig.supported_context_types` rather than the hardcoded set.

---

### AgentBackend Extraction (2026-04-21)

**Problem**: The `Executor` is deeply coupled to pydantic-ai (~15 distinct API touch points in 283 lines). It both orchestrates the A2A task lifecycle AND translates between A2A and pydantic-ai message formats. `AgentSpec` (formerly `ConfigAgent`) has framework-coupled construction methods (`build_pydantic_agent()`, `build_model()`). `ContextStore` hardcodes `TypeAdapter(list[ModelMessage])` for serialization.

**Goal**: Extract pydantic-ai coupling into an `AgentBackend` protocol so that the `Executor` orchestrates the A2A task lifecycle without knowing which LLM framework is underneath, `ContextStore` becomes framework-agnostic, and `AgentSpec` becomes a pure config object.

**Protocol shapes**:

```python
@dataclass
class RunResult:
    output: Any                     # final output (str or structured)
    serialized_history: bytes       # opaque — backend owns the format
    new_message_parts: list[Part]   # already in A2A terms (thinking, etc.)

class StreamHandle(Protocol):
    def __aiter__(self) -> AsyncIterator[str]: ...   # text deltas
    async def result(self) -> RunResult: ...         # call after iteration

class AgentBackend(Protocol):
    def check_credentials(self) -> list[str]: ...
    def convert_history(self, a2a_messages: Sequence[Message]) -> list[Any]: ...
    def run_stream(self, *, messages: list[Any], model: Any) -> StreamHandle: ...
    def serialize_history(self, messages: list[Any]) -> bytes: ...
    def deserialize_history(self, data: bytes) -> list[Any]: ...
    def convert_result_to_part(self, result: Any) -> Part: ...
```

**Key decisions**:

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Streaming API | `StreamHandle` (iterator + result accessor) | Matches the two-phase shape of all LLM frameworks (stream tokens, then access final result). Consumer drives iteration. Backend wraps context manager lifecycle internally. |
| ContextStore | `bytes` in/out | Backend owns serialization. ContextStore becomes a dumb KV store. Zero framework deps. |
| AgentSpec role | Pure config object | No `build_pydantic_agent()` or `build_model()` — those move to `PydanticAIBackend`. AgentSpec exposes config via properties only. |
| `RunResult.new_message_parts` | `list[Part]` (A2A type) | Conversion is the backend's job. `Part` is our domain type (A2A), not a framework type. |
| `check_credentials()` | Stays on AgentSpec, backend delegates | Credential checking is a config concern, not a framework concern. |

**Implementation phases**:

1. Rename: `ConfigAgent` → `AgentSpec`, `FinAssistExecutor` → `Executor`
2. Create `AgentBackend` protocol + `PydanticAIBackend` (TDD)
3. Make `ContextStore` framework-agnostic (`bytes` in/out)
4. Refactor `Executor` to take `AgentBackend` instead of `AgentSpec`
5. Update `AgentFactory` wiring
6. Move `build_pydantic_agent()` / `build_model()` from `AgentSpec` to `PydanticAIBackend`
7. Update all tests
8. `just ci` verification

### Nix / Home Manager Packaging (2026-04-21)

**Status**: Pre-design — no implementation started.

**Goal**: Make fin-assist installable via Nix and declaratively manageable via Home Manager, integrating with the owner's existing dotfiles-driven setup.

**Why**: The owner's dev environment is fully declarative via Home Manager (`~/dotfiles/home.nix`). fin-assist should be installable the same way as every other tool, with config managed alongside the rest of the dotfiles.

#### Layer 1: PyPI Publishing (prerequisite)

Publish to PyPI so Nix tooling can fetch a known-good sdist/wheel. Without this, `uv2nix` and `nixpkgs buildPythonApplication` have nothing to build from.

Steps:
1. Ensure `pyproject.toml` has correct metadata (description, classifiers, license, URLs)
2. Add CI workflow for publishing on tag push (`uv publish`)
3. Publish v0.1.0 to PyPI (or TestPyPI first)

#### Layer 2: Nix Flake

Two viable approaches:

| Approach | How | Pros | Cons |
|----------|-----|------|------|
| **`uv2nix`** | Locks `uv.lock` into Nix derivations | Most idiomatic for Python+nix; already uses `uv`; reproducible lockfile | Requires `uv2nix` + `pyproject.nix` in flake inputs; more moving parts |
| **`nixpkgs buildPythonApplication`** | Fetches from PyPI | Simpler overlay; familiar pattern | Requires PyPI publish first; dependency resolution via nixpkgs may lag |

Recommendation: **`uv2nix`** — the project already uses `uv` and `devenv`, so `uv2nix` is the natural fit. It produces a `python313Packages.fin-assist` derivation from the lockfile.

Flake structure:

```nix
# flake.nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
    uv2nix.url = "github:pyproject-nix/uv2nix";
    # ...
  };
  outputs = { nixpkgs, pyproject-nix, uv2nix, ... }@inputs: {
    packages.x86_64-linux.fin-assist = ...;  # uv2nix derivation
    overlays.default = final: prev: { fin-assist = ...; };
  };
}
```

#### Layer 3: Home Manager Module

A `programs.fin-assist` module for declarative config + service management:

```nix
# In home.nix
programs.fin-assist = {
  enable = true;

  settings = {
    general.default_provider = "anthropic";
    general.default_model = "claude-sonnet-4-6";

    agents.default = {
      enabled = true;
      system_prompt = "chain-of-thought";
      output_type = "text";
      thinking = "medium";
      serving_modes = ["do" "talk"];
    };

    agents.shell = {
      enabled = true;
      system_prompt = "shell";
      output_type = "command";
      thinking = null;
      serving_modes = ["do"];
      requires_approval = true;
    };
  };

  # Optional: run hub server as systemd user service
  server = {
    enable = true;           # auto-start on login
    port = 4096;
  };

  # Optional: fish plugin (when Phase 12 lands)
  fishIntegration.enable = true;
};
```

**Module implementation** would generate:
- `~/.config/fin/config.toml` from `settings` (Nix → TOML via `formats.toml`)
- `~/.local/share/fin/` data directory (via `xdg.dataFile` or `systemd.tmpfiles`)
- `systemd.user.services.fin-assist-hub` if `server.enable = true`
- Fish plugin files if `fishIntegration.enable = true`

**Credential handling**: API keys stay out of the Nix store (they're secrets). The module would document using `CredentialStore` file or env vars post-install, or integrate with the owner's 1Password CLI setup via `secretspec`.

#### Open Questions

| Question | Notes |
|----------|-------|
| PyPI package name | `fin-assist` (matches CLI) or `fin_assist` (matches Python package)? Most tools use the dash form on PyPI |
| Flake location | Standalone flake in this repo, or add to `~/dotfiles/flake.nix` as an overlay? |
| Versioning | Start PyPI publishes at `0.1.0` or wait until a stable feature set? |
| uv2nix vs nixpkgs | Verify `uv2nix` handles `a2a-sdk` and `pydantic-ai` dependency chains correctly before committing |
| Config validation | Nix → TOML generation needs to match `Config` schema exactly; consider generating from the same schema |

#### Dependencies

- PyPI publish must come first (for `nixpkgs` approach) or be done in parallel (for `uv2nix` which builds from source)
- Fish plugin module depends on Phase 12
- systemd service for hub server is independent — can ship as soon as packaging works

---

## AgentBackend Extraction — Accomplished (2026-04-21)

**Status**: Complete

### What Was Accomplished

Extracted pydantic-ai coupling from the hub layer into an `AgentBackend` protocol so the `Executor` orchestrates A2A task lifecycle without knowing which LLM framework is underneath.

**Phase 1: Rename** — `ConfigAgent` → `AgentSpec`, `FinAssistExecutor` → `Executor` across 12 source + test files.

**Phase 2: Backend protocol** — Created `agents/backend.py` with `AgentBackend` protocol, `StreamHandle` protocol, `RunResult` dataclass, and `PydanticAIBackend` concrete implementation. 24 new tests.

**Phase 3: ContextStore** — Changed from `TypeAdapter(list[ModelMessage])` to `bytes`-in/`bytes`-out. Backend owns serialization. Zero framework deps in `context_store.py`.

**Phase 4: Executor refactor** — Executor now takes `AgentBackend` instead of `AgentSpec`. No pydantic-ai imports. Uses `StreamHandle` for streaming and `RunResult` for final results.

**Phase 5: Factory wiring** — `AgentFactory.create_a2a_app()` creates `PydanticAIBackend(agent_spec=agent)` and passes to `Executor(backend=backend, ...)`.

**Phase 6: Move construction** — `build_pydantic_agent()` and `build_model()` moved from `AgentSpec` to `PydanticAIBackend._build_pydantic_agent()` and `_build_model()`. `AgentSpec` is now a pure config object (properties only).

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Streaming API | `StreamHandle` (iterator + result accessor) | Matches two-phase shape of all LLM frameworks. Consumer drives. Backend wraps context manager internally. |
| ContextStore | `bytes` in/out | Backend owns serialization. Zero framework deps. Adding a new backend automatically gets serialization. |
| AgentSpec role | Pure config object | No `build_pydantic_agent()` or `build_model()`. All pydantic-ai knowledge in `PydanticAIBackend`. |
| `RunResult.new_message_parts` | `list[Part]` (A2A type) | Conversion is the backend's job. `Part` is our domain type, not a framework type. |
| `check_credentials()` | Stays on AgentSpec, backend delegates | Credential checking is a config concern. |

### Files Changed

| File | Change |
|------|--------|
| `src/fin_assist/agents/agent.py` | Renamed `ConfigAgent` → `AgentSpec` |
| `src/fin_assist/agents/__init__.py` | Updated exports, added backend types |
| `src/fin_assist/agents/backend.py` | **New** — `AgentBackend`, `StreamHandle`, `RunResult`, `PydanticAIBackend` |
| `src/fin_assist/agents/metadata.py` | Updated docstring reference |
| `src/fin_assist/hub/executor.py` | Rewritten — takes `AgentBackend`, zero pydantic-ai imports |
| `src/fin_assist/hub/factory.py` | Creates `PydanticAIBackend`, passes to `Executor` |
| `src/fin_assist/hub/app.py` | Updated type hints |
| `src/fin_assist/hub/context_store.py` | `bytes` in/out, no framework deps |
| `src/fin_assist/hub/__init__.py` | Updated exports |
| `src/fin_assist/cli/main.py` | Updated import + construction |
| `tests/test_agents/test_backend.py` | **New** — 24 backend tests |
| `tests/test_agents/test_agent.py` | Renamed all references |
| `tests/test_hub/test_executor.py` | Rewritten — mocks `AgentBackend` instead of pydantic-ai |
| `tests/test_hub/test_context_store.py` | Uses `bytes` instead of `ModelMessage` |
| `tests/test_hub/test_factory.py` | Updated imports |
| `tests/test_hub/test_app.py` | Patches `PydanticAIBackend._build_model` |

### Test Summary

```text
494 tests passing (467 before + 27 new: 24 backend + 3 executor)
CI green (fmt, lint, typecheck, all tests)
```

### Next Steps

- None remaining from backend extraction — all cleanup complete

---

## fasta2a → a2a-sdk Migration (2026-04-20)

**Status**: Complete (Phases 1-7)

### What Was Accomplished

Full migration from `fasta2a` (pydantic's abandoned A2A implementation) to `a2a-sdk` (Google's official A2A Python SDK v1.0.0), plus Phase 9 streaming that was blocked on fasta2a.

**Phase 1: Storage split** — `hub/context_store.py` extracts conversation history (ModelMessage) from `SQLiteStorage`. A2A task storage uses `InMemoryTaskStore` (ephemeral).

**Phase 2: AgentExecutor** — `hub/executor.py` replaces `FinAssistWorker(Worker[Context])`. Uses `TaskUpdater` for all state transitions (`start_work`, `complete`, `failed`, `requires_auth`). `MissingCredentialsError` → `updater.requires_auth()`. Protobuf message types replace TypedDicts.

**Phase 3: Factory + Agent Card** — `hub/factory.py` uses a2a-sdk route factories (`create_jsonrpc_routes`, `create_agent_card_routes`). `AgentExtension(uri="fin_assist:meta")` replaces `Skill(id="fin_assist:meta")` hack. `AgentCapabilities(streaming=True, extensions=[...])`.

**Phase 4: Hub App** — `hub/app.py` is a FastAPI parent app (matching sub-apps from a2a-sdk). No more `AsyncExitStack` lifespan hack. Sub-apps from route factories don't need explicit lifespan management.

**Phase 5: Client** — `cli/client.py` uses `ClientFactory(config=ClientConfig(httpx_client=...))` + `client.send_message(request)` async iterator. `_poll_task()` eliminated. `_task_to_dict()` normalizes protobuf enums (state ints → strings, `ROLE_AGENT` → `agent`).

**Phase 6: Streaming** — Executor uses `pydantic_agent.run_stream()` + `stream.stream_text(delta=True)` → `TaskUpdater.add_artifact(append=True, last_chunk=False)` per delta, final `last_chunk=True`. Client `stream_agent()` yields `StreamEvent` objects (`text_delta`, `completed`, `failed`, `auth_required`). Chat loop uses Rich `Live` for progressive Markdown display.

**Phase 7: Cleanup** — Deleted `hub/worker.py`, `hub/storage.py`, `tests/test_hub/test_worker.py`, `tests/test_hub/test_storage.py`. Removed `fasta2a>=0.6` from `pyproject.toml`. All fasta2a imports eliminated.

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Task persistence | `InMemoryTaskStore` (ephemeral) | Tasks created/resolved in one session; history persisted separately in `ContextStore` |
| Auth-required state | `TaskUpdater.requires_auth()` | First-class in a2a-sdk (`TaskState.TASK_STATE_AUTH_REQUIRED` = value 8) |
| Agent card metadata | `AgentExtension(uri="fin_assist:meta")` | Proper A2A extension, eliminates `Skill(id="fin_assist:meta")` hack |
| Parent app framework | FastAPI | Matches a2a-sdk sub-apps from route factories |
| Streaming depth | Token-by-token via `stream_text(delta=True)` | Fine-grained progressive output; `add_artifact(append=True, last_chunk=)` for chunking |
| No broker | `DefaultRequestHandler` handles routing | Eliminates `InMemoryBroker` indirection |
| No lifespan hack | Route factory sub-apps are self-contained | No `AsyncExitStack` needed |

### Files Changed

| File | Change |
|------|--------|
| `pyproject.toml` | Removed `fasta2a>=0.6` |
| `hub/worker.py` | **Deleted** |
| `hub/storage.py` | **Deleted** |
| `hub/context_store.py` | **New** (Phase 1) — extracted from SQLiteStorage |
| `hub/executor.py` | **New** (Phase 2) — a2a-sdk AgentExecutor + streaming |
| `hub/factory.py` | Rewritten for a2a-sdk route factories + AgentExtension |
| `hub/app.py` | Rewritten as FastAPI parent |
| `hub/__init__.py` | Updated exports |
| `cli/client.py` | Rewritten for a2a-sdk ClientFactory + StreamEvent |
| `cli/interaction/chat.py` | Added streaming support via Rich Live |
| `tests/test_hub/test_worker.py` | **Deleted** |
| `tests/test_hub/test_storage.py` | **Deleted** |
| `tests/test_hub/test_executor.py` | **New** — executor + streaming tests |
| `tests/test_hub/test_context_store.py` | Already existed from Phase 1 |
| `tests/test_hub/test_factory.py` | Updated for a2a-sdk |
| `tests/test_hub/test_app.py` | Updated for FastAPI + a2a-sdk |
| `tests/test_cli/test_client.py` | Rewritten — removed fasta2a, added StreamEvent tests |

### Test Summary

```text
446 tests passing (23 removed from deleted worker/storage tests, 1 new streaming test added)
11 protobuf type annotation warnings (inherent to a2a-sdk generated types)
```

### Known Issues

- 11 `ty` typecheck warnings from protobuf types — `RepeatedCompositeFieldContainer` vs `list`, `Value` vs `Struct`, `MessageToDict` returning untyped dicts. These are inherent to a2a-sdk's protobuf-based API.
- `_stream_and_render` in chat.py falls back to blocking `send_message_fn` for the `do` command. The `do` command stays blocking (intentional per plan).

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

## Config-Driven Redesign (2026-04-11)

**Status**: Steps 1-6 complete. Steps 7-9 pending.

### Problem

Three issues drove this redesign:

1. **Issue #68**: `FinAssistWorker` imports from `pydantic_ai._a2a.AgentWorker` (private API). This breaks on any pydantic-ai upgrade.
2. **Class hierarchy rigidity**: `DefaultAgent` and `ShellAgent` are separate subclasses that differ only in system prompt, output type, thinking support, and approval. Adding a new agent means writing a new class — even if it's just a config variant.
3. **No agent configuration**: The architecture doc describes `[agents.default]` and `[agents.shell]` TOML sections, but `Config` has zero agent configuration. Agents are hardcoded in `_serve_command`.

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent architecture | Config-driven, not class-hierarchy | `ShellAgent` behavior becomes a TOML config variant of a single `ConfigAgent` class |
| `DefaultAgent` → `ConfigAgent` | Rename, config-driven, no ABC | `system_prompt`, `output_type`, thinking, serving modes, approval all from `AgentConfig`. No `BaseAgent` ABC — single impl doesn't need it; `Protocol` for DI if needed later |
| `ShellAgent` | Remove entirely | Its behavior is expressible as config: `[agents.shell]` with `output_type = "command"`, `serving_modes = ["do"]`, `requires_approval = true` |
| `AgentWorker` private import | Replace with direct `Worker[list[ModelMessage]]` | Public fasta2a API, eliminates private import, removes wasted default worker construction |
| `pydantic_agent.to_a2a()` | Replace with direct `FastA2A()` construction | Eliminates wasted default `AgentWorker`, enables custom lifespan without replacing it |
| Thinking | Per-agent config field | Moves from `DefaultAgent` override into `AgentConfig`, driven by TOML |
| `multi_turn: bool` | Replaced by `ServingMode` enum | `"do"`, `"talk"`, `"do_talk"` — declares which CLI modes an agent supports |
| Default agent shortcut | `fin do "prompt"` / `fin talk` → `[agents.default]` | No agent arg required; resolves to default config |
| Context for `do` | CLI flags (`--file`, `--git-diff`, `--git-log`) | No TUI required |
| Context for `talk` | `@`-completion in FinPrompt via `ContextProvider.search()` | Uses existing search, no TUI required |
| `@selection` context | Deferred to TUI/Phase 13+ | Requires richer interaction model |

### What Was Accomplished

**Steps 1-6 implemented (2026-04-12):**

1. **`ServingMode` + `serving_modes`** — `ServingMode = Literal["do", "talk"]` in `metadata.py`. `AgentCardMeta.serving_modes` replaces `multi_turn: bool`. CLI validates in both `do` and `talk` commands.
2. **Output type + prompt registries** — `OUTPUT_TYPES` and `SYSTEM_PROMPTS` dicts in `registry.py`. Unknown names fall through (passthrough for system_prompt, str for output_type).
3. **Per-agent TOML config** — `AgentConfig` in `config/schema.py` with all fields. `_DEFAULT_AGENTS` dict. `_serve_command` creates `ConfigAgent` instances from `config.agents`.
4. **ConfigAgent (no ABC)** — Removed `BaseAgent` ABC, `DefaultAgent`, `ShellAgent` classes. Single `ConfigAgent` in `agent.py`. Moved metadata types (`AgentCardMeta`, `AgentResult`, `MissingCredentialsError`, `ServingMode`) to `metadata.py`. No ABC, no subclasses — `typing.Protocol` for DI if needed later.
5. **Direct Worker implementation** — `FinAssistWorker(Worker[Context])` using public `fasta2a.Worker` ABC. No private `pydantic_ai._a2a` import. Direct `FastA2A()` construction in factory. Closes #68.
6. **Default agent shortcut** — `agent` arg is `nargs="?", default="default"` in both `do` and `talk` parsers.

**Additional decision: No `AgentSpec`/`from_spec()` integration.**

We investigated using `pydantic_ai.AgentSpec` + `Agent.from_spec()` as an internal construction helper in `ConfigAgent.build_pydantic_agent()`. Rejected because:

- `from_spec()` requires a model immediately and calls `infer_model()` (needs API keys)
- Our architecture defers model resolution to run time (`model=None` on `Agent()`) so the hub can start before credentials are configured
- `Agent(model=None)` skips `infer_model()` — our current pattern already works
- `from_spec()` doesn't pass `defer_model_check` through to the constructor
- `AgentConfig` still owns everything `AgentSpec` doesn't (serving modes, approval, credential injection, agent card metadata)
- If `from_spec()` gains `defer_model_check` support in the future, we can adopt it as an internal helper

The full rationale is documented in `agents/agent.py` module docstring.

**Files changed:**
- `agents/metadata.py` — NEW (extracted from old `base.py`)
- `agents/agent.py` — Rewritten as `ConfigAgent` (no ABC)
- `agents/base.py` — DELETED
- `agents/default.py` — DELETED
- `agents/shell.py` — DELETED
- `agents/__init__.py` — Updated exports
- `hub/worker.py` — Updated imports
- `hub/factory.py` — Updated imports
- `hub/app.py` — Updated imports
- `cli/client.py` — Updated imports
- `cli/main.py` — Updated imports + `ConfigAgent` usage
- All test files updated; `test_base.py`, `test_default.py`, `test_shell.py`, `test_credentials_check.py` deleted (merged into `test_agent.py`)

### The 9-Step Implementation Plan

**Step 1: `ServingMode` enum + `serving_modes` field** — Add `ServingMode = Literal["do", "talk", "do_talk"]` to `agents/metadata.py`. Add `serving_modes: list[ServingMode] = ["do", "talk"]` to `AgentCardMeta` (replaces `multi_turn: bool`). Update CLI `do`/`talk` commands to validate against `serving_modes` before sending.

**Step 2: Output type + prompt registries** — Create registry mapping config names to types: `{"text": str, "command": CommandResult}`. Create registry mapping names to prompt constants: `{"chain-of-thought": CHAIN_OF_THOUGHT_INSTRUCTIONS, "shell": SHELL_INSTRUCTIONS}`. Enables TOML to reference types/prompts by name.

**Step 3: Per-agent TOML config sections** — Add `AgentConfig` to `config/schema.py` with fields: `enabled`, `system_prompt` (name), `output_type` (name), `thinking` (ThinkingEffort), `serving_modes`, `requires_approval`, `tags`. Add `agents: dict[str, AgentConfig]` to `Config` with default entries for `default` and `shell`. `_serve_command` reads from config instead of hardcoding.

**Step 4: Collapse to single `ConfigAgent` class** (depends on 1-3) — Remove `BaseAgent` ABC, `DefaultAgent`, and `ShellAgent` classes. Create `ConfigAgent` in `agents/agent.py` — a concrete class (no ABC) that takes `name: str`, `AgentConfig`, `Config`, `CredentialStore`. All behavior driven by config. `build_pydantic_agent()` uses config-driven thinking + output type. `agent_card_metadata` derives from config fields. If a type bound is needed for DI/mocking, use `typing.Protocol`.

**Step 5: Direct `Worker` implementation** (#68 resolution) — Replace `FinAssistWorker(AgentWorker)` with `FinAssistWorker(Worker[list[ModelMessage]])`. No import from `pydantic_ai._a2a`. Own ~100 lines of message conversion using `pydantic_ai.messages` public types. Constructor takes `pydantic_agent`, `agent_config`, `broker`, `storage`. Update `factory.py`: construct `FastA2A()` directly with custom lifespan, no `pydantic_agent.to_a2a()`.

**Step 6: Default agent shortcut in CLI** (depends on 4) — `fin do "prompt"` (no agent arg) → `[agents.default]`. `fin talk` (no agent arg) → `[agents.default]`. Agent arg becomes optional with default.

**Step 7: Context injection for `do`** — Add `--file`, `--git-diff`, `--git-log` CLI flags to `do` command. Inject as `ContextItem`s into user message.

**Step 8: Context injection for `talk`** — Extend `FinPrompt` with `@`-triggered fuzzy completion via `ContextProvider.search()`. `@file:`, `@git:`, `@history:` prefixes.

**Step 9: Approval "add context" option for structured output in talk** (depends on 4) — When `CommandResult` returns in talk mode: `[execute] [add context] [cancel]`. "Add context" drops back into REPL with previous generation in history.

### Dependency graph

```text
Step 1 (serving modes) ──────────────────────┐
Step 2 (registries) ──────────────────────────┤
Step 5 (Worker impl) ────────────────────────┤
                                              ├──▶ Step 4 (collapse Agent) ──▶ Step 6 (default shortcut)
Step 3 (TOML config) ────────────────────────┘
Step 7 (context flags for do) ── independent
Step 8 (@-completion for talk) ── independent
Step 9 (approval in talk) ── depends on Step 4
```

### Discoveries

- **Mental model vs implementation drift:** No agent config system exists (agents hardcoded in `_serve_command`), `AgentCardMeta` grew beyond the architecture doc (`requires_approval` added ad-hoc), context injection has no user-facing mechanism (auto-gathered only), and thinking is only modular inside `DefaultAgent`'s override.
- **Structured output in multi-turn is valid:** `output_type` constrains what the agent returns per response, not the conversation shape. A `CommandResult` response in a talk session is coherent — generate → render → "add context" → back to REPL → regenerate with history.
- **Issue #68 is partially addressed by the config-driven approach:** The unified `Agent` class eliminates the "two agents" problem, but doesn't fix the private import. That requires implementing `Worker` directly — Step 5.
- **`AgentWorker` inherits ~200 lines of message conversion logic** that the direct `Worker` implementation needs to own (~100 lines) using public `pydantic_ai.messages` types.
- **`AgentCardMeta` is encoded as a `Skill(id="fin_assist:meta")`** with JSON in the `description` field — a workaround until fasta2a PR #44 lands.
- **`pydantic_agent.to_a2a()` creates a default `AgentWorker` that gets immediately discarded** — our custom lifespan replaces it. Direct `FastA2A()` construction eliminates this waste.

### Relevant Files

| File | Change |
|------|--------|
| `src/fin_assist/agents/agent.py` | Step 4 — New `ConfigAgent` class (replaces `base.py`, `default.py`, `shell.py`) |
| `src/fin_assist/agents/metadata.py` | Steps 1, 4 — `ServingMode`, `AgentCardMeta`, `AgentResult` (extracted from old `base.py`) |
| `src/fin_assist/agents/default.py` | Step 4 — Removed (absorbed into `ConfigAgent`) |
| `src/fin_assist/agents/shell.py` | Step 4 — Removed (behavior is `[agents.shell]` config) |
| `src/fin_assist/agents/results.py` | Step 2 — Referenced by output type registry |
| `src/fin_assist/agents/__init__.py` | Steps 2, 4 — Updated exports |
| `src/fin_assist/hub/worker.py` | Step 5 — Rewritten as `Worker[list[ModelMessage]]` |
| `src/fin_assist/hub/factory.py` | Step 5 — Direct `FastA2A()` construction |
| `src/fin_assist/hub/app.py` | Steps 3-5 — Config-driven agent creation |
| `src/fin_assist/cli/main.py` | Steps 1, 3, 6, 7 — Config-driven agents, default shortcut, context flags |
| `src/fin_assist/cli/client.py` | Step 1 — `AgentCardMeta` changes |
| `src/fin_assist/cli/interaction/approve.py` | Step 9 — "add context" option |
| `src/fin_assist/cli/interaction/chat.py` | Step 9 — `requires_approval` in talk |
| `src/fin_assist/cli/interaction/prompt.py` | Step 8 — `@`-completion |
| `src/fin_assist/config/schema.py` | Step 3 — `AgentConfig` |
| `src/fin_assist/config/loader.py` | Step 3 — Load agent configs |
| `src/fin_assist/llm/prompts.py` | Step 2 — Prompt registry |
| `docs/architecture.md` | All steps — Reflect config-driven design |
| `docs/manual-testing.md` | All steps — Update for config-driven agents |

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

## Design Sketch: Shared Render Pipeline (Option B)

**Status**: Complete

### Problem

Rendering is coupled to serving mode, not response type. Same `AgentResult` renders differently in `do` (Panel via `render_response`/`render_command`) vs `talk` (raw `console.print`). Widgets (thinking, warnings, approval) are bolted into specific code paths with inline if/else rather than composable. Approval widget doesn't work in `talk` at all.

### Design

**One entry point**: `render_agent_output(result, card_meta, *, show_thinking, mode)` composes existing widget functions. Both modes call the same function. `mode` only affects the text wrapper (Panel for `do`, Markdown for `talk`), not which widgets render.

Widget dispatch (driven by `AgentResult` + `AgentCardMeta`):

```text
auth_required?  → render_auth_required()
!result.success? → render_error()
requires_approval? → render_command()  (syntax panel + inline warnings + hint)
else (text)     → do: render_response() / talk: render_markdown()
show_thinking?  → render_thinking()
warnings?       → render_warnings()  (only when not already inside render_command)
```

Approval interaction stays in the caller (it's interaction, not display), but now works in both modes.

### Implementation Steps

1. **`display.py`** — Add `render_markdown(text)` (Rich `Markdown` class, no panel) + `render_agent_output(result, card_meta, *, show_thinking=False, mode="do")` composing all widget functions per dispatch table.
2. **`main.py`** — Replace inline rendering in `_do_command()` with `render_agent_output()`. Add `--show-thinking` flag to `do` subparser. Keep approval widget as separate interaction step after rendering.
3. **`chat.py`** — Add `card_meta: AgentCardMeta` param to `run_chat_loop()`. Replace inline rendering with `render_agent_output()`. Add approval widget support: after rendering, if `card_meta.requires_approval`, show `run_approve_widget()`.
4. **`main.py`** — Pass `card_meta` to `run_chat_loop()` in `_talk_command()`.
5. **Tests** — `TestRenderMarkdown`, `TestRenderAgentOutput` (matrix), update chat tests for `card_meta` param, add approval-in-talk test.

### Scope Limits

- No "add context" option in talk approval (Step 9 from config redesign)
- No `render_agent_output` return value / event system
- No streaming integration
- No new `AgentResult` fields

### What Was Accomplished

- Added `render_markdown()` and `render_agent_output()` to `display.py` — shared pipeline composes all widget functions based on `AgentResult` + `AgentCardMeta`
- Refactored `_do_command()` to use `render_agent_output()` instead of inline rendering
- Added `--show-thinking` flag to `do` subparser
- Refactored `run_chat_loop()` to accept `card_meta` param and use `render_agent_output()` with `mode="talk"`
- Added approval widget support in talk mode — when `card_meta.requires_approval`, shows `run_approve_widget()` after rendering
- Backward-compatible: when `card_meta` is `None`, chat loop falls back to legacy inline rendering
- Passed `card_meta=discovered.card_meta` from `_talk_command()` to `run_chat_loop()`
- Removed unused imports from `main.py` (`render_command`, `render_response`, `render_warnings`)
- Moved `AgentCardMeta` import to `TYPE_CHECKING` block in `chat.py`

### Test Summary

```text
tests/test_cli/test_display.py: +10 tests (TestRenderMarkdown: 2, TestRenderAgentOutput: 8)
tests/test_cli/interaction/test_chat.py: +2 tests (TestChatLoopCardMeta: 2)
tests/test_cli/test_main.py: 1 test updated (render_response → render_agent_output patch)
Total: 440 tests, all passing
```

### Files Changed

| File | Change |
|------|--------|
| `src/fin_assist/cli/display.py` | Added `render_markdown()`, `render_agent_output()`, `Markdown` import |
| `src/fin_assist/cli/main.py` | Refactored `_do_command()` to use `render_agent_output()`, added `--show-thinking` to `do`, passed `card_meta` to `run_chat_loop()`, removed unused imports |
| `src/fin_assist/cli/interaction/chat.py` | Added `card_meta` param to `run_chat_loop()`, uses `render_agent_output()` + approval widget when `card_meta` provided |
| `tests/test_cli/test_display.py` | Added `TestRenderMarkdown`, `TestRenderAgentOutput` |
| `tests/test_cli/interaction/test_chat.py` | Added `TestChatLoopCardMeta` (approval in talk, no approval when not required) |
| `tests/test_cli/test_main.py` | Updated `render_response` → `render_agent_output` patch |

---

## Next Session

### Recommended sequence

1. **Manual verification baseline.** Run the Pre-Refactor Smoke Set (`docs/manual-testing.md`): Chunk A (all), B1/B3/B4/B6, C1/C5/C10/C11/C13, F1/F3. Establishes a known-good baseline before the refactor.
2. ~~**Phase A: Foundation.**~~ COMPLETE. ContextStore version byte + `StepEvent` + `StepHandle` + `_PydanticAIStepHandle` + Executor rewrite (event-driven with approval verification) + all tests updated. 540 tests passing, CI green, CodeRabbit review findings fixed.
3. ~~**Phase B: Tool Calling.**~~ COMPLETE. `ToolRegistry` + `ToolDefinition` + `tools` config field + context-as-tools (`read_file`, `git_diff`, `git_log`, `shell_history`) + CLI `--file` / `--git-diff` flags (user-driven) + `AgentCardMeta.supported_context_types`. 577 tests passing, CI green.
4. **Phase C: HITL / Approval.** `ApprovalPolicy` + shell command tool with `requires_approval=True` + deferred event handling + client approval flow. Resolve open questions #2-4 (A2A pause state, resume protocol, deferred semantics).
5. **Phase D: Observability.** `[observability]` config + Arize Phoenix wiring + `Agent.instrument_all()` + Executor step spans. Can proceed in parallel with C.

Phases B–D can overlap once Phase A lands. The recommended vertical slice for a first implementation session is **Phase A + a minimal Phase B** (one tool: `read_file`) — this proves the loop works end-to-end with tool calling.

**Phase B accomplished (2026-04-24).**

- `ToolDefinition` dataclass in `agents/tools.py`: platform-level, framework-agnostic. Fields: `name`, `description`, `callable`, `parameters_schema`, `approval_policy` (reserved for Phase C).
- `ToolRegistry` class in `agents/tools.py`: global registry with `register()`, `get()`, `list_tools()`, `get_for_agent()`. Duplicate registration raises `ValueError`. `get_for_agent()` silently skips unknown tool names.
- `create_default_registry()` factory: pre-loads `read_file`, `git_diff`, `git_log`, `shell_history` tools wrapping existing `ContextProvider` classes as async callables.
- `AgentConfig.tools` field: list of tool name strings, defaulting to `["read_file", "git_diff", "git_log", "shell_history"]` for default agent, `[]` for shell agent.
- `AgentSpec.tools` property: delegates to `AgentConfig.tools`.
- `AgentSpec.supports_context()` now derived from tool list via `_CONTEXT_TYPE_MAP` instead of hardcoded frozenset.
- `AgentSpec.agent_card_metadata` populates `supported_context_types` from tool list.
- `AgentCardMeta.supported_context_types` field: list of context type strings derived from agent tools.
- `PydanticAIBackend` accepts optional `tool_registry` in `__init__`. `_build_pydantic_agent()` resolves agent's tools via `tool_registry.get_for_agent(spec.tools)` and registers them as pydantic-ai `Tool` objects with explicit names and descriptions.
- `AgentFactory` accepts optional `tool_registry`, defaults to `create_default_registry()`.
- CLI `--file` and `--git-diff` flags added to `do` command. `_inject_context()` helper prepends context from `FileFinder` and/or `GitContext` above the user's prompt.
- New test files: `tests/test_agents/test_tools.py` (ToolRegistry/ToolDefinition), `tests/test_cli/test_context_injection.py` (_inject_context).
- Updated tests: `test_spec.py` (tools property, supports_context from tools, card metadata context types), `test_backend.py` (tool registration in _build_pydantic_agent).
- Full CI green: 577 tests passing, lint/typecheck/fmt clean.

### Deferred / open as external tickets

- **AgentBackend protocol simplification.** Filed as [#80](https://github.com/ColeB1722/fin-assist/issues/80) (enhancement / tech-debt). Revisit when a second backend is actually needed.
- **Diagram / doc drift defense.** The "citation required" rule in `docs/architecture.md` (2026-04-22) is now the structural guard.

---

## Historical: A2A SDK Migration + Context Injection Plan (2026-04-20, superseded)

> **Status**: Goals 1-4 below are **complete** (a2a-sdk migration landed 2026-04-20; config-driven redesign Steps 1-6 landed 2026-04-11; Steps 7-9 explicitly deferred — see current Next Session for ordering). Kept as historical record of the migration plan.

### Original Goals

1. ~~**A2A SDK migration**~~: Done. See "fasta2a → a2a-sdk Migration (2026-04-20)" entry above.
2. **Step 7**: Add `--file`, `--git-diff`, `--git-log` CLI flags to `do` command. Inject as `ContextItem`s into user message. — **Deferred** until Executor Loop Rework lands.
3. **Step 8**: Extend `FinPrompt` with `@`-triggered fuzzy completion via `ContextProvider.search()`. — **Deferred**, same reason.
4. **Step 9**: Approval "add context" option for structured output in talk mode. — **Partially obsolete**. Folds into the HITL research spike, not a standalone step.
5. ~~**Manual testing**~~: Re-verified post-migration; `docs/manual-testing.md` was audited 2026-04-22 and corrected.

### Resolved Technical Debt

The custom protocol extensions below existed because fasta2a didn't support them. The a2a-sdk migration replaced most of them with native mechanisms:

| Convention (fasta2a era) | Resolution under a2a-sdk |
|--------------------------|--------------------------|
| `metadata.type == "thinking"` on TextPart | Still used; a2a-sdk has no native thinking part type. Acceptable. |
| `meta_skill` encoding on agent card skills | Replaced with `AgentExtension(uri="fin_assist:meta", params=Struct)` — proper a2a-sdk extension. |
| `metadata.auth_required` flag on AgentResult | Replaced with native `TaskState.TASK_STATE_AUTH_REQUIRED`. |

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
| 8b | **CLI REPL Mode** | ✅ Complete |
| — | **Config-Driven Redesign** | ✅ Steps 1-6 complete, Steps 7-9 pending |
| — | **Backend Extraction** | ✅ Complete — AgentSpec pure config, Executor framework-agnostic |
| 9a | **Progressive Output (polling)** | ↩️ Reverted — jank, tight coupling to pydantic-ai internals |
| 9b | Full SSE Streaming | ⬜ **Blocked** (fasta2a v0.7+ unreleased) |
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

## Design Sketch: Interactive Task State Machine (Phase 10) — Superseded

**Status**: Superseded by "Unified Executor & Agent Platform Sketch (2026-04-24)" Phase C (HITL / Deferred Tools). The `input-required` state machine and `InputRequiredError` pattern below remain valid reference material; the unified sketch refines the approach using pydantic-ai Deferred Tools instead of a custom gate protocol.

### Problem

The current `_poll_task` / `_resolve_task` logic in `HubClient` treats the A2A task lifecycle as binary: poll until terminal, then extract the result. This works for agents that run to completion without further input, but the A2A spec supports `input-required` — an agent pausing mid-task to ask the client for more information (e.g., disambiguation, confirmation, missing parameters).

Today, if an agent returned `input-required`, our poll loop would spin forever until timeout because that state isn't in `_TERMINAL_STATES` and we have no mechanism to surface the agent's question to the user.

### A2A Task State Machine

```text
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
- A2A protocol via a2a-sdk v1.0 for multi-client support
- Multi-path routing: N agents at `/agents/{name}/`, each with own agent card
- Conversation threading via A2A `context_id`
- SQLite for context storage; InMemoryTaskStore for A2A tasks (ephemeral)
- Server lifecycle: standalone via `fin-assist serve`; auto-start from CLI
- Existing TUI widgets set aside — will become A2A client in Phase 11
- `AgentSpec` is a pure config object (zero framework imports); all LLM coupling in `PydanticAIBackend`

---

## Design Sketch: Tracing Integration (Phoenix Arize) — Superseded

**Status**: Superseded by "Unified Executor & Agent Platform Sketch (2026-04-24)" Phase D. The Phoenix wiring details below remain valid reference material for implementation.

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
