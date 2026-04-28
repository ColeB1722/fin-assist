# Handoff Document

Rolling context for session handoffs. Updated as checkpoints are reached.

**Current state (2026-04-27)**: 729 tests passing, CI green. Git agent (#79) shipped with scoped CLI tools (`git`, `gh`) and workflow config. All Tier 1 features shipped. Documentation synced with codebase. Phase 4 architectural discussions filed as issues [#89–#94](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+is%3Aissue+89+90+91+92+93+94).

**Core platform status:**

| Area | Status |
|------|--------|
| Executor rework + tool calling | ✅ Complete (Phases A + B merged via PR #87) |
| HITL approval | ✅ Complete (Phase C — `ApprovalPolicy`, deferred tool flow, approval widget) |
| ContextProviders dual path | ✅ Complete — model-driven (tools) + user-driven (`@`-completion) |
| Streaming UX (thinking + text deltas, `render_stream`) | ✅ Complete |
| `fin do` input panel + `--edit` | ✅ Complete — interactive input, pre-fill, `--agent` flag |
| `@`-completion in FinPrompt | ✅ Complete — `AtCompleter`, `resolve_at_references`, `_CombinedCompleter` |
| `fin list` capabilities | ✅ Complete — `tools`, `prompts`, `output-types` (local, no hub) |
| Remove built-in agents | ✅ Complete — `_DEFAULT_AGENTS = {}`, all from config.toml |
| Client artifact-merge fix | ✅ Complete — splice in both `stream_agent()` and `_send_and_wait()` |
| Git agent (#79) | ✅ Complete — scoped `git`/`gh` CLI tools, `WorkflowConfig`, three workflows (commit/pr/summarize) |
| Observability / tracing | 📐 Design resolved (Phoenix + OTel); queued as next session — see "Sequenced roadmap" |

**Remaining tracked items:**

- `_CONTEXT_TYPE_MAP` centralization — `AgentSpec._CONTEXT_TYPE_MAP` hardcodes tool→context mappings; tests read the private attribute.
- AgentBackend protocol simplification ([#80](https://github.com/ColeB1722/fin-assist/issues/80))
- `build_user_message`/`format_context` helpers in `llm/prompts.py` are dead code
- `supported_context_types` published in agent cards, never consumed by clients
- Phase 4 architectural discussions — issues [#89–#94](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+is%3Aissue+89+90+91+92+93+94)
- Scoped CLI tools approval=always is not final state — per-subcommand approval is Phase A of the sequenced Skills API plan (see "Design Sketches: Skills API" below)

---

## Next Session

**Planned: Tracing — Phoenix + OTel.**

Design is resolved (see architecture.md and handoff.md historical notes). Now that the git agent provides real multi-step tool-call + deferred-approval flows to observe, the tracing signal will be meaningful. Wire OTel spans to `StepEvent`/`StepHandle` boundaries from PR #87, ship Phoenix as the observability backend.

### Sequenced roadmap (why this order)

| # | Work | Rationale |
|---|------|-----------|
| 1 | **Tracing: Phoenix + OTel** (next session) | Design resolved but zero code in `src/`. Git agent provides real multi-step tool-call + deferred-approval flows to observe. `StepEvent`/`StepHandle` boundaries from PR #87 are fresh — cheapest time to wire instrumentation. Phoenix gives us an eval UI for free once traces are clean. |
| 2 | **Eval harness (per-agent, not platform-level)** | Evals are downstream of observability when using Phoenix. Two real agents exist (test + git) — eval criteria are meaningful. Platform stance: evals live at the agent level (`tests/evals/<agent>/`). Closes [#14](https://github.com/ColeB1722/fin-assist/issues/14). Likely surfaces [#80](https://github.com/ColeB1722/fin-assist/issues/80) (AgentBackend simplification). |
| 3 | **Skills API** | Generalizes the scoped CLI tools + workflow config pattern from the git agent. Per-subcommand approval, context templates, skill auto-discovery. See the Skills API GitHub issue for the full vision. |

**Why not tracing first:** tracing one agent (the `test` agent) gives ~10% of the learnings of tracing a real agent with non-trivial tool calls. The scaffolding would ship but the signal wouldn't.

**Why not evals first:** without tracing, eval failures are opaque — you know an eval failed but not why the agent went wrong in the middle of a 3-step tool loop. Phoenix eval primitives specifically consume OTel traces, so doing them in the other order duplicates work.

### Alternative picks if priorities change

1. **Phase 4 design discussions** — open issues [#89–#94](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+is%3Aissue+89+90+91+92+93+94). Each issue body is a session-ready brief. `#92` has a research spike as pre-work.
2. **Tech debt** — `_CONTEXT_TYPE_MAP` centralization, dead code cleanup in `llm/prompts.py`, AgentBackend simplification ([#80](https://github.com/ColeB1722/fin-assist/issues/80)).
3. **Future phases** — Multiplexer, TUI, Skills/MCP, additional agents, multi-agent workflows.
4. **Other open issues** — see `gh issue list` for the broader backlog.

---

## Implementation Progress

| Phase | Description | Status |
|-------|-------------|--------|
| 1–8b | Core platform (repo setup → CLI REPL) | ✅ Complete |
| — | Config-Driven Redesign (all steps including context injection) | ✅ Complete |
| — | a2a-sdk migration (from fasta2a) | ✅ Complete (2026-04-20) |
| — | Backend Extraction (AgentSpec pure config) | ✅ Complete (2026-04-21) |
| — | Auth-Required Credential Pre-Check | ✅ Complete (2026-04-03) |
| — | Reliable Server Lifecycle (fcntl PID lock) | ✅ Complete (2026-04-09) |
| — | Shared Render Pipeline (`render_agent_output`) | ✅ Complete |
| — | Streaming UX Refactor (thinking in artifacts, `render_stream`) | ✅ Complete (2026-04-23) |
| — | Unified Executor + Tools + HITL (PR #87 Phases A–C) | ✅ Complete (2026-04-24/26) |
| — | `FIN_DATA_DIR` unified path | ✅ Complete |
| — | Remove built-in agents (`_DEFAULT_AGENTS = {}`) | ✅ Complete |
| — | `fin do` input panel + `--edit` + `--agent` flag | ✅ Complete |
| — | `@`-completion (AtCompleter + resolve_at_references) | ✅ Complete |
| — | `fin list` capabilities (tools, prompts, output-types) | ✅ Complete |
| — | Client artifact-merge fix (splice in stream_agent + _send_and_wait) | ✅ Complete |
| — | ContextSettings forwarded to tool callables | ✅ Complete |
| — | PR #87 self-review triage (Phases 1–3) | ✅ Complete (2026-04-26) |
| — | Phase 4 architecture discussions | 📐 Filed as issues #89–#94 |
| — | Documentation sync (README, architecture.md, manual-testing.md, handoff.md) | ✅ Complete (2026-04-27) |
| — | Git agent (#79): scoped `git`/`gh` CLI tools, `WorkflowConfig`, three workflows | ✅ Complete (2026-04-27) |
| 9b | Full SSE Streaming (was blocked on fasta2a) | ✅ Covered by a2a-sdk migration |
| 10 | Non-blocking + interactive tasks | 📐 Superseded by deferred tools |
| 11 | Multiplexer Integration | ⬜ Not Started |
| 12 | Fish Plugin | ⬜ Not Started |
| 13 | TUI Client (A2A) | ⬜ Not Started |
| 14 | Testing Infrastructure (Deep Evals) — per-agent eval harness, rides on Phoenix traces | ⬜ Queued after tracing — see "Sequenced roadmap" in Next Session |
| 15 | Skills + MCP Integration | 📐 Scoped CLI tools + WorkflowConfig shipped (git agent); sequenced Phase A/B/C sketch resolved 2026-04-27 — see "Design Sketches" below |
| 16 | Additional Agents | 🔄 Git agent shipped; SDD/TDD/code review pending |
| 17 | Multi-Agent Workflows | ⬜ Not Started |
| 18 | Documentation | ⬜ Not Started |
| — | Phoenix/OTel tracing | 📐 Design resolved; queued as next session |
| — | Nix/Home Manager packaging | 📐 Sketched |

---

## Design Sketches

### Skills API: sequenced refactor (Phase 15 breakdown)

**Status:** Sketch resolved 2026-04-27. Ready to start Phase A in a fresh session.

**Why this exists:** the scoped CLI + WorkflowConfig pattern from the git agent (2026-04-27) is a prototype for the broader Skills API (`architecture.md:991`, Phase 15). Rather than landing Skills as one big refactor, split into three sequenced phases, each independently shippable with a real user-visible exit gate.

**Grounding citations** (in-repo, so this sketch stays honest):

- Scoped CLI prototype + TODO for per-subcommand approval: `src/fin_assist/agents/tools.py:213`, `src/fin_assist/agents/tools.py:295`
- Current `ApprovalPolicy` shape (only `never`/`always`, no rules): `src/fin_assist/agents/tools.py:40`
- `AgentConfig.tools` flat list of names: `src/fin_assist/config/schema.py:99`
- Empty `skills/` + `mcp/` placeholder folders: `architecture.md:291`, `architecture.md:294`
- Skills API vision (API + CLI + Skills pattern): `docs/architecture.md:991`–`:1007`
- Existing note: "Scoped CLI tools approval=always is not final state": this file, "Remaining tracked items"

---

#### Phase A — Subcommand approval rules

**Goal:** `git diff` runs un-gated; `git push` still asks. Highest-value slice of the user's idea, aligned with the explicit TODO at `tools.py:213`.

**Design:**

```python
# src/fin_assist/agents/tools.py
@dataclass
class ApprovalRule:
    pattern: str            # fnmatch-style glob against the full args string
    mode: Literal["never", "always"]
    reason: str | None = None

@dataclass
class ApprovalPolicy:
    mode: Literal["never", "always"]        # fallback when no rule matches
    rules: list[ApprovalRule] = field(default_factory=list)
    reason: str | None = None

    def evaluate(self, args: str) -> tuple[Literal["never", "always"], str | None]:
        for r in self.rules:
            if fnmatch(args, r.pattern):
                return r.mode, r.reason
        return self.mode, self.reason
```

**Touchpoints:**

- `src/fin_assist/agents/tools.py:40` — extend `ApprovalPolicy` (above)
- `src/fin_assist/agents/tools.py:295` — `_make_scoped_cli` callable becomes aware of its policy so the backend can query `policy.evaluate(args)` per call
- Backend adapter (pydantic-ai glue that reads `approval_policy`) — switch from static `requires_approval` flag to per-call evaluation via pydantic-ai's `approval_required()` toolset wrapper pattern
- **Rules still Python-defined in `create_default_registry()`** — no config schema change yet. Config authoring lands in Phase B.

**TDD tests (before implementation, per `AGENTS.md`):**

- `test_approval_policy_evaluate.py`: pattern matching, first-match-wins, fallback to `mode`, empty rules behaves like current `ApprovalPolicy`
- `test_tools_scoped_cli_approval.py`: `git diff` → never, `git push origin main` → always, `git log --oneline -5` → never, unknown subcommand → fallback
- Executor integration: deferred `StepEvent` emitted only when `evaluate()` returns `always`

**Exit gate:** through the git agent, `git diff` runs without an approval prompt; `git push` still pauses. Manual demo + tests.

**Files touched (estimate):** ~4 source, ~2 new test files, ~200 LOC + tests.

---

#### Phase B — Skill bundling (ToolDefinition → SkillDefinition)

**Goal:** one TOML object bundles a scoped CLI + its approval rules + named scripts + workflows. Makes skills authorable end-to-end in config.

**Design (TOML shape):**

```toml
[skills.git]
type = "cli"                         # preps the tool-type taxonomy in Phase C
prefix = "git"
description = "Run any git subcommand."

[skills.git.approval]
default = "always"
rules = [
  { pattern = "diff*",   mode = "never" },
  { pattern = "status*", mode = "never" },
  { pattern = "log*",    mode = "never" },
  { pattern = "show*",   mode = "never" },
]

[skills.git.scripts.pr-checklist]
description = "Print the PR review checklist from scripts/git/pr-checklist.sh"
path = "scripts/git/pr-checklist.sh"
approval = "never"

# Workflows move under skills (decided 2026-04-27) to unlock cross-agent reuse.
# The existing [agents.<name>.workflows.<w>] keys MUST be migrated; no dual-read.
[skills.git.workflows.commit]
description = "Generate a conventional commit message from current changes."
prompt_template = "git-commit"
entry_prompt = "Analyze the current staged and unstaged changes and generate a conventional commit message."
```

**Touchpoints:**

- **New:** `src/fin_assist/skills/` package (currently empty placeholder at `architecture.md:291`). Contains:
  - `definition.py` — `SkillDefinition`, `SkillConfig` (pydantic model)
  - `loader.py` — reads `config.skills`, instantiates `SkillDefinition`s
  - `registration.py` — adapter that expands a skill into N `ToolDefinition`s (the CLI itself + one per named script), all sharing the skill's approval policy, and registers them into `ToolRegistry`
- `src/fin_assist/config/schema.py:85` — add `skills: dict[str, SkillConfig]` at root `Config` level. **Remove** `workflows` from `AgentConfig`; migrate to `SkillConfig.workflows`. `AgentConfig.tools` now references either raw tool names or skill names (skill name expands to "CLI tool + its scripts").
- `src/fin_assist/hub/app.py:create_hub_app` — load skills and register into the shared `ToolRegistry` before `AgentSpec` construction (so `spec.tools` resolution sees them).
- `config.toml` — migrate `[agents.git.workflows.*]` to `[skills.git.workflows.*]`. Agent still references the skill via `tools = ["git", "gh"]`.
- `src/fin_assist/cli/main.py` — workflow resolution (`fin do git commit`) now looks up the workflow via the agent's skills, not `AgentConfig.workflows` directly.

**What Phase B explicitly does NOT do:**

- No tool-type dispatch beyond validation. `type = "cli"` is required and parsed, but only the CLI branch is wired. Second branch (`mcp`, `function`, `browser`) waits for Phase C with a real consumer.
- No KG / NL-over-docs discoverability. Current `description` is sufficient (and `fin list tools` already surfaces it).
- No cross-project skill auto-discovery from `~/.config/fin/skills/`. Phase 15 stretch goal.

**TDD tests:**

- `test_skills_config.py`: TOML parsing for skill + approval rules + scripts + workflows
- `test_skills_registration.py`: a skill with `scripts = {foo, bar}` registers 3 `ToolDefinition`s (`git`, `git.foo`, `git.bar`) all sharing the approval policy
- `test_skills_workflow_resolution.py`: `fin do git commit` resolves to `[skills.git.workflows.commit]`, not the old `[agents.git.workflows.commit]`
- Migration test: loading a config with the legacy `[agents.*.workflows.*]` shape raises a clear error pointing to the new location (no silent fallback)

**Exit gate:** `config.toml` defines `skills.git` with subcommand rules and at least one named script; `[agents.git] tools = ["git"]` auto-resolves to the Skill; behavior identical to Phase A but config-driven. A **second** skill authored end-to-end in TOML (candidate: `just`, `gh`, or `docker` — pick at implementation time based on what's most useful for the dev loop) as the config-path validation.

**Files touched (estimate):** ~3 new source files, ~3 modified source files, ~4 new test files, ~400 LOC + tests + config migration.

---

#### Phase C — Tool-type primitive

**Goal:** `type: Literal["cli", "mcp", ...]` as a first-class field, with type-specific OTel span attributes and a self-documenting registry.

**Gate for starting Phase C:** a second tool type has a concrete consumer. Most likely trigger: MCP integration (`architecture.md:294`, `tools.py:22`). Secondary candidates: browser-use, Python-script-exec-in-sandbox. **Do not start Phase C speculatively** — the primitive is premature generalization without a second consumer.

**Design:**

```python
# src/fin_assist/agents/tool_types.py  (new)
class ToolTypeAdapter(Protocol):
    """How a tool of type <T> is invoked, traced, and loaded from config."""

    type_name: str  # "cli", "mcp", "function", "browser", ...

    def span_attributes(self) -> list[str]:
        """OTel attribute names this type emits. Powers `fin list tool-types`."""

    async def invoke(
        self, definition: ToolDefinition, args: dict[str, Any]
    ) -> str:
        """Run the tool and emit a type-shaped OTel span around the callable."""

    def load_from_config(self, skill_config: SkillConfig) -> list[ToolDefinition]:
        """Turn TOML config into ToolDefinitions. Phase B's CLI loader moves here."""
```

- `ToolDefinition.type: str` — required field (default `"cli"` for backward compat at first, made required once all skills declare explicitly)
- OTel instrumentation lives in the adapter, **not** in the tool callable. Preserves "platform types zero framework deps" invariant at `agents/tools.py:1`
- Global `ToolTypeRegistry` (alongside `ToolRegistry`) maps `type_name` → adapter

**Expanded exit gate (per 2026-04-27 discussion):**

1. **Type-adapter pattern codified.** `ToolTypeAdapter` protocol lands with the `cli` adapter as the first implementation. The existing `_make_scoped_cli` logic moves behind the adapter interface; all current CLI-typed skills flow through it unchanged. Span attributes for `cli`: `cli.prefix`, `cli.args`, `cli.exit_code`, `cli.duration_ms`, `cli.timed_out`.
2. **Second adapter lands end-to-end.** Most likely `mcp` — `MCPToolsetAdapter` connects to one configured MCP server, enumerates its tools via the MCP client protocol, and registers each as a `ToolDefinition(type="mcp", ...)`. Span attributes for `mcp`: `mcp.server`, `mcp.tool_name`, `mcp.request_id`, `mcp.duration_ms`. Ships with one real MCP server working end-to-end (candidate: `mcp-server-git` or a filesystem server; decide at implementation time based on ecosystem state).
3. **`fin list tool-types` CLI surface.** New subcommand matching the existing `fin list tools/prompts/output-types` pattern (from handoff Tier 1 work). Output shape:
   ```
   cli        span attrs: cli.prefix, cli.args, cli.exit_code, cli.duration_ms, cli.timed_out
              skills: git, gh, just
   mcp        span attrs: mcp.server, mcp.tool_name, mcp.request_id, mcp.duration_ms
              skills: mcp.filesystem, mcp.github
   ```
   Self-documenting: adding a new type means its span schema is discoverable without reading adapter source. Enforces the invariant that types are semantically distinct (if two types have identical `span_attributes()`, one of them is decorative).
4. **Span semantics verified in Phoenix.** By the time Phase C starts, Phoenix/OTel has shipped (next-session work per `handoff.md:36`). Exit criterion: open Phoenix, see `cli`-type and `mcp`-type invocations side-by-side with their type-specific attributes, and be able to filter traces by `tool.type`. **This is the gate that proves the primitive has real semantic weight rather than being a decorative enum.**

**Files touched (estimate):** ~5 new source files (tool_types module, MCP adapter, MCP client wrapper), ~4 modified (ToolDefinition field, backend adapter wiring, CLI `list` command, Phoenix instrumentation hooks), ~5 new test files, ~600 LOC + tests + MCP integration test.

---

#### Explicitly parked (from the original brainstorm)

- **Knowledge-graph–backed tool discoverability** (NL Q&A over man pages / docs). Revisit post-Skills as a new `ContextProvider` implementation if a real pain point appears — LLMs already know `git`'s surface area, and Context7 covers library docs. Not on Phase A/B/C critical path.
- **"One `bash` supertool" framing.** Rejected in favor of distinct prefix-scoped Skills. The codebase direction (`tools.py:14`) is explicitly away from generic shell as primary surface; scoped CLIs are the replacement.
- **"Agents orchestrate many CLIs" as new design.** Already the shape (`[agents.git] tools = ["git", "gh", "run_shell", ...]`); Skills make it more structured but don't change the conceptual model.

#### Sequencing summary

| Phase | Ship | Blocks on | Real consumer |
|---|---|---|---|
| A | Per-subcommand approval (Python-defined rules) | — | Git agent UX today |
| B | Skill object (TOML-authored skills, script bundling, workflows migrated under skills) | Phase A | User-authored skills; replaces agent-scoped workflows |
| C | Tool-type taxonomy + adapter pattern + `fin list tool-types` | Phase B + Phoenix/OTel + a real second type (MCP likely) | MCP integration or browser-use |

**Start here in next session:** Phase A, TDD-first per `AGENTS.md`. Open the failing `test_approval_policy_evaluate.py` first.

---

## Historical Reference

Key completed milestones. See git log for full detail; code is the source of truth.

### Git Agent + Scoped CLI Tools (#79, 2026-04-27)

First real end-user agent. Introduced three concepts that generalize to the Skills API:

- **Scoped CLI tools**: `git` and `gh` tools that wrap a command prefix (`git {args}`, `gh {args}`). Replaced per-subcommand wrappers (`git_diff`, `git_log`) — one tool per CLI instead of one per subcommand, saving prompt tokens. Approval is `always` for all scoped CLI tools; per-subcommand approval is a planned Skills API enhancement.
- **WorkflowConfig**: Agent-scoped config primitive for prompt-steered sub-tasks. Each workflow has a description, prompt_template (system prompt override), entry_prompt (sent as user message), and optional serving_modes override. CLI resolves workflows via `fin do git commit` (positional) or `--workflow commit` (explicit flag).
- **Git agent system prompt**: Covers three workflows (commit, PR, summarize) with step-by-step instructions. Each workflow has a dedicated prompt template in `SYSTEM_PROMPTS` for focused steering.

Files changed: `tools.py` (scoped CLI factory, remove `git_diff`/`git_log`), `spec.py` (`_CONTEXT_TYPE_MAP` update), `prompts.py` (git instructions), `registry.py` (prompt registration), `schema.py` (`WorkflowConfig`), `config.toml` (git agent + workflows), `main.py` (workflow resolution + `--workflow` flag), `streaming.py` (emoji map + key arg for scoped tools).

### Tier 1 Features + Doc Sync (2026-04-27)

All remaining Tier 1 features landed and documentation synchronized with codebase:

- **`@`-completion**: `AtCompleter` in `prompt.py` triggers on `@`, offers `file:`, `git:diff`, `git:log`, `history:` types. `@file:` delegates to `FileFinder.search()`. `resolve_at_references()` replaces `@type:ref` tokens with resolved context content before sending. Works in both `do` and `talk`.
- **`fin list`**: New `list` subcommand with positional `resource: Literal["tools", "prompts", "output-types"]`. Local registry lookups only — no hub connection. Prints name, description, approval status for tools; name + first line for prompts; name → type name for output-types.
- **`--file`/`--git-diff` removed**: No deprecation path — codebase isn't stable, so the old CLI flags were simply dropped. `@`-completion is the sole user-driven context path.
- **`fin do` input panel + `--edit`**: `fin do` without prompt opens FinPrompt input panel. `--edit` pre-fills with the prompt arg. `--agent` flag replaces positional agent arg.
- **Remove built-in agents**: `_DEFAULT_AGENTS = {}`. All agents from config.toml. `GeneralSettings.default_agent` config field. Zero-agents error with TOML example.
- **Client artifact-merge fix**: Splice collected artifacts into `task.artifacts` in both `stream_agent()` and `_send_and_wait()` before calling `_extract_result()`.
- **ContextSettings forwarded to tool callables**: `_make_read_file()`, `_make_git_diff()`, etc. all pass `context_settings` to provider constructors.
- **Doc sync**: README (duplicate Mermaid subgraph fixed, `@`-completion + `fin list` in status), architecture.md (directory tree updated, context section updated, `--file`/`--git-diff` references corrected to historical), manual-testing.md (test counts, `@`-completion tests, `fin list` tests), handoff.md (full rewrite to reflect current state).

### Unified Executor & Agent Platform (2026-04-24 → 2026-04-26, PR #87)

Unified five structural gaps into one coherent abstraction: executor loop (multi-step turns), tool calling, dual-path context (user-driven `@`-completion + model-driven tools), HITL approval gates, and OTel-ready step boundaries.

**Guiding principle:** the platform owns the abstractions, backends adapt them. Tools, approval, and step events are platform concepts (zero framework imports); `PydanticAIBackend` maps them to pydantic-ai Deferred Tools / Hooks. Future `LangChainBackend` etc. would map the same platform types to their own primitives.

**Phase A (Foundation) shipped.** ContextStore version byte; `StepEvent`/`StepHandle`/`_PydanticAIStepHandle`; Executor rewritten event-driven; all tests updated.

**Phase B (Tool Calling) shipped.** `ToolDefinition`/`ToolRegistry` in `agents/tools.py`; `create_default_registry()` wraps `ContextProvider`s as async callables; `AgentConfig.tools` field; `AgentSpec.supports_context()` derived from tools; `AgentCardMeta.supported_context_types`; `PydanticAIBackend` resolves tools via `tool_registry.get_for_agent(spec.tools)`.

**Phase C (HITL / Approval) shipped.** `ApprovalPolicy` on `ToolDefinition`; deferred tool flow end-to-end; `DeferredToolCall` dataclass; `run_approval_widget` in CLI.

**Phase D (Observability).** Design only — Phoenix + OTel via `Agent.instrument_all()` aligned to step boundaries. Not yet implemented.

### PR #87 Self-Review Triage (2026-04-26)

45 review comments left on PR #87 as a notetaking mechanism. Worked through in phases:

**Phase 1 — Quick wins** (commit `6149a2b`): Removed stale imports/ignores, `_key_arg_for_tool` → `match`, removed redundant `dest=` kwargs, if/elif → `match`, env var naming convention in AGENTS.md.

**Phase 2 — Real smells** (5 items, all landed): Extracted version envelope to `agents/serialization.py`, dropped `conditional` approval mode, promoted `DeferredToolCall` dataclass, added lifecycle logging, split `Executor.execute()`.

**Phase 3 — Real bugs** (3 items, all landed): Rewrote `_run_shell` with asyncio-native subprocess, dropped unused `AgentSpec.requires_approval`, normalized `StepEvent.content` for `tool_result`.

**Phase 4 — Architectural discussions** filed as issues #89–#94.

### Streaming UX Refactor (2026-04-23)

Backend streams typed `StreamDelta(kind, content)` via pydantic-ai `agent.iter()`. Executor routes thinking deltas as artifacts with `metadata.type = "thinking"`. Client yields `thinking_delta` events. Shared `render_stream()` uses Rich `Live` with initial spinner, transitions to `Group(thinking_panel?, answer_markdown)`. Both `do` and `talk` use the same pipeline.

### AgentBackend Extraction (2026-04-21)

Extracted pydantic-ai coupling from hub into `AgentBackend` protocol. `AgentSpec` is now pure config (no `build_pydantic_agent`); all pydantic-ai knowledge in `PydanticAIBackend`. ContextStore takes `bytes` in/out — backend owns serialization. Executor takes `AgentBackend` and has zero pydantic-ai imports. Tracked simplification work as [#80](https://github.com/ColeB1722/fin-assist/issues/80).

### fasta2a → a2a-sdk Migration (2026-04-20)

Full migration from `fasta2a` (pydantic's abandoned A2A impl) to `a2a-sdk` v1.0.0 (Google's official). Hub/executor uses `TaskUpdater` for all state transitions. `InMemoryTaskStore` (ephemeral) + SQLite `ContextStore` (conversation history). Agent card uses `AgentExtension(uri="fin_assist:meta")`. FastAPI parent app. Client uses `ClientFactory` + `send_message` async iterator. Streaming via `add_artifact(append=True, last_chunk=)`.

### Config-Driven Redesign (2026-04-11)

Agents went from class-hierarchy (`DefaultAgent`, `ShellAgent` subclasses) to a single `ConfigAgent` driven by TOML. `AgentConfig` in `config/schema.py`. `ServingMode = Literal["do", "talk"]` replaces `multi_turn: bool`. `OUTPUT_TYPES` and `SYSTEM_PROMPTS` registries. Direct `Worker[list[ModelMessage]]` (closed #68).

### Auth-Required Credential Pre-Check (2026-04-03)

Graceful early detection of missing API keys using A2A `auth-required` state. `MissingCredentialsError` raised in backend before any LLM call. Client renders yellow panel with provider name, env vars, credentials path.

### Reliable Server Lifecycle (2026-04-09)

Server-owned PID file with `fcntl.flock()`. `atexit` + custom SIGTERM handler cleans up. Lock-based stale detection. `stop_server` sends SIGTERM, waits up to 10s, escalates to SIGKILL.

### Early Platform Setup (2026-03-25 → 2026-04-08)

Phases 1–8b: repo setup, core package structure, LLM module (pydantic-ai + credentials), credential UI (Textual `ConnectDialog`), context module (FileFinder/GitContext/ShellHistory/Environment providers), agent protocol & registry, agent hub server (fasta2a + SQLite), CLI client (A2A HTTP), CLI REPL mode (`FinPrompt` with prompt_toolkit, slash commands, persistent history).

---

## Context for Fresh Session

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
| `handoff.md` | This file — rolling session context |
| `pyproject.toml` | Dependencies, tool config |
| `justfile` | Task runner commands |

---

## Notes

- Target fish 3.2+ for shell integration
- Config stored in `~/.config/fin/config.toml`
- Credentials stored in `$FIN_DATA_DIR/credentials.json` (0600 permissions)
- Server binds to `127.0.0.1` only (local-only)
- A2A protocol via a2a-sdk v1.0 for multi-client support
- Multi-path routing: N agents at `/agents/{name}/`, each with own agent card
- Conversation threading via A2A `context_id`
- SQLite for context storage; `InMemoryTaskStore` for A2A tasks (ephemeral)
- Server lifecycle: standalone via `fin serve`; auto-start from CLI; fcntl-locked PID file
- `AgentSpec` is a pure config object (zero framework imports); all LLM coupling in `PydanticAIBackend`
- Platform types in `agents/` have zero `hub/` imports by design (platform vs transport separation)
- `@`-completion is the sole user-driven context path (`@file:`, `@git:diff`, `@git:log`, `@history:`); `--file`/`--git-diff` CLI flags removed
- `fin list tools/prompts/output-types` lists platform registries locally (no hub connection)
- Scoped CLI tools (`git`, `gh`) are the prototype for the Skills API — one tool per CLI, LLM picks subcommand/args
- WorkflowConfig is agent-scoped prompt steering; full Skills API will generalize to global registry + context templates + per-subcommand approval
