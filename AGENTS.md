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
├── hub/              - Agent Hub server (Starlette + fasta2a)
├── cli/              - CLI client (primary client)
├── agents/           - Agent protocol, registry, implementations
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

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Python | 3.12+ (3.13 in nixpkgs) | Stable, production-ready, good ecosystem |
| LLM | pydantic-ai | Unified interface for 20+ providers, FallbackModel |
| Server | Starlette + fasta2a (A2A) | Protocol-native multi-agent hub, agent discovery |
| Primary client | CLI (Rich + httpx) | Fast iteration; TUI and other clients come later |
| TUI | Textual | Mature async TUI framework (future A2A client) |
| Multiplexers | tmux + zellij | Most common; ghostty pending |
| Credentials | Separate from config | Allows config sharing without secrets |
| Provider setup | `/connect` command | Familiar pattern from opencode |

## Testing

- Use `pytest` with `pytest-asyncio` for async tests
- Use `pytest-textual-snapshot` for TUI tests
- Run `just test-cov` for coverage report

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

## Before Committing

1. Run `just ci` to ensure all checks pass
2. Update `handoff.md` if work spans multiple sessions
3. Reference `docs/architecture.md` for design decisions
