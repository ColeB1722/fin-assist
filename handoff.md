# Handoff Document

Rolling context for session handoffs. Updated as checkpoints are reached.

**Current state (2026-04-30):** 880 tests passing, `just ci` green. PR #103 (OTel tracing) review comments addressed in code, awaiting merge. All Tier 1 features shipped. Tracing fully integrated: hub + CLI spans, JSONL file sink, HITL two-span trace continuity, noise suppression, attribute hygiene. Code review follow-up issue [#111](https://github.com/ColeB1722/fin-assist/issues/111) open.

**Recent refactoring (this session):**

1. **`tracing_shared.py`** — extracted shared span processors, config resolvers, and constants from `hub/tracing.py` and `cli/tracing.py` into a new public module. Eliminated cross-module private imports and duplicated logic. Dependency graph changed from `cli/ → hub/` to `cli/ → tracing_shared/ ← hub/`.
2. **`get_user_input` fix** — removed test-induced fallback path (`getattr(context.message, ...)`) from executor; fixed `_make_request_context` helper in `test_tracing.py` to stub on the context object where the real a2a-sdk API puts it.
3. **Executor prep extract** — extracted `_extract_user_input()` (static method) and `_detect_resume()` + `_ResumeInfo` dataclass from `execute()`, shrinking the method by ~15 lines and untangling user-input extraction and resume detection into named, testable units.

**Deferred to follow-up PR:** Full `_TaskTracer` extraction from `executor.py` — moving 6 tracing fields from `_ExecutionContext` and 8 tracing methods from `Executor` into a dedicated `_TaskTracer` class. See "Design Sketches: _TaskTracer Extraction" below.

**Core platform status:**

| Area | Status |
|------|--------|
| Executor rework + tool calling | ✅ Complete (PR #87) |
| HITL approval | ✅ Complete |
| ContextProviders dual path | ✅ Complete |
| Streaming UX | ✅ Complete |
| `fin do` input panel + `--edit` | ✅ Complete |
| `@`-completion | ✅ Complete |
| `fin list` capabilities | ✅ Complete |
| Remove built-in agents | ✅ Complete |
| Client artifact-merge fix | ✅ Complete |
| Git agent (#79) | ✅ Complete |
| Observability / tracing | ✅ Complete (PR #103 + hardening + UX pass) |

**Remaining tracked items:**

- `_CONTEXT_TYPE_MAP` centralization — `AgentSpec._CONTEXT_TYPE_MAP` hardcodes tool→context mappings; tests read the private attribute
- AgentBackend protocol simplification ([#80](https://github.com/ColeB1722/fin-assist/issues/80))
- `build_user_message`/`format_context` helpers in `llm/prompts.py` are dead code
- `supported_context_types` published in agent cards, never consumed by clients
- Scoped CLI tools approval=always is not final state — per-subcommand approval is Phase A of Skills API
- Phase 4 architectural discussions — issues [#89–#94](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+is%3Aissue+89+90+91+92+93+94)

---

## Next Session

**Recommended picks (in priority order):**

1. **`fin-assist trace replay <file>`** — POST loop that re-ships JSONL lines at an OTLP endpoint so a captured trace can be re-rendered in a fresh backend. ~50 LOC. Not filed yet.
2. **Skills API Phase A — Subcommand approval rules.** Extend `ApprovalPolicy` with per-subcommand rules. `git diff` stops prompting; `git push` still asks. ~200 LOC. See "Design Sketches: Skills API" below.
3. **Retry-aware tool spans** ([#108](https://github.com/ColeB1722/fin-assist/issues/108)) — smaller; naturally follows from parallel-tool-span refactor.
4. **Re-parent `running tool` under `fin_assist.tool_execution`** — currently siblings under `fin_assist.step`, which double-counts `tool.name` queries. Needs SpanProcessor.on_start hook. No issue filed.

### Sequenced roadmap

| # | Work | Status |
|---|------|--------|
| 1 | Tracing: OTel + OpenInference bridge | ✅ Complete — follow-ups [#104-#109](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+104+105+106+107+108+109) |
| 2 | Eval harness (per-agent, not platform-level) | ⬜ Queued — rides on tracing; Phoenix eval primitives consume OTel traces |
| 3 | Skills API | 📐 Phase A sketch resolved; see below |

### Alternative picks

1. **Phase 4 design discussions** — issues [#89–#94](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+is%3Aissue+89+90+91+92+93+94)
2. **Tech debt** — `_CONTEXT_TYPE_MAP`, dead code in `llm/prompts.py`, AgentBackend simplification ([#80](https://github.com/ColeB1722/fin-assist/issues/80))
3. **Other open issues** — `gh issue list`

---

## Implementation Progress

| Phase | Description | Status |
|-------|-------------|--------|
| 1–8b | Core platform (repo setup → CLI REPL) | ✅ Complete |
| — | Config-Driven Redesign | ✅ Complete |
| — | a2a-sdk migration | ✅ Complete |
| — | Backend Extraction (AgentSpec pure config) | ✅ Complete |
| — | Auth-Required Credential Pre-Check | ✅ Complete |
| — | Reliable Server Lifecycle (fcntl PID lock) | ✅ Complete |
| — | Shared Render Pipeline | ✅ Complete |
| — | Streaming UX Refactor | ✅ Complete |
| — | Unified Executor + Tools + HITL (PR #87) | ✅ Complete |
| — | `FIN_DATA_DIR` unified path | ✅ Complete |
| — | Remove built-in agents | ✅ Complete |
| — | `fin do` + `--edit` + `--agent` | ✅ Complete |
| — | `@`-completion | ✅ Complete |
| — | `fin list` capabilities | ✅ Complete |
| — | Client artifact-merge fix | ✅ Complete |
| — | ContextSettings forwarded to tool callables | ✅ Complete |
| — | PR #87 self-review triage | ✅ Complete |
| — | Phase 4 architecture discussions | 📐 Filed as #89–#94 |
| — | Documentation sync | ✅ Complete |
| — | Git agent (#79) | ✅ Complete |
| — | Phoenix/OTel tracing (PR #103) | ✅ Complete |
| — | Telemetry Hardening Phase 2 | ✅ Complete |
| — | JSONL file exporter (#105) | ✅ Complete |
| — | Tracing UX pass (#104) | ✅ Complete |
| — | PR #103 code review fixes | ✅ Complete |
| 9b | Full SSE Streaming | ✅ Covered by a2a-sdk migration |
| 10 | Non-blocking + interactive tasks | 📐 Superseded by deferred tools |
| 11 | Multiplexer Integration | ⬜ Not Started |
| 12 | Fish Plugin | ⬜ Not Started |
| 13 | TUI Client | ⬜ Not Started |
| 14 | Testing Infrastructure (Deep Evals) | ⬜ Queued |
| 15 | Skills + MCP Integration | 📐 Phase A sketch resolved |
| 16 | Additional Agents | 🔄 Git shipped |
| 17 | Multi-Agent Workflows | ⬜ Not Started |
| 18 | Documentation | ⬜ Not Started |
| — | Nix/Home Manager packaging | 📐 Sketched |

---

## Design Sketches

### Tracing (OTel + OpenInference, shipped 2026-04-29)

Three incremental phases, all shipped:

**Phase 1 — Baseline OTel spans** (PR #103): `setup_tracing` in `hub/tracing.py` builds a vendor-agnostic `TracerProvider` + `OTLPSpanExporter`. Executor emits `fin_assist.task`, `fin_assist.step`, `fin_assist.tool_execution`, `fin_assist.approval_request`/`approval_decided` spans with OpenInference semantic convention attributes. Backends install their own instrumentation via `AgentBackend.install_tracing(provider)` hook. `hub/tracing_attrs.py` is the single source of truth for attribute/span constants.

**Phase 2 — OpenInference bridge + HITL continuity**: `agents/pydantic_ai_tracing.py` adds `OpenInferenceSpanProcessor` (translates `gen_ai.*` → `llm.*` + `openinference.span.kind=LLM`). HITL two-span model: at pause, `approval_request` span ended + `save_pause_state` persists SpanContext + user_input; at resume, new task span with `Link(prev_ctx)`, `approval_decided` child span. `TracingSettings` has `sampling_ratio`, `headers`, `event_mode`, `include_content` knobs. JSONL file exporter (`hub/file_exporter.py`) always writes to `paths.TRACES_PATH` when tracing is enabled — no config knob, toggled via `enabled`.

**Phase 3 — UX pass** (#104): CLI tracer (`cli/tracing.py`) with `cli.<command>` root spans + `HTTPXClientInstrumentor` + Baggage-propagated `fin_assist.cli.invocation_id`. `_DropSpansProcessor` filters ASGI/a2a-sdk noise. `FinAssistAttributes.TASK_STATE` enum replaces binary flag. `_scrub_span_attributes` strips `logfire.*`, `final_result`, duplicate `session.id`. One `fin do` = 1 CLI trace + 1 hub trace, ~30-40 useful spans.

**Key architectural invariants:**

- `hub/tracing.py` and `hub/executor.py` never import from `openinference.instrumentation.*` — only backends do
- `hub/tracing_attrs.py` re-exports semconv constants — treated as pure spec, not coupling
- OpenInference is semantic conventions (attribute *names* like `input.value`, `tool.name`), not a framework — any OTel backend stores spans with these attributes
- JSONL sink is always-on when tracing enabled, writes to `$FIN_DATA_DIR/traces.jsonl` via `paths.TRACES_PATH`
- `OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false` set in `__init__.py` (before a2a-sdk import) to suppress `@trace_class` noise

**Span hierarchy:**

```
HTTP POST /agents/{name}/ (FastAPI auto-instrumentation)
  └── fin_assist.task (AGENT)
        ├── fin_assist.step (CHAIN)
        │     └── chat {model} (CLIENT, via instrument_all)
        ├── fin_assist.step (CHAIN)
        │     ├── fin_assist.tool_execution (TOOL)
        │     └── chat {model} (CLIENT)
        ├── fin_assist.step (CHAIN)
        │     └── fin_assist.approval_request (TOOL, paused)
        └── (resume: new trace with Link back)
              └── fin_assist.approval_decided (TOOL)
```

**Initialization order** (`fin serve` / `fin do`):

1. Backends constructed
2. `setup_tracing(config.tracing, backends)` — builds provider, calls `backend.install_tracing(provider)` for each
3. `create_hub_app`
4. `FastAPIInstrumentor.instrument_app(app)`
5. CLI: `setup_cli_tracing(config.tracing)` — separate provider writing to same JSONL

**Follow-up issues:** [#104](https://github.com/ColeB1722/fin-assist/issues/104) (W3C traceparent), [#106](https://github.com/ColeB1722/fin-assist/issues/106) (multi-exporter), [#107](https://github.com/ColeB1722/fin-assist/issues/107) (event_mode=logs), [#108](https://github.com/ColeB1722/fin-assist/issues/108) (retry-aware tool spans), [#109](https://github.com/ColeB1722/fin-assist/issues/109) (OTLP probing), [#111](https://github.com/ColeB1722/fin-assist/issues/111) (code review quality improvements).

---

### _TaskTracer Extraction (deferred)

**Status:** Design sketched, not yet implemented.

**Problem:** `executor.py` conflates A2A task lifecycle and OTel span lifecycle. `_ExecutionContext` has 6 tracing fields out of 11 total. 8 of ~15 `Executor` methods are pure-tracing or majority-tracing. `execute()` spends ~63 lines on tracing setup before business logic starts. The interleaving hurts readability — anyone reading for the task lifecycle must mentally filter ~50% tracing boilerplate.

**Design:**

```python
class _TaskTracer:
    """Owns all OTel span lifecycle for one task invocation."""

    task_span: Span | None
    current_step_span: Span | None
    active_tool_spans: dict[str, Span]
    paused_approval_span_ctx: Any  # SpanContext
    _task_context_token: Any
    _step_context_token: Any

    def start_task_span(self, ctx: _ExecutionContext, ...) -> None: ...
    def end_task_span(self, ctx: _ExecutionContext, ...) -> None: ...
    def read_invocation_id_from_baggage(self) -> str: ...
    def detach_task_context(self) -> None: ...
    def start_step_span(self, event: StepEvent) -> None: ...
    def end_step_span(self) -> None: ...
    def start_tool_span(self, event: StepEvent) -> None: ...
    def end_tool_span(self, event: StepEvent) -> None: None: ...
    def make_link(self, trace_ctx, link_type) -> Any: ...
    def emit_approval_decided_span(self, decisions, prior_trace_ctx) -> None: ...
    def emit_approval_request_span(self, event: StepEvent) -> None: ...
```

**Changes:**

1. Move 6 tracing fields from `_ExecutionContext` into `_TaskTracer`
2. Move 8 tracing methods from `Executor` into `_TaskTracer`
3. Split mixed methods: A2A artifact/state calls stay in executor, span attribute calls delegate to tracer
4. `_ExecutionContext` becomes pure business state (task_id, raw_context_id, updater, artifact_id, user_input, created_artifacts, text_chunks)
5. `Executor.execute()` creates a `_TaskTracer` early, passes `ctx.tracer.task_span` where needed

**Expected outcome:** `execute()` shrinks from ~135 lines to ~50 lines (business flow only). `_ExecutionContext` docstring focuses on business state. Tracing logic is independently testable.

**Risk profile:** Structural refactor of the most critical path. If it introduces a regression in span parenting or context token management, tracing silently degrades (no test failures, just missing/wrong spans). The current interleaving is ugly but stable.

**Why deferred:** Current PR delivers core value (tracing_shared dedup, get_user_input fix, prep extracts). `_TaskTracer` is readability improvement, not correctness. Better as a dedicated PR with focused review.

---

### Skills API: sequenced refactor (Phase 15 breakdown)

**Status:** Sketch resolved 2026-04-27. Ready to start Phase A.

**Why this exists:** scoped CLI + WorkflowConfig pattern from the git agent is a prototype for the broader Skills API. Split into three sequenced phases, each independently shippable.

**Grounding citations:**

- Scoped CLI prototype + TODO for per-subcommand approval: `src/fin_assist/agents/tools.py:213`, `src/fin_assist/agents/tools.py:295`
- Current `ApprovalPolicy` shape (only `never`/`always`, no rules): `src/fin_assist/agents/tools.py:40`
- `AgentConfig.tools` flat list of names: `src/fin_assist/config/schema.py:99`
- Skills API vision: `docs/architecture.md:991`–`:1007`

---

#### Phase A — Subcommand approval rules

**Goal:** `git diff` runs un-gated; `git push` still asks. Aligned with TODO at `tools.py:213`.

**Design:**

```python
@dataclass
class ApprovalRule:
    pattern: str            # fnmatch glob against full args string
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

- `src/fin_assist/agents/tools.py:40` — extend `ApprovalPolicy`
- `src/fin_assist/agents/tools.py:295` — `_make_scoped_cli` callable queries `policy.evaluate(args)` per call
- Backend adapter — switch from static `requires_approval` to per-call evaluation
- Rules still Python-defined in `create_default_registry()` — no config schema change yet

**TDD tests:**

- `test_approval_policy_evaluate.py`: pattern matching, first-match-wins, fallback to `mode`, empty rules
- `test_tools_scoped_cli_approval.py`: `git diff` → never, `git push origin main` → always
- Executor integration: deferred `StepEvent` emitted only when `evaluate()` returns `always`

**Exit gate:** through the git agent, `git diff` runs without prompt; `git push` still pauses.

---

#### Phase B — Skill bundling (ToolDefinition → SkillDefinition)

**Goal:** one TOML object bundles a scoped CLI + its approval rules + named scripts + workflows.

**Design (TOML shape):**

```toml
[skills.git]
type = "cli"
prefix = "git"
description = "Run any git subcommand."

[skills.git.approval]
default = "always"
rules = [
  { pattern = "diff*",   mode = "never" },
  { pattern = "status*", mode = "never" },
  { pattern = "log*",    mode = "never" },
]

[skills.git.scripts.pr-checklist]
description = "Print the PR review checklist"
path = "scripts/git/pr-checklist.sh"
approval = "never"

[skills.git.workflows.commit]
description = "Generate a conventional commit message."
prompt_template = "git-commit"
entry_prompt = "Analyze the current staged and unstaged changes..."
```

**Touchpoints:** new `src/fin_assist/skills/` package (definition, loader, registration), `config/schema.py` add `skills: dict[str, SkillConfig]`, migrate workflows from `AgentConfig` to `SkillConfig`, update `cli/main.py` workflow resolution.

**Exit gate:** config.toml defines `skills.git` with rules + scripts; second skill authored end-to-end in TOML as validation.

---

#### Phase C — Tool-type primitive

**Goal:** `type: Literal["cli", "mcp", ...]` as first-class field, with type-specific OTel span attributes.

**Gate for starting Phase C:** a second tool type has a concrete consumer. Most likely MCP ([#84](https://github.com/ColeB1722/fin-assist/issues/84)). **Do not start speculatively.**

**Design:** `ToolTypeAdapter` protocol with `span_attributes()`, `invoke()`, `load_from_config()`. `ToolDefinition.type` field. Global `ToolTypeRegistry`. OTel instrumentation lives in the adapter, not the callable. `fin list tool-types` CLI surface.

**Exit gate:** two type adapters landed end-to-end, span semantics verified in OTel backend.

---

#### Sequencing summary

| Phase | Ship | Blocks on | Real consumer |
|---|---|---|---|
| A | Per-subcommand approval | — | Git agent UX today |
| B | Skill object (TOML-authored, workflows migrated) | Phase A | User-authored skills |
| C | Tool-type taxonomy + adapter pattern | Phase B + real second type | MCP integration |

#### Skills vs. `context/` overlap

`GitContext` duplicates what the `git` scoped CLI tool does. With per-subcommand approval (Phase A), `@git:diff` can resolve through the skill (diff → `never` approval). `FileFinder` and `ShellHistory` remain as `ContextProvider`s — they have search/get_item semantics, not CLI-wrapper semantics.

---

## Historical Reference

Key completed milestones. See git log for full detail; code is the source of truth.

### PR #103 Code Review Fixes (2026-04-30)

Addressed all 21 review comments across 6 themes:

1. **Framework agnosticism** — rewrote docstrings across all tracing files to use vendor-neutral language; explained OpenInference = semantic conventions, not a framework
2. **Docstring verbosity** — stripped conversational comments, private cross-references, Phoenix-specific editorializing
3. **Legacy cleanup** — removed `ALTER TABLE` migration sniffing, removed `save_trace_context`/`load_trace_context` methods, renamed to `save_pause_state`/`load_pause_state`
4. **Config simplification** — removed `file_path` from `TracingSettings`; JSONL sink always-on via `paths.TRACES_PATH` when tracing enabled; removed `FIN_TRACING__FILE_PATH` env var
5. **OTel conceptual clarity** — added docstrings explaining OTel Links, force_flush/shutdown lifecycle, duplicate span tradeoff
6. **Argparse cleanup** — replaced `getattr(args, "agent", None) or ""` with `args.agent or ""` via `set_defaults(agent=None)`

4 new tests added (876 → 880). `just ci` green.

### Git Agent + Scoped CLI Tools (#79, 2026-04-27)

First real end-user agent. Scoped CLI tools (`git`, `gh`), WorkflowConfig (agent-scoped prompt steering), three workflows (commit, PR, summarize).

### Tier 1 Features + Doc Sync (2026-04-27)

`@`-completion, `fin list`, `fin do` input panel + `--edit`, remove built-in agents, client artifact-merge fix, ContextSettings forwarding, doc sync.

### Unified Executor & Agent Platform (PR #87, 2026-04-24→26)

Unified executor loop, tool calling, dual-path context, HITL approval, OTel-ready step boundaries. Platform owns abstractions, backends adapt them.

### Streaming UX Refactor (2026-04-23)

Backend streams `StreamDelta(kind, content)`. Shared `render_stream()` with Rich Live. Both `do` and `talk` use same pipeline.

### AgentBackend Extraction (2026-04-21)

`AgentSpec` → pure config. All pydantic-ai knowledge in `PydanticAIBackend`. Executor has zero pydantic-ai imports.

### fasta2a → a2a-sdk Migration (2026-04-20)

Full migration to Google's `a2a-sdk` v1.0.0. `TaskUpdater` for state transitions, `InMemoryTaskStore` + SQLite `ContextStore`.

### Config-Driven Redesign (2026-04-11)

Agents from class-hierarchy to `ConfigAgent` driven by TOML. `ServingMode`, `OUTPUT_TYPES`, `SYSTEM_PROMPTS` registries.

### Auth-Required Credential Pre-Check (2026-04-03)

`MissingCredentialsError` before LLM call. A2A `auth-required` state. Client renders credential panel.

### Reliable Server Lifecycle (2026-04-09)

`fcntl.flock()` PID file, `atexit` + SIGTERM cleanup, lock-based stale detection.

### Early Platform Setup (2026-03-25 → 2026-04-08)

Phases 1–8b: repo setup, LLM module, credentials, context module, agent protocol, hub server, CLI client, REPL.

---

## Context for Fresh Session

1. Read this file for current state
2. Read `docs/architecture.md` for full architecture
3. Read `AGENTS.md` for development patterns
4. Check "Implementation Progress" table
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
- Server binds to `127.0.0.1` only
- A2A protocol via a2a-sdk v1.0
- Multi-path routing: N agents at `/agents/{name}/`
- SQLite for context storage; `InMemoryTaskStore` for A2A tasks (ephemeral)
- Server lifecycle: fcntl-locked PID file
- `AgentSpec` is pure config; all LLM coupling in `PydanticAIBackend`
- Platform types in `agents/` have zero `hub/` imports by design
- `@`-completion is the sole user-driven context path; `--file`/`--git-diff` removed
- Scoped CLI tools (`git`, `gh`) are the prototype for Skills API
- JSONL trace sink always-on when tracing enabled, writes to `$FIN_DATA_DIR/traces.jsonl`
- `OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false` set in `__init__.py` to suppress a2a-sdk noise
