# Manual Testing Checklist

**When to run**: Before merging a change that touches CLI commands, server lifecycle, approval widget, chat loop, agent configuration, or the Executor/streaming path. Run the full A+B before a big refactor to establish a baseline.

**Purpose**: Verify CLI integration end-to-end in ways unit tests can't. Designed for parallel testing and pick-up-where-you-left-off.

> All commands shown as `fin` can also be invoked as `fin-assist`.
>
> **Architecture note**: `shell` and `default` are TOML config entries (`[agents.shell]`, `[agents.default]`) consumed by a single `AgentSpec` class. No per-agent Python subclasses. CLI and UX are unchanged from the user's perspective; what differs is how agents are defined.
>
> **Currently-implemented slash commands** in the REPL: `/exit`, `/help`, `/sessions`. Anything else will print `Unknown command: <x>`.

---

## Chunk A — Basic CLI and Server

*Tests the foundation: server lifecycle, start/stop/status, auto-start, basic agent dispatch.*

> If this breaks, fix before touching anything else.

| # | Test | Command | Expected |
|---|------|---------|----------|
| A1 | List agents (auto-start) | `fin agents` (hub stopped) | Auto-starts server; prints `default` and `shell` agent cards, with metadata chips (`default`: `multi-turn`/no chips; `shell`: `one-shot`, `requires approval`) |
| A2 | List agents (reuse) | `fin agents` (hub up) | Same output, no restart — `ensure_server_running` short-circuits on healthy hub |
| A3 | Do shell | `fin do shell list files` | "Generated Command" panel, then approval widget (Execute/Cancel) |
| A4 | Do default one-shot | `fin do default "hello"` | Text panel with response, no approval widget |
| A5 | Default agent shortcut (do) | `fin do "hello"` (no agent arg) | Same as A4 — resolves to `[agents.default]` |
| A6 | Default agent shortcut (talk) | `fin talk` (no agent arg) | Enters REPL as `default` agent |
| A7 | Start server | `fin start` | `[dim]Hub running at http://127.0.0.1:4096[/dim]` |
| A8 | Start when running | `fin start` (already up) | Same message, no restart (idempotent) |
| A9 | Status when running | `fin status` (hub up) | `Hub running at http://127.0.0.1:4096, PID <n>` |
| A10 | Status when stopped | `fin status` (hub down) | `Hub is not running.` |
| A11 | Stop server | `fin stop` | `[dim]Hub stopped.[/dim]` |
| A12 | Stop when down | `fin stop` (already stopped) | `No running hub found (…)` error, exit code 1 |
| A13 | Unknown agent | `fin do nonexistent "hi"` | `Unknown agent 'nonexistent'. Available: default, shell`, exit 1 |
| A14 | Orphan-server detection | `fin status` after killing the hub process directly (bypassing `fin stop`) | `Hub running at …(PID file missing — orphaned server)` |
| A15 | Port already in use | `fin serve --port 4096` while hub is up | Remediation message suggesting a different port or stop, exit 1 |

**If A fails**: server startup, client connectivity, or basic dispatch broken. Fix before anything else.

---

## Chunk B — Approval Widget (`fin do shell`)

*Tests the arrow-key selection widget. `shell` agent has `requires_approval=true`.*

The widget is `ChoiceInput` — arrow-key navigation between Execute/Cancel, Enter confirms. No text input.

> Run B after A passes.

| # | Test | Action | Expected |
|---|------|--------|----------|
| B1 | Execute (default) | `fin do shell "echo hi"`, press Enter immediately | Execute is the default selection; command runs, exit 0 |
| B2 | Execute (navigate) | Arrow-key to Execute (already there), press Enter | Same as B1 |
| B3 | Cancel | Arrow-down to Cancel, press Enter | `[yellow]Cancelled.[/yellow]`, no execution, exit 0 |
| B4 | Ctrl+C | During prompt | Cancels (same as B3), exits cleanly |
| B5 | Ctrl+D | During prompt | Cancels (same as B3), exits cleanly |
| B6 | Escape | During prompt | Cancels (same as B3), exits cleanly |
| B7 | No text input surface | Observe | Selection-only; no text field, no completions |

**If B fails**: `cli/interaction/approve.py` or the `handle_post_response` approval wiring broken.

---

## Chunk C — REPL Loop (`fin talk <agent>`)

*Tests the full chat loop with FinPrompt, streaming, session persistence, and resume.*

> Run C after A passes.

| # | Test | Action | Expected |
|---|------|--------|----------|
| C1 | Basic chat (streaming) | `fin talk default`, type a message, Enter | Response streams progressively via `Live` + Markdown; final panel rendered |
| C2 | Exit with /exit | Type `/exit` (after at least one turn) | Chat ends, `[dim]Session saved: <slug>[/dim]` printed where `<slug>` is a coolname (e.g. `swift-harbor`) |
| C3 | Unknown slash command | Type `/bad` | `[yellow]Unknown command: /bad[/yellow]`, then `Type /help for available commands` |
| C4 | Empty input | Press Enter with nothing typed | No message sent, prompt returns |
| C5 | Multi-turn context | Send 2+ messages referencing earlier turns | Context preserved — replies should acknowledge prior content |
| C6 | Ctrl+C exits | Press Ctrl+C at prompt | `[dim]Exiting chat[/dim]`, chat loop ends. (Does **not** return to prompt — same behavior as Ctrl+D.) |
| C7 | Ctrl+D exits | Press Ctrl+D at prompt | Same as C6 |
| C8 | Exit without chatting | `/exit` immediately after starting `talk` (no turns sent) | Chat ends, **no** `Session saved` message (nothing to save) |
| C9 | Session file exists | After C2, check `~/.local/share/fin/sessions/default/<slug>.json` | File exists, JSON with `context_id` and metadata |
| C10 | Resume session | `fin talk default --resume <slug>` (use slug from C2) | Chat resumes; prior context is in history; no new `Session saved` message on exit (resumed sessions don't re-create the file) |
| C11 | Resume nonexistent | `fin talk default --resume ghost-banana` | `Error: Session ghost-banana not found`, exit 1 |
| C12 | List sessions (--list) | `fin talk default --list` | Lists saved sessions for `default`: `  <slug>  (context: <cid[:8]>...)`. Or `No sessions for default` if empty. |
| C13 | Initial message | `fin talk default "what time is it"` | First turn auto-sent, response streams, then enters REPL for follow-up |
| C14 | `/sessions` slash command | Inside REPL, type `/sessions` | Lists saved sessions for the current agent (same format as `--list`) |
| C15 | `/help` slash command | Inside REPL, type `/help` | Prints available slash commands |
| C16 | `--show-thinking` | `fin talk default --show-thinking`, chat once | Thinking blocks (if the model emits them) appear in the output |

**If C fails**: `cli/interaction/chat.py`, `FinPrompt`, session persistence, or streaming broken.

---

## Chunk D — FinPrompt Completions and History

*Tests the features prompt_toolkit + FinPrompt provide: fuzzy slash completion and persistent history.*

> Run D after C1/C2 confirm the basic REPL works.

| # | Test | Action | Expected |
|---|------|--------|----------|
| D1 | Slash trigger | Type `/` then Tab | Completion menu shows `/exit`, `/help`, `/sessions` + agent names (`default`, `shell`) |
| D2 | Fuzzy /exit | Type `/ex`, Tab | Completes to `/exit` |
| D3 | Fuzzy /help | Type `/he`, Tab | Completes to `/help` |
| D4 | Fuzzy /sessions | Type `/se`, Tab | Completes to `/sessions` |
| D5 | History up | Press Up arrow in an empty prompt | Previous input recalled |
| D6 | History down | Press Down after Up | Next/empty |
| D7 | History persists | Exit (`/exit`), re-launch `fin talk default`, press Up | Previous session's input available |
| D8 | History file | `cat ~/.local/share/fin/history` | File exists; format is prompt_toolkit `FileHistory` (entries prefixed with `+`, timestamp comments with `#`) — not bare lines |

**If D fails**: `cli/interaction/prompt.py` completion config or `FileHistory` wiring broken.

> **Note**: Slash commands that used to be planned (`/quit`, `/q`, `/switch`) do **not** exist. Don't test them.

---

## Chunk E — Serving Mode Validation

*Tests that `serving_modes` config is enforced by the CLI before any request is sent.*

| # | Test | Command | Expected |
|---|------|---------|----------|
| E1 | Shell supports do | `fin do shell list files` | Works — `shell.serving_modes = ["do"]` |
| E2 | Shell rejects talk | `fin talk shell` | `Agent 'shell' does not support multi-turn (talk) mode. Available modes: do`, exit 1 |
| E3 | Default supports do | `fin do default "hello"` | Works — `default.serving_modes = ["do", "talk"]` |
| E4 | Default supports talk | `fin talk default` | Works, enters REPL |

**If E fails**: validation in `_do_command` / `_talk_command` in `cli/main.py` broken.

---

## Chunk F — Credentials / Auth-Required Path

*Tests the graceful failure mode when API credentials are missing. Important to verify before any Executor change, since the AUTH_REQUIRED state transition is on the critical path.*

> Run F after A passes. Requires temporarily removing credentials — do this in a throwaway shell or be prepared to restore them.

| # | Test | Setup | Command | Expected |
|---|------|-------|---------|----------|
| F1 | Missing API key | Unset `ANTHROPIC_API_KEY` (and any other configured provider env vars) in the current shell | `fin do default "hello"` | Yellow "Authentication required" panel listing missing providers and env-var hints; exit 1 |
| F2 | Talk mode, missing key | Same unset | `fin talk default`, send one message | Panel as F1; then `[dim]Fix credentials and try again.[/dim]`; chat loop exits |
| F3 | Recovery | Restore the env var, repeat F1 | `fin do default "hello"` | Normal response |

**If F fails**: `MissingCredentialsError` not reaching the client, or `render_auth_required` / `display.py` broken.

---

## Chunk G — Context Injection for `do` (NOT YET IMPLEMENTED)

*Tests CLI flags for one-shot context injection. Planned for Step 7 of the config-driven redesign; do not run until the flags exist.*

> **Status**: The underlying `ContextProvider` classes are built and unit-tested in `src/fin_assist/context/`, but the `do` parser has no `--file`, `--git-diff`, or `--git-log` flags. See `handoff.md` → "ContextProviders — Parked State" and "Executor Loop Rework".

| # | Test | Command | Expected |
|---|------|---------|----------|
| G1 | File context | `fin do shell "describe this file" --file pyproject.toml` | Response references file contents |
| G2 | Git diff context | `fin do default "review these changes" --git-diff` | Response references `git diff` |
| G3 | Git log context | `fin do default "summarize recent work" --git-log` | Response references recent commits |
| G4 | Multiple flags | `fin do default "full context" --git-diff --git-log` | Both diff and log included |
| G5 | Missing file | `fin do default "describe" --file nonexistent.txt` | Warning about missing file; command still runs |

---

## Chunk H — `@`-Completion in Talk (NOT YET IMPLEMENTED)

*Tests `@`-triggered fuzzy completion in FinPrompt for context injection during chat. Planned for Step 8.*

> **Status**: No `@`-trigger logic exists in `cli/interaction/prompt.py`. See handoff.md, same entries as Chunk G.

| # | Test | Action | Expected |
|---|------|--------|----------|
| H1 | `@` trigger | Type `@` | Shows context-type options (`file:`, `git:`, `history:`) |
| H2 | `@file:` completion | Type `@file:` + partial path + Tab | Shows matching files |
| H3 | `@git:` completion | Type `@git:` + Tab | Shows git context options (`diff`, `log`, `status`) |
| H4 | `@history:` completion | Type `@history:` + Tab | Shows recent shell history |

---

## Running Order

```
A1-A15  →  Chunk A (blocks everything if broken)
            │
            ├── B1-B7   →  Chunk B
            │
            ├── C1-C16  →  Chunk C (run in parallel with B after A passes)
            │             │
            │             └── D1-D8  →  Chunk D (after C1/C2 work)
            │
            ├── E1-E4   →  Chunk E  (parallel with B/C after A)
            │
            └── F1-F3   →  Chunk F  (parallel with B/C/E after A)

Chunks G and H are NOT YET IMPLEMENTED — skip until Steps 7-8 land.
```

---

## Pre-Refactor Smoke Set

Before a big refactor (e.g. the Executor loop rework), run the **minimum set most likely to catch regressions**:

- **Chunk A**: all 12, plus A13-A15. Server lifecycle is subtle, not deeply covered by unit tests.
- **Chunk B**: B1, B3, B4, B6. Covers Enter-default, Cancel, and two cancel-binding variants.
- **Chunk C**: C1, C5, C10, C11, C13. Streaming, multi-turn context, resume, resume-missing, initial-message.
- **Chunk F**: F1, F3. Auth-required panel + recovery — high regression risk if Executor state transitions change.

The rest of C/D/E is largely redundant with unit tests or exercises prompt_toolkit behavior that doesn't depend on the refactor.

---

## If a Chunk Fails

1. Note test IDs and chunk.
2. File a bug or branch a fix.
3. A second session can work another chunk in parallel.

---

## Notes

- Server auto-starts on first `do`/`talk`/`agents` via `ensure_server_running` (`cli/server.py`).
- `fin stop` uses PID file; falls back to `/proc` scan for orphans. See A14.
- Session slugs are coolnames from `coolname.generate_slug(2)` — e.g. `swift-harbor`, not UUIDs.
- History file: `~/.local/share/fin/history`. Sessions dir: `~/.local/share/fin/sessions/<agent>/<slug>.json`.
- The "Session saved" message only prints when (a) at least one turn completed, AND (b) the session is not a resume.
- `fin do "prompt"` / `fin talk` (no agent arg) → `[agents.default]`.
- `shell.serving_modes = ["do"]` — no talk mode.
- `default.serving_modes = ["do", "talk"]`.
- `fin serve` runs the hub in the foreground (distinct from `fin start` which daemonizes). Useful for development; see A15.
