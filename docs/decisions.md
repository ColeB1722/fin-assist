# Design Decisions

The "why" behind structural choices. New decisions go here when they shape the platform's contracts; small implementation choices stay in code comments or commit messages.

## Architecture

| Decision | Choice | Rationale |
|----------|--------|-----------|
| A2A SDK | a2a-sdk v1.0 (Google) | Official SDK; fasta2a abandoned; v1.0 supports JSON-RPC, REST, gRPC from a single protobuf schema |
| Multi-path routing | N agents, N agent cards, one server | True A2A compliance, enables agent-to-agent workflows |
| Parent ASGI framework | FastAPI | a2a-sdk route factories produce FastAPI-compatible routes; consistent framework across sub-apps |
| Config-driven agents | TOML config defines agent behavior | Adding agents = editing TOML, not writing Python classes |
| Spec/backend split | `AgentSpec` (pure config) + `AgentBackend` protocol (framework glue) | Isolates pydantic-ai to one file (`agents/backend.py`); spec is trivially testable and transport-ready; backend swap touches one module |
| No ABC for specs | Single `AgentSpec` class, no `BaseAgent` ABC | Only one implementation exists; `Protocol` for DI/mocking if needed later; multi-language agents use A2A protocol, not Python inheritance |
| Executor over Worker/Broker | `Executor(AgentExecutor)` + `DefaultRequestHandler` | a2a-sdk pattern; no broker needed; `TaskUpdater` for state transitions; Executor depends on `AgentBackend` protocol, not pydantic-ai directly |
| Agent card metadata | `AgentExtension(uri="fin_assist:meta", params=Struct)` | Proper a2a-sdk extension; replaces earlier `Skill(id="fin_assist:meta")` hack |
| Streaming | Token-by-token via `TaskUpdater.add_artifact(append=True)` + SSE | Progressive output via `SendStreamingMessage`; Rich `Live` rendering on client |
| Task storage | `InMemoryTaskStore` (ephemeral) | a2a-sdk managed; tasks lost on server restart; acceptable for personal local-first tool |
| Conversation storage | SQLite `ContextStore` | Persists pydantic-ai message history across tasks; `context_id` for threading |
| `serving_modes` over `multi_turn` | `ServingMode = Literal["do", "talk"]` | More expressive than boolean; declares which CLI modes an agent supports |
| Default agent shortcut | `fin do "prompt"` → `[general] default_agent` | Reduces friction for common case; agent arg optional |
| Context for `do` / `talk` | `@`-completion in FinPrompt | Replaces `--file`/`--git-diff` CLI flags; context injected inline before sending |
| Local-only server | Bind 127.0.0.1 | Personal tool, no network exposure; future opt-in |
| CLI as dev tool, not product | CLI is hub system ops + verification-only dev REPL; end-user use happens through inbound protocol surfaces | Resolved 2026-05-17 (platform stance Q3). See [§Platform stance](#platform-stance) below |
| UI metadata transport | Static in agent card, dynamic in artifacts | Agent card declares capabilities; per-response hints in artifact metadata |
| Testing approach | Deep evals + CI | LLM-as-judge by default, pytest-compatible, post-merge regression checks |

## Platform stance

**Date:** resolved 2026-05-17 across five working sessions; the working-notes archaeology lives in git history (`git log -- docs/platform-stance.md`). The stance answers a cluster of strategic questions about fin-assist's relationship to the broader agent ecosystem — what protocol surfaces the hub exposes, what the CLI is, and how new inbound consumers relate to the hub architecturally.

**Core stance:** *"I want a system that I can, with a reasonable amount of work, integrate with arbitrary systems in order to make that system agent-enhanced. […] I am more interested conceptually with fin as a platform, vs thinking through the user experience."*

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Integration direction (Q1) | Both inbound and outbound; no sequencing implied | Maps to protocol *roles* (inbound surfaces vs outbound surfaces), not competing product directions. Each surface grows when its motivating consumer or peer exists |
| Protocol surfaces (Q2) | Three inbound (A2A-server existing; MCP-server + ACP-server committed), three outbound (MCP-client existing; A2A-client + ACP-client committed) | A2A, MCP, ACP are sibling protocols at different layers (agent ↔ agent, agent ↔ tool, client ↔ agent), not substitutes. ACP-client bundled with ACP-server architecturally because the protocol library and session model are shared |
| CLI stance (Q3) | Dev tool only — hub system ops + verification-only dev REPL | Collapses the previous "two deliverables" framing in `architecture.md` into one deliverable (the hub) with multiple inbound integration surfaces. The CLI talks to the hub via plain HTTP for hub-level routes and via A2A for agent-traffic messaging in the dev REPL — for that A2A traffic specifically, it is one consumer among many. See *Deliverables: Hub vs CLI* in `architecture.md` |
| Workspace split (Q4) | Deferred indefinitely; #132's BFF framing rejected on the merits | New inbound consumers are **protocol peers**, not BFF clients. The protocol *is* the boundary; no BFF layer is needed. Hub-CLI import-linter firewall stays in CI for hygiene; no forcing function expected to fire. See [#128](https://github.com/ColeB1722/fin-assist/issues/128) for the deferred workspace-split design thinking |
| Surface sequencing (Q5) | ACP-server first ([#162](https://github.com/ColeB1722/fin-assist/issues/162)) | Dogfooding-as-platform-verification: the platform claim is unverified until a non-fin client drives the hub through a fixed external protocol contract. Minimal first cut: session lifecycle, streaming text, permission round-trip. See *Inbound protocol surfaces* in `architecture.md` |
| Dev-REPL feature line (Q7) | **Verification-only** | The REPL exists to verify that an agent works after `/connect` + config. Anything beyond verification (conversation polish, session switching, multi-line edit, rich tool_result rendering, `$EDITOR` integration, splash screens) is out. Examples list below is the calibration |

### Verification-only dev REPL — the feature line

The principle is intentionally tight: the dev REPL is not a "small chat client" or a "developer-facing daily-driver." It is the smallest thing that lets a developer confirm a newly configured agent responds correctly and that a skill loads and dispatches. End-user conversational use happens through inbound protocol surfaces — MCP-host clients, ACP-speaking editors, future A2A clients.

**What stays:**

- **Hub system operations** — `fin start` / `stop` / `status` / `health`, `/connect`, `fin pkg` ([#146](https://github.com/ColeB1722/fin-assist/issues/146) when it ships).
- **Basic A2A round-trip** — send a prompt, receive a response, see streaming tokens, see tool calls and approval prompts.
- **`@`-completion** (`@file:` / `@git:` / `@history:` / `@env:`) — verifying a context-consuming agent *requires* injecting context. Removing completion would make some agents impossible to test from the dev REPL.
- **Positional grammar `fin do <agent> <skill> [prompt]`** — verification is a per-skill operation. The two-turn `entry_prompt` semantics fix is a real bug regardless of CLI shape. (The rest of [#137](https://github.com/ColeB1722/fin-assist/issues/137) — `--workflow` mode flag, mode-resolution table, listing annotations — drops.)
- **Core slash commands** — `/help`, `/exit`, `/connect`, `/agents`, `/skill:<name>`.
- **Session persistence + `--resume`** — out-of-REPL operations only.

**What's explicitly out (non-exhaustive):**

| Out-of-scope | Issue | Why |
|---|---|---|
| Interactive REPL session switching | [#64](https://github.com/ColeB1722/fin-assist/issues/64) | Conversation management, not verification |
| Splash screen / startup banner | [#67](https://github.com/ColeB1722/fin-assist/issues/67) (closed) | Product polish |
| Richer tool_result rendering | [#91](https://github.com/ColeB1722/fin-assist/issues/91) (closed) | Visualization, not verification |
| `fin do` vs `fin prompt` semantic split | [#94](https://github.com/ColeB1722/fin-assist/issues/94) (closed) | Verification needs one entry point |
| `/spec` verbose agent ASCII art | [#95](https://github.com/ColeB1722/fin-assist/issues/95) (closed) | Product polish |
| `$EDITOR` integration via `--edit` | [#97](https://github.com/ColeB1722/fin-assist/issues/97) (closed) | Multi-line composition is a real client's job |
| Telegram / iOS / other bespoke clients | [#133](https://github.com/ColeB1722/fin-assist/issues/133), [#134](https://github.com/ColeB1722/fin-assist/issues/134) (both closed) | Moot under Q3 |

**Drift-prevention contract:** When a new CLI feature is proposed, the principle ("REPL exists to verify an agent works after `/connect` + config; anything beyond verification is out") is the rule; the table above is the calibration. If a contributor argues their feature is verification-shape, the discussion happens against this concrete reference rather than vibes. The examples list is intentionally non-exhaustive — new exclusions are added as they come up.

**ACP-server is the forcing function.** Once a real editor can drive fin, the exclusion list becomes obvious because the editor will do most of these things better. Q7 is a first cut; if ACP-server work ([#162](https://github.com/ColeB1722/fin-assist/issues/162)) reveals something the verification-only framing got wrong, file a follow-up against this resolution rather than re-litigating the principle wholesale.

## Windows

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Install method | `uv tool install -e .` (not Scoop) | Scoop distributes pre-built binaries; Python tools use `uv tool install` instead. Pure-Python projects (FastAPI, Textual, pydantic-ai) use pip/uv only — no Scoop manifest precedent |
| Scoop manifest | Deferred post-1.0 | Requires PyInstaller/Nuitka build pipeline + signing. Not worth the effort until there's a pre-built binary story |
| Default data dir | `%LOCALAPPDATA%\fin` | Platform convention; matches Chrome, VS Code, etc. `FIN_DATA_DIR` override still works |
| `fin start` detachment | `CREATE_NO_WINDOW` + `STARTUPINFO(SW_HIDE)` | See [§`fin start` background spawn on Windows](#fin-start-background-spawn-on-windows) below |
| PID file locking | `filelock` library + sidecar `.lock` file | `fcntl` is Unix-only; `filelock` wraps `fcntl` on Unix and `msvcrt.locking` on Windows. `msvcrt.locking` locks byte ranges of the file you open (preventing a separate write to the PID payload) — so we lock a sidecar `hub.pid.lock` and write the PID to `hub.pid` separately |

## Skills

See [`docs/skills.md`](skills.md#design-decisions) for skill-specific design decisions (tool gating, agent-level policies, SKILL.md format, etc.).

## Tracing

See [`docs/tracing.md`](tracing.md) for tracing-specific decisions (CLI-side trace ID joining, HITL pause/resume continuity, attribute hygiene, noise suppression).

## Open questions

Decisions deferred until the relevant work picks them up.

| Question | Status | Notes |
|----------|--------|-------|
| `AgentBackend` protocol shape | Open — [#80](https://github.com/ColeB1722/fin-assist/issues/80) | Protocol currently reflects pydantic-ai shape in ~5 of 6 methods. Revisit when a second backend is actually needed |
| External agent federation | Open — deferred | Hub can register external A2A servers (any language) in discovery; deferred until a real external agent exists to validate config schema. See [§External agent federation](#external-agent-federation) below |
| gRPC transport | Open — deferred | A2A protocol supports gRPC; a2a-sdk v1.0 supports it; not yet used by fin-assist |
| Non-blocking agents | Open | `SendMessage` with `blocking: false`; client-side polling not yet wired |
| Deep evals criteria | Open | Must/must-not/should per agent, LLM-as-judge default — designed when eval harness is built (v0.3) |
| MCP discovery caching | Deferred to v0.1.2 — [#84](https://github.com/ColeB1722/fin-assist/issues/84) | v0.1.1 ships eager connect with no caching. v0.1.2 adds 60s TTL + `listChanged` invalidation. See §MCP integration below. |

## MCP integration

**ToolDefinition carries only `approval_policy`.** Source-specific metadata (MCP `ToolAnnotations`, future file-based `@tool` decorators) is translated by the provider during `discover()` into the platform's `ApprovalPolicy` type. There is no `annotations` field on `ToolDefinition`.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Dependency | `mcp>=1.26.0` in `pyproject.toml` dependencies (not extra) | Direct dependency; needed at runtime for stdio/SSE client sessions |
| Namespacing | `mcp.<server>.<tool>` with dot-safe identifiers | Collision on full name = startup error; optional `alias` in config |
| Discovery | Eager connect at startup (`discover()` triggers `_connect()`) | Reliability > responsiveness; session stays alive for tool calls |
| Approval mapping (#141) | `readOnlyHint=true` → `never`; `destructiveHint=true` → `always`; no annotations → `always` | Conservative defaults match MCP spec; agent-level `tool_policies` still override |
| Caching | None in v0.1.1 | Ecosystem consensus is that discovery caching is standard, but v0.1.1 defers to keep change focused. See open questions table above. |
| Config schema | `[mcp.servers.<name>]` with `transport`, `command`/`args`, `url`, `alias`, `enabled`, `env`, `timeout`, `headers` | Covers stdio + SSE; forward-compat with auth headers |
| Timeout | 30s default per `tools/call`, per-server configurable | Ecosystem consensus (OpenAI SDK, MCP spec RFC #1492); `asyncio.timeout()` implementation |

## External agent federation

The hub currently only mounts **internal** agents — Python `AgentSpec` instances running in-process as A2A sub-apps. The A2A protocol is language-agnostic, so the hub *can* also register **external** agents: any process that serves the two A2A endpoints (`GET /.well-known/agent-card.json` + `POST /` JSON-RPC), regardless of implementation language.

**Two pluggability levels:**

| Level | What | Current support |
|-------|------|-----------------|
| Config plugins | New agent behaviors via TOML (different prompt, output type, serving modes) | Done |
| Process plugins | External A2A servers in any language, registered with the hub via URL | Not yet |

**Federation model — hub as registry, not proxy.** External agents register their URL in config. The hub lists them in the discovery endpoint (`GET /agents`) alongside internal agents. Clients talk to external agents directly — the hub is a directory service, not a proxy. This aligns with A2A's design: agent cards already have a `url` field.

**Config schema (when implemented):**

```toml
[agents.myrust]
mode = "external"                          # new field; "internal" is default
url = "http://127.0.0.1:5001"

[agents.claude-code]
mode = "external"
url = "http://127.0.0.1:5002"
```

**What changes when implemented:**

1. `AgentConfig` gets `mode: Literal["internal", "external"]` and `url: str | None`
2. `create_hub_app()` distinguishes internal (mount sub-app) vs external (register URL only)
3. Discovery endpoint already returns agent URLs — minimal change
4. Client, CLI, streaming all work as-is — they're protocol-native

**What external agents don't get:** `ContextStore`, `CredentialStore`, `ContextProviders` are in-process Python services. External agents manage their own credentials, context, and conversation history. This is the correct boundary: shared services are an implementation convenience for internal agents, not a protocol requirement.

**Why defer:** No external agents exist yet. The change is small (~50 lines) but designing the schema without a real external process to validate against risks over-fitting. Once a toy Rust/Gleam agent exists, the schema will be obvious.

## `fin start` background spawn on Windows

`fin start` spawns `fin-assist serve` as a detached background process so the hub keeps running after the terminal closes.  Windows does not have a `daemon()` syscall — the closest equivalent is choosing the right combination of `CreateProcess` flags and `STARTUPINFO` fields.  Getting that combination wrong manifests in three different failure modes that we worked through:

1. **Hang at startup on EDR-protected machines** — observed on the corporate laptop, not on the personal machine.  Manifested as `fin start` timing out after 10s with an empty `hub.log`.
2. **Visible console window** — the spawned process briefly flashed a terminal window, then either stayed open or closed without detaching.
3. **Console window stays open and kills the hub when closed** — child was sharing the parent's console.

### What we tried

| Approach | Outcome |
|----------|---------|
| `start_new_session=True` (Unix idiom; maps to `CREATE_NEW_PROCESS_GROUP` on Windows) | EDR blocks `CREATE_NEW_PROCESS_GROUP` silently; spawn hangs |
| `DETACHED_PROCESS \| CREATE_NO_WINDOW` | Worked on personal Windows; on corporate machine sometimes spawned a visible console (some library calls `AllocConsole` when no console exists) |
| Swap `sys.executable` from `python.exe` to `pythonw.exe` | `pythonw.exe` failed to start on `uv tool install`-managed corporate installs — process exited immediately, empty log |
| **`CREATE_NO_WINDOW` + `STARTUPINFO(STARTF_USESHOWWINDOW, SW_HIDE)`, no `DETACHED_PROCESS`, no `CREATE_NEW_PROCESS_GROUP`, no `pythonw.exe`** | Works on personal + corporate; no visible window; child survives terminal closure |

### Why the working combination works

`CREATE_NO_WINDOW` tells `CreateProcess` to allocate a console session for the child *without* a visible window.  The console handles are valid (so libraries that probe `GetConsoleWindow()` succeed without calling `AllocConsole`), but there is no window to show.

`STARTUPINFO(STARTF_USESHOWWINDOW, SW_HIDE)` is a belt-and-suspenders hint: if any code path *does* create a window, the OS is instructed to hide it on first display.

We deliberately drop `DETACHED_PROCESS`:

* Per [the Python docs and CPython issue 41619](https://bugs.python.org/issue41619), `CREATE_NO_WINDOW` and `DETACHED_PROCESS` are mutually exclusive — combining them is documented as undefined.
* `DETACHED_PROCESS` means "no console at all," which means downstream code that calls `GetStdHandle` gets `NULL` handles; some libraries respond by calling `AllocConsole` and the window pops up anyway.

We deliberately drop `CREATE_NEW_PROCESS_GROUP`: it was observed to make the spawn hang or be killed silently on corporate EDR-protected machines.  The child survives terminal closure without it because (a) `stdin` is `DEVNULL` (no `Ctrl+C` propagation path), and (b) the windowless console is a separate session from the parent's interactive console.

We deliberately do not swap to `pythonw.exe`: the GUI-subsystem interpreter is the conventional choice for hidden-console daemons, but on `uv tool install`-managed Windows installs it fails to start on at least one corporate machine.  `python.exe` + `CREATE_NO_WINDOW` achieves the same hidden-console effect without that risk.

### Regression tests

`tests/test_cli/test_server.py::TestSpawnServe::test_windows_uses_hidden_console_session` asserts the exact flag combination and runs on Windows CI (`runs-on: windows-latest` in `.github/workflows/ci.yml`).  `test_unix_uses_start_new_session` asserts the Unix path stays clean.  Together they prevent silent regression of either platform's spawn semantics.

## CI required checks

**Date:** 2026-05-17 (PR #159)

**Problem:** the `main` branch ruleset required `format`, `lint`, and `test` as status checks while `.github/workflows/ci.yml` declared `paths-ignore: [docs/**, *.md]`.  Documentation-only PRs (anything that touched only those paths) skipped the entire workflow.  Skipped workflows don't report their status — so the required checks remained perpetually pending and the PR was unmergeable.

This is the well-known "[required status check deadlock](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-status-checks-to-pass-before-merging)" problem.  Surfaced when the recovery PR #159 (handoff.md doc update missed from #152) hit it.

**Patterns considered:**

| Pattern | Notes |
|---|---|
| Duplicate "skip" workflow with same job names (GitHub's old recommended fix) | Doesn't scale past one required check; GitHub removed it from their own docs; creates double-execution edge cases |
| Drop `paths-ignore` entirely | Simplest. ~6–9 min cached CI per doc PR is acceptable for this project's size. No conditional logic. Works without aggregation jobs. |
| Single aggregation "sentinel" job using `if: contains(needs.*.result, 'failure')` | The "skipped = success" pattern.  One required check (`ci-required`) that fails only when an upstream job fails or is cancelled.  When upstream jobs run and succeed, the sentinel is skipped (because of its `if:` guard) and reports success.  When upstream jobs would be skipped (path filtering, etc.), the sentinel is also skipped and reports success.  Recommended by [DevOps Directive's 2025 writeup](https://devopsdirective.com/posts/2025/08/github-actions-required-checks-for-conditional-jobs/) and the consensus on [github/docs#21865](https://github.com/github/docs/issues/21865). |

**Choice:** both — drop `paths-ignore` *and* add the `ci-required` sentinel.

`paths-ignore` was solving a problem (don't waste CI minutes on doc PRs) that is real but cheap at this project's scale.  Removing it makes the immediate deadlock impossible.  Adding the sentinel makes it safe to *reintroduce* path-conditional jobs later (e.g., when `test-windows` runtime becomes painful and we want to skip it on doc-only changes) without re-creating the deadlock.

**Ruleset update:** the `main` ruleset's required checks were changed from `[format, lint, test]` to `[ci-required]`.  Future required checks should be added by listing them in `ci-required.needs`, not by adding them to the ruleset.  The ruleset is now agnostic to the workflow's internal job structure — one less coupling point between repo settings (managed via the GitHub API/UI) and code (managed via PRs).

**When adding a new job to `ci.yml`:** add it to `ci-required.needs`.  No other CI plumbing changes required.

### Selective execution (follow-up, 2026-05-17)

PR #159 deferred selective execution with the line *"adding the sentinel makes it safe to reintroduce path-conditional jobs later."*  PR #161 surfaced that "later" — a handoff-only PR ran the full ~6–9 min suite (plus a Windows VM), which is the predictable friction of dropping `paths-ignore` wholesale.

**Approach:** the `dorny/paths-filter` Pattern B from the [costops.dev writeup](https://costops.dev/guides/docs-changes-trigger-full-ci) and [dorny/paths-filter's README](https://github.com/dorny/paths-filter).  A small `changes` job runs on every PR and emits a `code` boolean; the expensive jobs (`format`, `lint`, `typecheck`, `test`, `test-windows`) gate on `if: needs.changes.outputs.code == 'true'`.  When the PR only touched markdown/docs, all five skip — and skipped jobs report success for required-check purposes ([GitHub docs](https://docs.github.com/en/actions/how-tos/managing-workflow-runs-and-deployments/managing-workflow-runs/skipping-workflow-runs)).  The `ci-required` sentinel still gates the merge; the deadlock from before remains impossible because the *workflow itself* always runs.

**Filter design:** uses `predicate-quantifier: 'every'` with a positive `**` pattern plus negations for prose-only paths (`**.md`, `docs/**`, `.github/ISSUE_TEMPLATE/**`, `.github/PULL_REQUEST_TEMPLATE.md`).  Everything else — lockfiles, `pyproject.toml`, `justfile`, `flake.*`, `devenv.*`, `.github/workflows/**` — counts as code so environment and CI changes still exercise the full suite.  The `every` quantifier is the [recommended workaround](https://github.com/dorny/paths-filter/issues/184) for picomatch's known bugs with complex negation extglobs.

**Why not workflow-level `paths-ignore`:** would re-create the exact deadlock PR #159 fixed.  Workflow-level filtering = skipped workflow = pending check = unmergeable.  Job-level `if:` filtering is the only pattern that's both selective *and* compatible with required checks.

**Why not commit-message `[skip ci]`:** same deadlock, plus manual.

**When adjusting the filter:** edit the `filters.code` block in `.github/workflows/ci.yml`.  If a new top-level path is added that should *not* run CI when changed alone (e.g. a future `RFCs/` directory), add a negation line.  When in doubt, leave it counting as code — under-running is worse than over-running.
