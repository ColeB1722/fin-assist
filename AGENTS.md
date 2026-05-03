# fin-assist

Expandable personal AI agent platform for terminal workflows. See `docs/architecture.md` for full architecture.

## Development Workflow

This project follows an **SDD → TDD** implementation pattern:

### 1. Sketch-Driven Design (SDD)

Before implementing any feature:
1. Review `docs/architecture.md` for alignment
2. Sketch the design in `handoff.md` under "Design Sketches"
3. Define interfaces and data flow
4. Identify edge cases and error handling

### 2. Test-Driven Development (TDD)

After design is sketched, write tests BEFORE writing implementation code:

1. **Write failing test first** — test specifies expected behavior
2. **Implement minimal code** — just enough to pass the test
3. **Refactor** — improve code while keeping tests green
4. **Update handoff.md** — document what was accomplished

**Test quality standards:**
- Test behavior, not implementation (avoid exact string matches)
- Use public API, not private state
- Derive expected values from centralized types (e.g., `ContextType`)
- Fixtures for reusable setup, avoid `setup_method` with manual cleanup

## Commands

| Command | Description |
|---------|-------------|
| `just` | List all tasks |
| `just dev` | Enter dev shell |
| `just fmt` | Format all code |
| `just lint` | Run linter |
| `just lint-fix` | Auto-fix lint issues |
| `just typecheck` | Run type checker |
| `just test` | Run tests |
| `just test-cov` | Run tests with coverage |
| `just ci` | Run full CI suite |
| `just run` | Run the TUI locally |
| `just install-fish` | Install fish plugin |

## Project Structure

```text
src/fin_assist/       - Main package
├── hub/              - Agent Hub server (FastAPI + a2a-sdk)
├── cli/              - CLI client (primary client)
├── agents/           - Agent protocol, registry, skills
├── llm/              - pydantic-ai integration
├── context/          - Context gathering
├── credentials/      - API key management
├── config/           - Config loading
├── ui/               - TUI client (Textual, future)
└── multiplexer/      - tmux/zellij support (future)

tests/                - Test suite
docs/                 - Architecture docs
fish/                 - Fish shell plugin (future)
```

## Local Development Paths

This project is intended to run locally for personal use. Dev ergonomics: runtime state (logs, database, PID file, sessions, history, credentials) should stay colocated with the repo while developing, not scattered under `~/.local/share/fin/`.

**Current state:** All runtime paths derive from `FIN_DATA_DIR` (default `~/.local/share/fin`). Set `FIN_DATA_DIR=./.fin` to keep state local to the repo.

| Path | Default location | Env override |
|------|------------------|--------------|
| Hub log | `$FIN_DATA_DIR/hub.log` | `FIN_DATA_DIR` (or `FIN_SERVER__LOG_PATH`) |
| Hub DB | `$FIN_DATA_DIR/hub.db` | `FIN_DATA_DIR` (or `FIN_SERVER__DB_PATH`) |
| PID file | `$FIN_DATA_DIR/hub.pid` | `FIN_DATA_DIR` |
| Sessions | `$FIN_DATA_DIR/sessions/` | `FIN_DATA_DIR` |
| REPL history | `$FIN_DATA_DIR/history` | `FIN_DATA_DIR` |
| Credentials | `$FIN_DATA_DIR/credentials.json` | `FIN_DATA_DIR` |
| Trace JSONL | `$FIN_DATA_DIR/traces.jsonl` | `FIN_DATA_DIR` (always active when tracing enabled) |

**Dev override** (in `devenv.nix`): `FIN_DATA_DIR = "./.fin"` — all runtime state stays in `.fin/` (git-ignored). Tracing is enabled (`FIN_TRACING__ENABLED=true`) and spans are written to both Phoenix (if running at `localhost:6006`) and `./.fin/traces.jsonl`.

**When adding a new runtime path:** plumb it through `src/fin_assist/paths.py`, honor `FIN_DATA_DIR`, and update the table above.

### Env var naming convention

This split is **project-specific**, not an industry standard — but we apply it consistently so the reading mechanism is obvious from the name:

| Pattern | Read by | Example | When to use |
|---------|---------|---------|-------------|
| `FIN_<NAME>` (single `_`) | `os.environ.get()` directly | `FIN_DATA_DIR` | Bootstrap vars needed before pydantic loads (paths, feature flags) |
| `FIN_<SECTION>__<FIELD>` (double `__`) | pydantic-settings | `FIN_GENERAL__DEFAULT_MODEL`, `FIN_SERVER__PORT` | Anything in `config/schema.py` — `env_nested_delimiter="__"` maps `SECTION__FIELD` → `config.section.field` |

**Context:** Double-underscore as a nested-section delimiter is a pydantic-settings convention (also used by ASP.NET Core and others) — it's not in POSIX or any RFC. We adopted it for config and kept flat bootstrap vars on single underscore to signal "this is read before pydantic is initialized."

**When adding a new env var:** if it feeds into pydantic config, add it to `config/schema.py` and it becomes `FIN_<SECTION>__<FIELD>` automatically. If it must be read at import time (like `paths.py`), use `FIN_<NAME>` via `os.environ.get()` and document it in the Local Development Paths table.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Python | 3.12+ (3.13 in nixpkgs) | Stable, production-ready, good ecosystem |
| LLM | pydantic-ai | Unified interface for 20+ providers, FallbackModel |
| Server | FastAPI + a2a-sdk (A2A) | Protocol-native multi-agent hub, agent discovery |
| Primary client | CLI (Rich + httpx) | Fast iteration; TUI and other clients come later |
| TUI | Textual | Mature async TUI framework (future A2A client) |
| Multiplexers | tmux + zellij | Most common; ghostty pending |
| Credentials | Separate from config | Allows config sharing without secrets |
| Provider setup | `/connect` command | Familiar pattern from opencode |
| Fuzzy matching | `rapidfuzz` | Unified across slash commands and `@file:` completion; C-backed, path-aware ranking via `fuzz.WRatio` |
| File discovery | `os.walk` + `pathspec` | Gitignore-aware directory pruning (files still included so local configs like `config.toml` complete); pure Python, no subprocess |
| Completion threading | `PromptSession(complete_in_thread=True)` | Keeps UI responsive even on cold scans — non-negotiable for `@file:` |

## Testing

- Use `pytest` with `pytest-asyncio` for async tests
- Use `pytest-textual-snapshot` for TUI tests
- Run `just test-cov` for coverage report

## Logging

- **Hub**: `src/fin_assist/hub/logging.py` configures a rotating file handler writing to `$FIN_DATA_DIR/hub.log`. All `logging.getLogger(__name__)` calls anywhere in the hub inherit this handler — no per-module setup needed.
- **Levels**:
  - `INFO` for lifecycle events (task start/end, auth required, pause for approval, resume, agent mount)
  - `WARNING` for recoverable anomalies (missing credentials, malformed payloads)
  - `DEBUG` for per-event internals (history load, event dispatch details)
  - `logger.exception(...)` for caught-and-re-raised exceptions so stack traces land in hub.log
- **CLI**: no logging configured — user-facing messages go via `render_info` / `render_error` in `cli/display.py`. A `--verbose` → `$FIN_DATA_DIR/cli.log` story is planned but not implemented.
- **When adding logs**: prefer structured key=value fields (`task_id=%s`, `missing=%s`) over prose so future log aggregation is easier. Don't log anything that could contain user secrets (API keys, file contents beyond path).

## Session Handoffs (handoff.md)

`handoff.md` is the rolling context document for multi-session development. It enables seamless handoffs between coding sessions (including AI agent sessions).

### Purpose

- Capture what was accomplished in each session
- Document design sketches before implementation
- Track implementation progress across phases
- Provide quick-start context for fresh sessions

### When to Update

- **Start of session**: Read handoff.md first for context
- **After design work**: Add sketches to "Design Sketches" section
- **At checkpoints**: Update "What Was Accomplished"
- **End of session**: Update "Next Session" with next steps
- **Phase completion**: Update "Implementation Progress" table

### Fresh Session Quick-Start

1. Read `handoff.md` - current state and next steps
2. Read `docs/architecture.md` - full architecture
3. Read `AGENTS.md` - dev patterns (this file)
4. Check "Implementation Progress" table
5. Continue from "Next Session" section

## Skill Authoring

Skills are the primary mechanism for organizing agent behavior. Each skill bundles tools, context injection text, and prompt steering. Approval policies are defined at the agent level via `tool_policies`, not per-skill.

### Inline TOML skills

Define skills in `config.toml` under `[agents.<name>.skills.<skill>]`:

```toml
[agents.git]
base_tools = ["read_file"]

[agents.git.skills.commit]
description = "Generate a conventional commit message from current changes."
tools = ["git", "read_file"]
prompt_template = "git-commit"
entry_prompt = "Analyze the current staged and unstaged changes and generate a conventional commit message."

[agents.git.tool_policies.git]
default = "always"
rules = [
  { pattern = "git diff*", mode = "never" },
  { pattern = "git add*", mode = "never" },
  { pattern = "git commit*", mode = "never" },
]
```

### SKILL.md files

For skills with substantial context, create a SKILL.md file following the agentskills.io open standard:

- **Project skills**: `.fin/skills/<name>/SKILL.md`
- **User skills**: `~/.config/fin/skills/<name>/SKILL.md`

Project-level skills take precedence for same-name skills.

```markdown
---
name: commit
description: Generate a conventional commit message.
allowed-tools:
  - git
  - read_file
metadata:
  fin-assist:
    prompt-template: git-commit
    entry-prompt: Analyze the current changes and commit.
---
## Guidelines

Use conventional commits format...
```

### Key points

- Skills are **additive** — once loaded, a skill's tools stay active for the session
- Tools are **gated** — only `base_tools` + loaded skills' tools are registered; unloaded skills' tools are not available
- Tools are **shared** across skills — name collisions are a config validation error
- **Agent-level** `tool_policies` define approval per tool, not per skill (eliminates merge conflicts)
- `AgentSpec.base_tools` lists always-available safe/read-only tools (default: `["read_file"]`)
- `--skill` CLI flag pre-loads a skill: `fin do git --skill commit`
- Positional skill matching: `fin do git commit` → agent=git, skill=commit
- `/skill:<name>` REPL command loads a skill mid-session
- `fin list skills` shows all skills grouped by agent
- `fin list skills` shows all skills grouped by agent

### When adding a new skill

1. Add the skill to `config.toml` under the appropriate agent
2. If the skill needs a new tool, add it to `create_default_registry()` in `agents/tools.py`
3. Write tests in `tests/test_agents/test_skills.py` (loader, catalog, manager)
4. Run `just ci` to verify
5. Update `docs/architecture.md` if the skill introduces new patterns

## Before Committing

1. Run `just ci` to ensure all checks pass
2. Update `handoff.md` if work spans multiple sessions
3. Reference `docs/architecture.md` for design decisions
