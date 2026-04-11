# Manual Testing Checklist

**When to run**: After changes to CLI commands, server lifecycle, approval widget, or chat loop.

**Purpose**: Verify CLI integration end-to-end without automated tests. Designed for parallel testing + fixing.

> All commands shown as `fin` can also be invoked as `fin-assist`.

---

## Chunk A — Basic CLI and Server

*Tests the foundation: server lifecycle, start/stop/status, and basic agent dispatch.*

> If this breaks, fix before touching interactive features.

| # | Test | Command | Expected |
|---|------|---------|----------|
| A1 | List agents | `fin agents` | Auto-starts server, prints `shell` and `default` agent cards |
| A2 | List agents (reuse) | `fin agents` (while server still up) | No restart, same output |
| A3 | Do shell | `fin do shell list files` | Generated command in panel, then approval widget (Execute/Cancel) |
| A4 | Do default one-shot | `fin do default "hello"` | Text response printed |
| A5 | Start server | `fin start` | "Hub running at http://..." |
| A6 | Start when running | `fin start` (already up) | Same message, no restart (idempotent) |
| A7 | Status when running | `fin status` (server up) | "Hub running at http://..., PID ..." |
| A8 | Status when stopped | `fin status` (server down) | "Hub is not running." |
| A9 | Stop server | `fin stop` | "Hub stopped." printed |
| A10 | Stop when down | `fin stop` (already stopped) | Error message, exit code 1 |

**If A fails**: server startup, client connectivity, or agent dispatch broken.

---

## Chunk B — Approval Widget (`fin do shell`)

*Tests the arrow-key selection widget via `fin do shell` (requires approval).*

The approval widget uses `ChoiceInput` — arrow-key navigation between Execute/Cancel, Enter to confirm. No text input, no slash commands.

> Run B after confirming A works.

| # | Test | Action | Expected |
|---|------|--------|----------|
| B1 | Execute (default) | Press Enter immediately | Command executes, exit code 0 (Execute is default selection) |
| B2 | Execute (navigate) | Arrow to Execute, press Enter | Command executes, exit code 0 |
| B3 | Cancel | Arrow to Cancel, press Enter | "Cancelled" info message, no execution |
| B4 | Ctrl+C | During approval prompt | Cancels, exits cleanly to shell |
| B5 | Ctrl+D | During approval prompt | Cancels, exits cleanly to shell |
| B6 | Escape | During approval prompt | Cancels, exits cleanly to shell |
| B7 | No text input | Observe widget | Only arrow-key selection shown; no text field, no slash completions |

**If B fails**: `approve.py` or `main.py` approval integration broken.

---

## Chunk C — REPL Loop (`fin talk <agent>`)

*Tests the full `run_chat_loop` with FinPrompt. Start with `fin talk default`.*

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
| C11 | Resume session | `fin talk <agent> --resume <slug>` | Conversation continues from prior context |

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
A1-A10 →  Chunk A (blocks everything if broken)
          │
          ├── B1-B7  →  Chunk B
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
- Use `fin stop` between test sessions to ensure clean state. Use `fin status` to check.
- If `fin stop` fails but the server is running, it falls back to `/proc` scanning to find the orphaned process.
- Session IDs are coolname slugs (e.g., `swift-harbor`) — not UUIDs.
- History file is at `~/.local/share/fin/history` (used by `talk` sessions only).
