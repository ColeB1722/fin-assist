# Manual Testing Checklist

**When to run**: Before merging a change that touches CLI commands, server lifecycle, approval widget, chat loop, agent configuration, or the Executor/streaming path. Run the full suite before a big refactor to establish a baseline.

**Purpose**: Verify CLI integration end-to-end in ways unit tests can't. Designed so an AI agent can run all non-interactive tests autonomously, leaving only TTY-dependent tests for the human.

> All commands shown as `fin` can also be invoked as `fin-assist`.
>
> **Architecture note**: `shell` and `default` are TOML config entries (`[agents.shell]`, `[agents.default]`) consumed by a single `AgentSpec` class. No per-agent Python subclasses. CLI and UX are unchanged from the user's perspective; what differs is how agents are defined.
>
> **Currently-implemented slash commands** in the REPL: `/exit`, `/help`, `/sessions`. Anything else will print `Unknown command: <x>`.

---

## Part 1 — Automated Tests (Non-Interactive)

An AI agent can run these from a terminal, verify output, and debug failures. No TTY interaction required.

> If any of these fail, fix before moving to Part 2.

### 1a. Server Lifecycle

Run these in order — each depends on the server state left by the previous test.

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

### 1b. Agent Listing

| # | Test | Command | Expected |
|---|------|---------|----------|
| A1 | List agents (auto-start) | `fin agents` (hub stopped) | Auto-starts server; prints `default` and `shell` agent cards with capability chips from `serving_modes` (`default`: `do | talk`; `shell`: `do | requires approval`) |
| A2 | List agents (reuse) | `fin agents` (hub up) | Same output, no restart — `ensure_server_running` short-circuits on healthy hub |

> **Debug**: Auto-start failures → run `fin start` manually to see logs. Card rendering → `cli/display.py`.

### 1c. One-Shot Dispatch

| # | Test | Command | Expected |
|---|------|---------|----------|
| A4 | Do default one-shot | `fin do default "hello"` | Text panel with response, no approval widget |
| A5 | Default agent shortcut | `fin do "hello"` (no agent arg) | Same as A4 — resolves to `[agents.default]` |
| A13 | Unknown agent | `fin do nonexistent "hi"` | `Unknown agent 'nonexistent'. Available: default, shell`, exit 1 |

> **Debug**: Dispatch failures → hub logs (`~/.local/share/fin/hub.log`). Empty response → check LLM credentials and `Executor` wiring.

### 1d. Serving Mode Validation

| # | Test | Command | Expected |
|---|------|---------|----------|
| E2 | Shell rejects talk | `fin talk shell` | `Agent 'shell' does not support multi-turn (talk) mode. Available modes: do`, exit 1 |
| E3 | Default supports do | `fin do default "hello"` | Works — `default.serving_modes = ["do", "talk"]` |

> E1 (`fin do shell …`) requires the approval widget — tested interactively in Part 2a. E4 (`fin talk default`) enters the REPL — tested interactively in Part 2b.

> **Debug**: Validation bypassed → check `_do_command` / `_talk_command` in `cli/main.py`.

### 1e. Credentials / Auth-Required

> Requires temporarily removing credentials. Run in a subshell or restore after.

| # | Test | Setup | Command | Expected |
|---|------|-------|---------|----------|
| F1 | Missing API key | Unset `ANTHROPIC_API_KEY` (and other configured provider env vars) | `fin do default "hello"` | Yellow "Authentication required" panel listing missing providers and env-var hints; exit 1 |
| F3 | Recovery | Restore the env var, repeat F1 | `fin do default "hello"` | Normal response |

> F2 (talk mode, missing key) enters the REPL — tested interactively in Part 2b.

> **Debug**: Auth panel not appearing → check `MissingCredentialsError` propagation and `render_auth_required` in `display.py`.

---

## Part 2 — Interactive Tests (Requires TTY)

These require keyboard input — arrow keys, text entry, or REPL interaction. Human-run only.

> **Prerequisite**: All of Part 1 must pass before starting Part 2.

### 2a. Approval Widget (`fin do shell`)

`shell` agent has `requires_approval=true`. Widget is `ChoiceInput` — arrow-key navigation between Execute/Cancel, Enter confirms. No text input.

| # | Test | Action | Expected |
|---|------|--------|----------|
| A3 | Do shell | `fin do shell list files` | "Generated Command" panel, then approval widget (Execute/Cancel) |
| E1 | Shell supports do | `fin do shell list files` | Same command as A3 — verifies serving mode allows `do` for `shell` (command reaches approval, not rejected by mode check) |
| B1 | Execute (default) | `fin do shell "echo hi"`, press Enter immediately | Execute is the default selection; command runs, exit 0 |
| B2 | Execute (navigate) | Arrow-key to Execute (already there), press Enter | Same as B1 |
| B3 | Cancel | Arrow-down to Cancel, press Enter | `[yellow]Cancelled.[/yellow]`, no execution, exit 0 |
| B4 | Ctrl+C | During prompt | Cancels (same as B3), exits cleanly |
| B5 | Ctrl+D | During prompt | Cancels (same as B3), exits cleanly |
| B6 | Escape | During prompt | Cancels (same as B3), exits cleanly |
| B7 | No text input surface | Observe | Selection-only; no text field, no completions |

> **Debug**: Widget issues → `cli/interaction/approve.py` or `handle_post_response` approval wiring.

### 2b. REPL (`fin talk <agent>`)

Tests the full chat loop with FinPrompt, streaming, session persistence, and resume.

> Run C1 and C2 first to establish a baseline.

| # | Test | Action | Expected |
|---|------|--------|----------|
| A6 | Default agent shortcut (talk) | `fin talk` (no agent arg) | Enters REPL as `default` agent |
| E4 | Default supports talk | `fin talk default` | Works, enters REPL — verifies serving mode allows `talk` for `default` |
| C1 | Basic chat (streaming) | `fin talk default`, type a message, Enter | Response streams progressively via `Live` + Markdown; final panel rendered |
| C2 | Exit with /exit | Type `/exit` (after at least one turn) | Chat ends, `[dim]Session saved: <slug>[/dim]` where `<slug>` is a coolname (e.g. `swift-harbor`) |
| C3 | Unknown slash command | Type `/bad` | `[yellow]Unknown command: /bad[/yellow]`, then `Type /help for available commands` |
| C4 | Empty input | Press Enter with nothing typed | No message sent, prompt returns |
| C5 | Multi-turn context | Send 2+ messages referencing earlier turns | Context preserved — replies should acknowledge prior content |
| C6 | Ctrl+C exits | Press Ctrl+C at prompt | `[dim]Exiting chat[/dim]`, chat loop ends |
| C7 | Ctrl+D exits | Press Ctrl+D at prompt | Same as C6 |
| C8 | Exit without chatting | `/exit` immediately after starting `talk` (no turns sent) | Chat ends, **no** `Session saved` message (nothing to save) |
| C9 | Session file exists | After C2, check `~/.local/share/fin/sessions/default/<slug>.json` | File exists, JSON with `context_id` and metadata |
| C10 | Resume session | `fin talk default --resume <slug>` (use slug from C2) | Chat resumes; prior context is in history; no new `Session saved` message on exit |
| C11 | Resume nonexistent | `fin talk default --resume ghost-banana` | `Error: Session ghost-banana not found`, exit 1 |
| C12 | List sessions (--list) | `fin talk default --list` | Lists saved sessions for `default`: `  <slug>  (context: <cid[:8]>...)`. Or `No sessions for default` if empty. |
| C13 | Initial message | `fin talk default "what time is it"` | First turn auto-sent, response streams, then enters REPL for follow-up |
| C14 | `/sessions` slash command | Inside REPL, type `/sessions` | Lists saved sessions for the current agent (same format as `--list`) |
| C15 | `/help` slash command | Inside REPL, type `/help` | Prints available slash commands |
| C16 | `--show-thinking` | `fin talk default --show-thinking`, chat once | Thinking blocks (if the model emits them) appear in the output |
| F2 | Talk mode, missing key | Unset `ANTHROPIC_API_KEY`, then `fin talk default`, send one message | Yellow "Authentication required" panel; then `[dim]Fix credentials and try again.[/dim]`; chat loop exits |

> **Debug**: REPL issues → `cli/interaction/chat.py`, `FinPrompt`. Streaming issues → `_PydanticAIStreamHandle` in `agents/backend.py`. Session issues → session persistence code.

### 2c. Prompt Completions & History

Tests FinPrompt features: fuzzy slash completion and persistent history. Run after C1/C2 confirm the basic REPL works.

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

> **Debug**: Completion issues → `cli/interaction/prompt.py` completion config. History issues → `FileHistory` wiring in same file.

> **Note**: Slash commands that used to be planned (`/quit`, `/q`, `/switch`) do **not** exist. Don't test them.

---

## Not Yet Implemented

### Chunk G — Context Injection for `do`

*Planned for Step 7 of the config-driven redesign; do not run until the flags exist.*

> **Status**: Underlying `ContextProvider` classes are built and unit-tested in `src/fin_assist/context/`, but the `do` parser has no `--file`, `--git-diff`, or `--git-log` flags. See `handoff.md`.

| # | Test | Command | Expected |
|---|------|---------|----------|
| G1 | File context | `fin do shell "describe this file" --file pyproject.toml` | Response references file contents |
| G2 | Git diff context | `fin do default "review these changes" --git-diff` | Response references `git diff` |
| G3 | Git log context | `fin do default "summarize recent work" --git-log` | Response references recent commits |
| G4 | Multiple flags | `fin do default "full context" --git-diff --git-log` | Both diff and log included |
| G5 | Missing file | `fin do default "describe" --file nonexistent.txt` | Warning about missing file; command still runs |

### Chunk H — `@`-Completion in Talk

*Planned for Step 8.*

> **Status**: No `@`-trigger logic exists in `cli/interaction/prompt.py`. See `handoff.md`.

| # | Test | Action | Expected |
|---|------|--------|----------|
| H1 | `@` trigger | Type `@` | Shows context-type options (`file:`, `git:`, `history:`) |
| H2 | `@file:` completion | Type `@file:` + partial path + Tab | Shows matching files |
| H3 | `@git:` completion | Type `@git:` + Tab | Shows git context options (`diff`, `log`, `status`) |
| H4 | `@history:` completion | Type `@history:` + Tab | Shows recent shell history |

---

## Running Order

```
Part 1 (Automated) — agent runs these first
┌──────────────────────────────────────────────┐
│ 1a. Server Lifecycle (A7-A15)                │
│ 1b. Agent Listing (A1, A2)                   │
│ 1c. One-Shot Dispatch (A4, A5, A13)          │
│ 1d. Serving Mode Validation (E2, E3)         │
│ 1e. Credentials (F1, F3)                     │
└──────────────────┬───────────────────────────┘
                   │ all pass
                   ▼
Part 2 (Interactive) — human at TTY
┌──────────────────────────────────────────────┐
│ 2a. Approval Widget (A3, E1, B1-B7)          │
│                                              │
│ 2b. REPL (A6, E4, C1-C16, F2)               │
│     │                                        │
│     └── 2c. Prompt Completions (D1-D8)       │
│         (after C1/C2 confirm REPL works)     │
└──────────────────────────────────────────────┘

Chunks G and H are NOT YET IMPLEMENTED — skip.
```

---

## Pre-Refactor Smoke Set

Before a big refactor, run the minimum set most likely to catch regressions:

**Automated** (agent runs): A1, A4, A5, A7-A15, E2, E3, F1, F3

**Interactive** (human runs):
- Approval: B1, B3, B4, B6 (Enter-default, Cancel, and two cancel-binding variants)
- REPL: C1, C5, C10, C11, C13 (streaming, multi-turn, resume, resume-missing, initial-message)
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
- `fin do "prompt"` / `fin talk` (no agent arg) → `[agents.default]`.
- `shell.serving_modes = ["do"]` — no talk mode.
- `default.serving_modes = ["do", "talk"]`.
- `fin serve` runs the hub in the foreground (distinct from `fin start` which daemonizes). Useful for development; see A15.
