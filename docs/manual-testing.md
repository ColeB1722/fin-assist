# Manual Testing Checklist — Phase 8b (CLI REPL Mode)

**When to run**: After implementing Phase 8b, before Phase 9 (streaming).

**Purpose**: Verify FinPrompt integration end-to-end without automated tests. Designed for parallel testing + fixing.

---

## Chunk A — Basic CLI and Server

*No FinPrompt interactivity yet. Tests the foundation: server lifecycle and basic agent dispatch.*

> If this breaks, fix before touching FinPrompt.

| # | Test | Command | Expected |
|---|------|---------|----------|
| A1 | List agents | `fin-assist agents` | Auto-starts server, prints `shell` and `default` agent cards |
| A2 | List agents (reuse) | `fin-assist agents` (while server still up) | No restart, same output |
| A3 | Do shell one-shot | `fin-assist do shell list files` | Command output printed, no approval prompt |
| A4 | Do default one-shot | `fin-assist do default "hello"` | Text response printed |
| A5 | Stop server | `fin-assist stop` | "Hub stopped." printed |
| A6 | Stop when down | `fin-assist stop` (already stopped) | Error message, exit code 1 |

**If A fails**: server startup, client connectivity, or agent dispatch broken — not FinPrompt.

---

## Chunk B — Approval Widget (`fin-assist do shell`)

*Tests `run_approve_widget` via `fin-assist do shell` (requires approval).*

> Run B after confirming A works.

| # | Test | Action | Expected |
|---|------|--------|----------|
| B1 | Execute | Type `execute` | Command executes, exit code 0 |
| B2 | Cancel | Type `cancel` | "Cancelled" info message, no execution |
| B3 | Unknown input | Type `whoops` | Loops, prints valid options |
| B4 | Empty input | Just press Enter | Loops, no action |
| B5 | Ctrl+C | During approval prompt | Exits cleanly to shell |
| B6 | Ctrl+D | During approval prompt | Exits cleanly to shell |

**If B fails**: `approve.py`, FinPrompt wiring, or `main.py` integration broken.

---

## Chunk C — REPL Loop (`talk`)

*Tests the full `run_chat_loop` with FinPrompt.*

> Run C in parallel with B if A passes.

| # | Test | Action | Expected |
|---|------|--------|----------|
| C1 | Basic chat | Type message, press Enter | Agent response printed |
| C2 | Exit via /exit | Type `/exit` | Chat ends, "Session saved" |
| C3 | Exit via /quit | Type `/quit` | Same as /exit |
| C4 | Exit via /q | Type `/q` | Same as /exit |
| C5 | Unknown slash | Type `/bad` | "Unknown command" warning |
| C6 | Empty input | Press Enter with no text | Skipped, no message sent |
| C7 | Multi-turn | Send 2+ messages | Context preserved between turns |
| C8 | Ctrl+C | While typing input | Returns to prompt, no message sent |
| C9 | Ctrl+D | While typing input | Chat exits cleanly |
| C10 | Session file | After /exit | `~/.local/share/fin/sessions/<agent>/<slug>.json` exists |
| C11 | Resume session | `fin-assist talk <agent> --resume <slug>` | Conversation continues from prior context |

**If C fails**: `chat.py`, FinPrompt, or session persistence broken.

---

## Chunk D — FinPrompt Completions and History

*Tests the features FinPrompt was built for: fuzzy completion and persistent history.*

> Run D after confirming C1-C9 (basic loop) work.

| # | Test | Action | Expected |
|---|------|--------|----------|
| D1 | Slash trigger | Type just `/` | Completion menu appears |
| D2 | Fuzzy /exit | Type `/ex` + Tab | Completes to `/exit` |
| D3 | Fuzzy /quit | Type `/qu` + Tab | Completes to `/quit` |
| D4 | Fuzzy /switch | Type `/sw` + Tab | Completes to `/switch` |
| D5 | /switch agents | Type `/switch ` + Tab | Shows available agent names (shell, default) |
| D6 | History up | Press Up arrow | Previous input recalled |
| D7 | History down | Press Down after Up | Next/blank |
| D8 | History persists | Exit, restart `talk`, Up | Previous session input available |
| D9 | History file | `cat ~/.local/share/fin/history` | File exists with prior input lines |
| D10 | Help command | Type `/help` | Shows available commands |

**If D fails**: `prompt.py` completion wiring or history persistence broken.

---

## Running Order

```
A1-A6  →  Chunk A (blocks everything if broken)
          │
          ├── B1-B6  →  Chunk B
          │
          └── C1-C11 →  Chunk C  (run in parallel with B after A passes)
                       │
                       └── D1-D10 →  Chunk D (run after basic REPL loop works)
```

## If a Chunk Fails

1. Note which test(s) failed and which chunk.
2. File a bug or fix in a new branch.
3. A second session can pick up the next chunk while the fix is in review.

---

## Notes

- Server auto-starts on first command (`do`, `talk`, `agents`) via `ensure_server_running`.
- Use `fin-assist stop` between test sessions to ensure clean state.
- Session IDs are coolname slugs (e.g., `swift-harbor`) — not UUIDs.
- History file is at `~/.local/share/fin/history` (shared across `do` and `talk`).
