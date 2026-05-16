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
| CLI-first development | CLI before TUI | Faster iteration on hub + agent behavior; TUI becomes a client later |
| UI metadata transport | Static in agent card, dynamic in artifacts | Agent card declares capabilities; per-response hints in artifact metadata |
| Testing approach | Deep evals + CI | LLM-as-judge by default, pytest-compatible, post-merge regression checks |

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
