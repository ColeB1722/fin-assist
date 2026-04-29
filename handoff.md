# Handoff Document

Rolling context for session handoffs. Updated as checkpoints are reached.

**Current state (2026-04-29)**: 837 tests passing, `just ci` green (format, lint, typecheck, test). Git agent (#79) shipped with scoped CLI tools (`git`, `gh`) and workflow config. All Tier 1 features shipped. OTel tracing shipped (PR #103). **Telemetry Hardening Phase 2 complete**: Phoenix-friendly attributes, HITL two-span trace continuity, OpenInference bridge, vendor-agnostic `setup_tracing`. Follow-ups filed as [#104-#109](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+104+105+106+107+108+109). Phase 4 architectural discussions filed as issues [#89–#94](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+is%3Aissue+89+90+91+92+93+94). See "Design Sketches: Telemetry Hardening — Phase 2" below for architecture.

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
| Observability / tracing | ✅ Complete (PR #103 + Phase 2 hardening 2026-04-29) — OTel spans, OpenInference bridge, HITL trace continuity; see "Design Sketches: Telemetry Hardening — Phase 2" |

**Remaining tracked items:**

- `_CONTEXT_TYPE_MAP` centralization — `AgentSpec._CONTEXT_TYPE_MAP` hardcodes tool→context mappings; tests read the private attribute.
- AgentBackend protocol simplification ([#80](https://github.com/ColeB1722/fin-assist/issues/80))
- `build_user_message`/`format_context` helpers in `llm/prompts.py` are dead code
- `supported_context_types` published in agent cards, never consumed by clients
- Phase 4 architectural discussions — issues [#89–#94](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+is%3Aissue+89+90+91+92+93+94)
- Scoped CLI tools approval=always is not final state — per-subcommand approval is Phase A of the sequenced Skills API plan (see "Design Sketches: Skills API" below)

---

## Next Session

**Recommended picks (in priority order):**

1. **CLI-side OTel propagation** ([#104](https://github.com/ColeB1722/fin-assist/issues/104)) — closes the trace loop. Today a CLI command → hub task chain shows only the hub side. Wire a `TracerProvider` into the CLI process, inject `traceparent` via `HubClient`, watch the CLI command span become the parent of `fin_assist.task`. ~150 LOC, TDD-first. High user-visible value + completes the telemetry story.
2. **Skills API Phase A — Subcommand approval rules.** Extend `ApprovalPolicy` with per-subcommand rules, update scoped CLI callables to evaluate policy per call, update backend adapter. `git diff` stops prompting; `git push` still asks. ~200 LOC. See "Design Sketches: Skills API" Phase A below.
3. **Retry-aware tool spans** ([#108](https://github.com/ColeB1722/fin-assist/issues/108)) — smaller; naturally follows from the parallel-tool-span refactor in Phase 2.

### Sequenced roadmap (why this order)

| # | Work | Rationale |
|---|------|-----------|
| 1 | **Tracing: Phoenix + OTel** | ✅ Complete (PR #103 + Phase 2 hardening 2026-04-29). Baseline OTel spans, OpenInference bridge for Phoenix rendering, HITL two-span trace continuity via ContextStore, vendor-agnostic `setup_tracing`. ~900 LOC + 143 tracing tests. Follow-ups [#104-#109](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+104+105+106+107+108+109). See "Design Sketches: Telemetry Hardening — Phase 2" below. |
| 2 | **Eval harness (per-agent, not platform-level)** | Evals are downstream of observability when using Phoenix. Two real agents exist (test + git) — eval criteria are meaningful. Platform stance: evals live at the agent level (`tests/evals/<agent>/`). Closes [#14](https://github.com/ColeB1722/fin-assist/issues/14). Likely surfaces [#80](https://github.com/ColeB1722/fin-assist/issues/80) (AgentBackend simplification). |
| 3 | **Skills API** | Generalizes the scoped CLI tools + workflow config pattern from the git agent. Per-subcommand approval, context templates, skill auto-discovery. See the Skills API GitHub issue for the full vision. |

**Why tracing before skills:** `step_start`/`step_end` are now wired to OTel spans in `executor.py`. Skills Phase A adds per-call approval evaluation; Phase B adds skill-loaded tool-surface swapping. Each new feature makes the instrumentation surface more complex — wiring it while the boundary was clean paid off.

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
| 14 | Testing Infrastructure (Deep Evals) — per-agent eval harness, rides on Phoenix traces | ⬜ Queued — tracing shipped, evals can start |
| 15 | Skills + MCP Integration | 📐 Scoped CLI tools + WorkflowConfig shipped (git agent); sequenced Phase A/B/C sketch resolved 2026-04-27 — see "Design Sketches" below |
| 16 | Additional Agents | 🔄 Git agent shipped; SDD/TDD/code review pending |
| 17 | Multi-Agent Workflows | ⬜ Not Started |
| 18 | Documentation | ⬜ Not Started |
| — | Phoenix/OTel tracing | ✅ Complete (2026-04-29, PR #103) |
| — | Nix/Home Manager packaging | 📐 Sketched |

---

## Design Sketches

### Telemetry Hardening — Phase 2 (complete, 2026-04-29)

**Status:** ✅ **Complete**. All 9 TDD steps landed; 837/837 tests passing; `just ci` green (format, lint, typecheck, test). 6 follow-up issues filed (#104-#109) for explicitly out-of-scope items.

**Shipped in this phase:**

| Piece | File | Notes |
|---|---|---|
| Vendor-agnostic `setup_tracing` | `hub/tracing.py` | Accepts `backends=…`, honors `OTEL_EXPORTER_OTLP_*` env, wires sampler + headers, returns the provider. No Phoenix/Logfire-specific code. |
| OpenInference semconv constants module | `hub/tracing_attrs.py` (new) | Re-exports `SpanAttributes`, `OpenInferenceSpanKindValues`, `OpenInferenceMimeTypeValues` + platform namespace `FinAssistAttributes` + `SpanNames`. Single source of truth. |
| pydantic-ai → OpenInference bridge | `agents/pydantic_ai_tracing.py` (new) | `install_pydantic_ai_instrumentation(provider, include_content, event_mode)`; idempotent via WeakSet + `_agent_instrumented` flag; passes `tracer_provider=provider` explicitly to `InstrumentationSettings` to avoid global-provider recursion in tests. |
| Backend tracing hook | `agents/backend.py` | `PydanticAIBackend.install_tracing(provider, *, include_content, event_mode)`; Protocol documents it as optional (hub uses `hasattr`). |
| Executor refactor | `hub/executor.py` | Every hand-typed attr swapped for constants; `active_tool_spans: dict[tool_call_id, Span]` for parallel tool safety; `record_exception` on failure paths; canonical `application/json` mime type; two-span HITL model. |
| HITL two-span flow | `hub/executor.py` + `hub/context_store.py` | At pause: emit `fin_assist.approval_request`, persist SpanContext via `ContextStore.save_trace_context`. At resume: load prior context, attach `Link(prev_ctx, type=resume_from_approval)` to new task span, emit `fin_assist.approval_decided` as first child with decision + Link back to `approval_request`. |
| ContextStore trace-context table | `hub/context_store.py` | New `trace_contexts` table (SQLite auto-migrates on open); hex-encoded trace/span ids for readability; upsert semantics. |
| `TracingSettings` schema knobs | `config/schema.py` | `sampling_ratio`, `headers`, `event_mode`, `include_content` — with validators and rich docstring. |
| CLI wiring | `cli/main.py` | Removed stray `Agent.instrument_all()`; builds backends before `setup_tracing`; passes them into the tracing call and into `create_hub_app` via `backend_factory`. |

**Original pain points, now addressed:**

1. ~~Phoenix breaks when clicking `fin_assist.approval` / `fin_assist.tool_execution` spans~~ → canonical `application/json` mime type; `approval` renamed to `approval_request` with proper attributes.
2. ~~HITL causes the trace to split into two unrelated traces~~ → two-span model with `Link`s; `ContextStore.save_trace_context` persists the pause context across processes.
3. ~~LLM span attributes render as raw JSON with `kind: unknown`~~ → `OpenInferenceSpanProcessor` translates `gen_ai.*` → `llm.*` + `openinference.span.kind=LLM` at span end.

**Design principles retained** (from original sketch, still relevant for reviewers):

**Root causes (from survey 2026-04-29):**

- pydantic-ai's `Agent.instrument_all()` emits **OTel GenAI** attributes (`gen_ai.input.messages`, `gen_ai.output.messages`, ...) — not **OpenInference** (`llm.input_messages.0.message.role`, `openinference.span.kind=LLM`, ...). Phoenix only renders LLM spans natively when OpenInference attrs are present ([confirmed in Phoenix #10753](https://github.com/Arize-ai/phoenix/issues/10753)). The two conventions overlap but are not equivalent; the GenAI content blob is what users currently see as "kind: unknown + raw JSON."
- `executor.py:341` calls `ctx.task_span.end()` before the approval is answered, `ContextStore` never persists trace context, and the CLI doesn't inject W3C `traceparent`. Any one of those kills the trace; all three compound.
- Hand-typed OpenInference attribute strings (`"openinference.span.kind"`, `"input.value"`, ...) drift silently from the actual spec.

**Guiding principles (from 2026-04-29 discussion):**

1. **Backend-owned instrumentation.** Platform tracing (`hub/tracing.py`, `executor.py`) is pure OTel. LLM-framework → OpenInference translation is the **backend's** job, attached via a new `AgentBackend.install_tracing(provider)` hook at construction. A future `LangChainBackend` brings its own translator the same way.
2. **Vendor-agnostic core.** No `phoenix.otel.register()`, no `logfire.configure()`, no Phoenix-specific assumptions in the tracing module. Honor standard `OTEL_EXPORTER_OTLP_*` env vars so swapping backends is a config change, not a code change.
3. **Additive, not substitutive.** The OpenInference bridge *adds* `llm.*` / `openinference.span.kind` attributes on top of `gen_ai.*` — it doesn't remove them. Vanilla OTel consumers still see standard GenAI semconv; Phoenix users get the richer shape.
4. **All known gaps scoped or issue-filed.** Nothing silently deferred.

---

#### New architecture

```
┌─────────────────────────── hub/tracing.py (vendor-agnostic) ───────────────────────────┐
│ setup_tracing(config, backends):                                                       │
│   1. Build Resource (service.name, openinference.project.name)                         │
│   2. Build exporter(s): FIN_TRACING__* overrides OTEL_EXPORTER_OTLP_* overrides defaults│
│   3. Provider.add_span_processor(_TruncatingSpanProcessor(BatchSpanProcessor(exporter)))│
│   4. for backend in backends: backend.install_tracing(provider)  ← NEW                 │
│   5. FastAPIInstrumentor.instrument_app(app) still lives in cli/main.py                │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                            │
                              install_tracing(provider)
                                            ▼
┌────────────── agents/backend.py ───────────────┐   ┌── agents/pydantic_ai_tracing.py ──┐
│ AgentBackend protocol:                         │   │ (NEW, only pulled in by           │
│   def install_tracing(self, provider) -> None: │   │  PydanticAIBackend)               │
│     ... = no-op (default via mixin/base)       │   │                                   │
│                                                │   │ - Adds OpenInferenceSpanProcessor │
│ PydanticAIBackend.install_tracing:             │   │   (from openinference-            │
│   - import openinference.instrumentation.      │──▶│   instrumentation-pydantic-ai)   │
│     pydantic_ai                                │   │ - Calls Agent.instrument_all(     │
│   - provider.add_span_processor(...)           │   │     InstrumentationSettings(      │
│   - Agent.instrument_all(settings)             │   │       include_content=True))      │
└────────────────────────────────────────────────┘   └───────────────────────────────────┘
                                            │
                                            ▼
┌──────────────────────────── hub/executor.py (pure OTel) ───────────────────────────┐
│ from fin_assist.hub.tracing_attrs import SpanAttr, SpanKind                        │
│                                                                                    │
│ fin_assist.task    (AGENT)                                                         │
│ fin_assist.step    (CHAIN)                                                         │
│ fin_assist.tool_execution  (TOOL) — dict keyed by tool_call_id (parallel-safe)     │
│ fin_assist.approval        (TOOL) — now a DURATION span, ended on resume w/        │
│                                    decision=approved|denied|overridden            │
│                                                                                    │
│ HITL: on pause → save_trace_context in ContextStore                                │
│       on resume → Link(prev_span_ctx) on new task span                             │
│ Errors: record_exception + set_status on every span on failure path                │
└────────────────────────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
┌──────────────────── hub/context_store.py (schema v2) ────────────────────┐
│ contexts(context_id PRIMARY KEY, data BLOB NOT NULL,                      │
│          trace_id TEXT, span_id TEXT, trace_flags INT)       ← NEW cols   │
│ async save_trace_context(context_id, span_context) -> None                │
│ async load_trace_context(context_id) -> SpanContext | None                │
│                                                                           │
│ Migration: ALTER TABLE on first connect — old rows get NULL trace cols.   │
└───────────────────────────────────────────────────────────────────────────┘
```

**Key invariant:** `hub/executor.py` and `hub/tracing.py` never import from `openinference.instrumentation.*`. Only backends do. The semconv **constants** (`openinference.semconv.trace.SpanAttributes`) are allowed in `executor.py` since they're a pure spec re-export, not an instrumentor — treated the same as `opentelemetry.semconv.resource.ResourceAttributes`.

---

#### Files touched

| File | Change |
|------|--------|
| `pyproject.toml` | Add `openinference-semantic-conventions>=0.1` and `openinference-instrumentation-pydantic-ai>=0.1` as **runtime** deps (both small, no heavy transitive) |
| `src/fin_assist/hub/tracing_attrs.py` | **NEW** — thin re-export of `SpanAttributes`, `OpenInferenceSpanKindValues`, `OpenInferenceMimeTypeValues`. Everything in executor imports from here. |
| `src/fin_assist/hub/tracing.py` | Accept `backends: Sequence[AgentBackend] = ()`. Honor `OTEL_EXPORTER_OTLP_ENDPOINT` / `_HEADERS` / `_PROTOCOL` as fallbacks (FIN_TRACING__* wins). Call `backend.install_tracing(provider)` for each. Drop Phoenix-specific `_probe_phoenix` — generalize to `_probe_endpoint` based on config (or remove; see issues). |
| `src/fin_assist/agents/backend.py` | Add `install_tracing(self, provider) -> None` to `AgentBackend` Protocol (optional — default no-op via `hasattr` check in tracing.py so existing fakes don't need updates). `PydanticAIBackend.install_tracing` delegates to the new module below. |
| `src/fin_assist/agents/pydantic_ai_tracing.py` | **NEW** — `install_pydantic_ai_instrumentation(provider)` adds `OpenInferenceSpanProcessor` and calls `Agent.instrument_all(InstrumentationSettings(include_content=True))`. Only module that imports `openinference.instrumentation.pydantic_ai` and `pydantic_ai.Agent`. |
| `src/fin_assist/hub/executor.py` | Switch every hand-typed OpenInference attr key to the semconv constant. Change `current_tool_span: Span \| None` → `active_tool_spans: dict[str, Span]` keyed by `tool_call_id`. Start/end tool spans as context-attached (not just `context=`) so pydantic-ai LLM spans inside the tool become children. Call `record_exception` + `set_status(ERROR)` on every open span in the exception path. Rework `fin_assist.approval` span: start on pause, **don't end it yet** (it's the wall-clock duration of the approval gate), persist its span context, end it on resume with `decision=` set. Resume path: load persisted trace context, create task span with `Link(prev_ctx)`, also ends the approval span (loading it by span_id via context_store). |
| `src/fin_assist/hub/context_store.py` | Schema migration: add `trace_id`, `span_id`, `trace_flags` columns. New methods `save_trace_context`, `load_trace_context`. |
| `src/fin_assist/cli/main.py` | Remove the `Agent.instrument_all()` call from `_serve_command` — moved to backend. Still calls `setup_tracing(config.tracing, backends=...)` and `FastAPIInstrumentor.instrument_app(app)`. Order becomes: configure_logging → construct agents → construct backends → setup_tracing(config, backends) → create_hub_app → FastAPIInstrumentor. |
| `src/fin_assist/hub/factory.py` / `hub/app.py` | Plumb backend instances through so `setup_tracing` can call `install_tracing` on each. Minor: expose a `backends()` accessor on the hub app or collect them before mounting. |
| `src/fin_assist/config/schema.py` | `TracingSettings`: add `sampling_ratio: float = 1.0`, `headers: dict[str, str] = {}`, `event_mode: Literal["attributes", "logs"] = "attributes"`, `include_content: bool = True`. Document that `OTEL_EXPORTER_OTLP_*` are honored as fallbacks. |
| `tests/test_hub/test_tracing.py` | Replace string literals with semconv constants. Add test cases for: (a) LLM span translation via OpenInferenceSpanProcessor (fake gen_ai span → verify llm.* attrs added), (b) parallel tool spans don't clobber, (c) exceptions recorded on all open spans, (d) approval span is a duration span, (e) HITL pause persists trace context, (f) HITL resume creates linked task span. |
| `tests/test_hub/test_context_store.py` | New tests for `save_trace_context` / `load_trace_context` + migration. |
| `tests/test_agents/test_pydantic_ai_tracing.py` | **NEW** — backend.install_tracing adds the processor and configures Agent. |
| `tests/conftest.py` | `tracing_setup` fixture unchanged. Add `trace_context_factory` helper for HITL tests. |

**Estimated:** ~3 new source files, ~7 modified, ~2 new test files, ~600 LOC + tests.

---

#### HITL flow (new)

```
CLIENT (CLI) ──1. send_message "run git push"──▶ HUB
                                                  │
                                                  ▼
                                          fin_assist.task (trace_id=T1)
                                            ├── fin_assist.step
                                            └── fin_assist.approval (STARTED, held open)
                                                  │ persist SpanContext(T1, approval_span_id)
                                                  │ via context_store.save_trace_context
                                                  ▼
                                          requires_input()
CLIENT ◀──2. task state: paused, approval widget──
CLIENT ──3. approval_result: approved────────────▶ HUB
                                                  │
                                                  │ context_store.load_trace_context → (T1, approval_span_id)
                                                  ▼
                                          fin_assist.task (trace_id=T2)
                                            ├── links = [Link((T1, approval_span_id),
                                            │            {fin_assist.link.type = "resume_from_approval"})]
                                            │
                                            │ ALSO: end the approval span remotely:
                                            │   — we can't re-enter a span from another process,
                                            │     but we CAN record a "resume" span event on
                                            │     it via the exporter? → NO, spans are already
                                            │     exported by BatchSpanProcessor.
                                            │
                                            │ PIVOT: approval span is ended at pause time
                                            │ (closing the original trace cleanly),
                                            │ decision is captured as a fin_assist.approval.decided
                                            │ span on the RESUME trace, linked back to the
                                            │ paused approval span.
                                            ▼
```

**Refined design after tracing semantics check:** OTel spans can't be resumed across processes (spans are written by BatchSpanProcessor at `end()` time). So:

- **At pause:** start `fin_assist.approval_request` span, set `fin_assist.approval.status=pending`, end it immediately but with `span_event("paused")` marker. Persist its SpanContext.
- **At resume:** start new trace (T2) with the old task-span context as a Link. As its first child, start `fin_assist.approval_decided` span with `fin_assist.approval.decision=approved|denied|overridden`, and a **second Link** back to the paused approval_request span. Phoenix renders both traces side-by-side, clickable links between them.

This mirrors how OTel recommends modeling async boundaries (see OTel [Links in the trace API](https://opentelemetry.io/docs/specs/otel/trace/api/#link)). One trace per HTTP request, explicit semantic link between them.

---

#### Config & env

| Source | Precedence | Example |
|--------|-----------|---------|
| init kwargs | highest | (tests) |
| `FIN_TRACING__*` env | | `FIN_TRACING__ENDPOINT=https://otel.example.com/v1/traces` |
| `OTEL_EXPORTER_OTLP_*` env | | `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` |
| `config.toml` `[tracing]` | | `endpoint = "http://localhost:6006/v1/traces"` |
| schema defaults | lowest | `http://localhost:6006/v1/traces` |

Point: nothing in the code knows whether you're targeting Phoenix, Tempo, Jaeger, Logfire, or a self-written renderer. Picking one is config only. The `openinference-instrumentation-pydantic-ai` bridge is always on when the PydanticAI backend is loaded — that's independent of the collector endpoint.

---

#### Out of scope (filed as GH issues)

| # | Topic | Issue |
|---|-------|-------|
| 1 | CLI-side OTel + W3C traceparent propagation | [#104](https://github.com/ColeB1722/fin-assist/issues/104) |
| 2 | `cli.trace` JSONL exporter for offline trace debugging | [#105](https://github.com/ColeB1722/fin-assist/issues/105) |
| 3 | Multi-exporter tracing (Phoenix + OTLP + file at once) | [#106](https://github.com/ColeB1722/fin-assist/issues/106) |
| 4 | Configurable `event_mode=logs`: plumb OTel LoggerProvider | [#107](https://github.com/ColeB1722/fin-assist/issues/107) |
| 5 | Retry-aware tool spans (`tool.retry_attempt`) | [#108](https://github.com/ColeB1722/fin-assist/issues/108) |
| 6 | Generalize `_probe_phoenix`: OTLP connectivity probing | [#109](https://github.com/ColeB1722/fin-assist/issues/109) |

---

### Phoenix + OTel Tracing

**Status:** Implemented 2026-04-29 (PR #103).

**Why this exists:** `step_start`/`step_end` now drive OTel span boundaries in `executor.py`. The git agent provides real multi-step tool-call + deferred-approval flows to observe. `Agent.instrument_all()` gives us pydantic-ai framework-layer spans for free. FastAPI auto-instrumentation provides the HTTP transport layer. Wiring instrumentation before Skills Phase A/B (per-call approval, tool-surface swapping) kept the boundary clean.

**Grounding citations:**

- `step_start`/`step_end` handling: `src/fin_assist/hub/executor.py`
- `StepEvent` kinds and `content` contract: `src/fin_assist/agents/step.py`
- `_PydanticAIStepHandle.__aiter__()` emits step boundaries: `src/fin_assist/agents/backend.py`
- `ApprovalPolicy` (two-mode, no rules): `src/fin_assist/agents/tools.py`
- Hub app factory (init order): `src/fin_assist/hub/app.py`
- Agent card + extension: `src/fin_assist/hub/factory.py`

---

#### Two-layer instrumentation

pydantic-ai has built-in `Agent.instrument_all()` that emits OTel spans for model requests, tool calls, and token usage. We get the LLM-layer for free. Our platform layer adds spans the framework can't know about — task lifecycle, approval gates, step boundaries, and agent identity.

| Layer | What it traces | Mechanism |
|-------|---------------|-----------|
| **HTTP transport** (FastAPI) | Every request to the hub: method, route, status code, duration | `opentelemetry-instrumentation-fastapi` auto-instrumentation |
| **Framework** (pydantic-ai) | Model requests, token usage, tool invocations | `Agent.instrument_all()` — emits `chat {model}` CLIENT spans with `gen_ai.*` attributes |
| **Platform** (fin-assist) | Task lifecycle, step boundaries, approval decisions, agent identity | Manual OTel spans in Executor — emits spans under `fin_assist.*` with OpenInference attributes |

Each layer is a child of the one above. In Phoenix, a trace looks like:

```text
HTTP POST /agents/git/ (FastAPI auto-instrumentation)
  └── fin_assist.task (AGENT, input="commit my changes", output="Done!", session_id=xyz)
        ├── fin_assist.step (CHAIN, step=0)
        │     └── chat claude-sonnet-4-6 (CLIENT, gen_ai.input.messages, gen_ai.output.messages, tokens=...)
        ├── fin_assist.step (CHAIN, step=1)
        │     ├── fin_assist.tool_execution (TOOL, tool.name=git, input.value={"args":"status"}, output.value="M file.py")
        │     └── chat claude-sonnet-4-6 (CLIENT)
        ├── fin_assist.step (CHAIN, step=2)
        │     └── fin_assist.approval (TOOL, tool.name=git, input.value={"args":"push"}, decision=pending)
        └── (task span ended with output.value and result_type)
```

#### Span hierarchy

| Span name | OpenInference kind | Parent | Key attributes |
|-----------|-------------------|--------|----------------|
| `HTTP {method} {route}` | SERVER | (root) | Auto-generated by FastAPI instrumentation |
| `fin_assist.task` | AGENT | HTTP span | `input.value`, `output.value`, `session.id`, `gen_ai.agent.name`, `fin_assist.task.id` |
| `fin_assist.step` | CHAIN | `fin_assist.task` | `fin_assist.step.number` |
| `fin_assist.tool_execution` | TOOL | `fin_assist.step` | `tool.name`, `input.value`, `input.mime_type`, `output.value` |
| `fin_assist.approval` | TOOL | `fin_assist.step` (deferred) | `tool.name`, `input.value`, `input.mime_type`, `fin_assist.approval.decision` |

#### Where spans are created

**Executor (`hub/executor.py`)** — owns the platform span layer:

- `_setup_task()` → start `fin_assist.task` span, set `agent.name`, `task.id`, `context.id`
- `_consume_events()` → dispatch:
  - `step_start` → start `fin_assist.step` child span
  - `step_end` → end current `fin_assist.step` span
  - `tool_call` → start `fin_assist.tool_execution` child span
  - `tool_result` → end `fin_assist.tool_execution` span, set exit/duration attrs
  - `deferred` → start `fin_assist.approval` child span, set attributes, end span
  - `text_delta`/`thinking_delta` → no span (content within step span)
- `_finalize()` → end `fin_assist.task` span, set `task.result_type`, `task.step_count`
- `_pause_for_approval()` → end `fin_assist.task` span, tag with `task.paused_for_approval=true`

**Backend (`agents/backend.py`)** — sets span context the Executor can't see:

- `PydanticAIBackend._build_model()` → set `model.name`, `model.provider` on the current span
- `_PydanticAIStepHandle.__aiter__()` → no change; pydantic-ai's `instrument_all()` picks up the current span via OTel context automatically

**No span creation in `agents/` package.** Platform types (`StepEvent`, `StepHandle`, `ApprovalPolicy`) remain framework-agnostic with zero OTel imports. The Executor (in `hub/`) is the instrumentation boundary.

#### OTel context propagation

OTel Python uses `contextvars.ContextVar` for context storage — automatic isolation across asyncio tasks. When the Executor creates a span with `tracer.start_as_current_span()`, the span becomes current in the async context. All downstream code (including pydantic-ai's `instrument_all()`) reads it via `trace.get_current_span()`. No manual propagation needed.

Key: `_PydanticAIStepHandle.__aiter__()` runs inside the executor's async context. When pydantic-ai emits a `model_request` span during `node.stream(run.ctx)`, it automatically becomes a child of our `fin_assist.step` span.

#### OTel initialization

New module: `src/fin_assist/hub/tracing.py`

```python
def setup_tracing(config: TracingSettings) -> None:
    """Initialize OTel TracerProvider with OTLP exporter.
    
    Called once at hub startup, after configure_logging().
    No-op if tracing is disabled.
    """
```

Initialization order in `fin serve`:
1. `configure_logging()` (existing)
2. `setup_tracing(config.tracing)` (new)
3. `Agent.instrument_all()` (new — enables pydantic-ai framework spans)
4. `FastAPIInstrumentor.instrument_app(app)` (new — enables HTTP transport spans)
5. `create_hub_app()` (existing)

**Raw OTel setup, not `phoenix.otel.register()`.** The convenience wrapper couples us to Phoenix's API. Raw `TracerProvider` + `OTLPSpanExporter` is ~10 lines, works with any OTel backend, and future-proofs for Jaeger/Tempo/etc.

#### Configuration

**Config schema addition:**

```python
class TracingSettings(BaseModel):
    """OpenTelemetry tracing configuration."""
    enabled: bool = False
    endpoint: str = "http://localhost:4317"  # OTLP gRPC (Phoenix default)
    exporter_protocol: Literal["grpc", "http"] = "grpc"
    project_name: str = "fin-assist"
```

**Config TOML:**

```toml
[tracing]
enabled = true
endpoint = "http://localhost:4317"
```

**Env overrides (pydantic-settings, double-underscore):**

- `FIN_TRACING__ENABLED=true`
- `FIN_TRACING__ENDPOINT=http://localhost:4317`
- `FIN_TRACING__EXPORTER_PROTOCOL=grpc`

Tracing config is only needed at hub startup, after pydantic loads, so no bootstrap env var is needed.

#### Phoenix integration

**Launch model: standalone, not embedded.** Phoenix runs as its own process on port 6006 (UI) + 4317 (gRPC). It's a data-plane dependency, not a code dependency.

**Graceful degradation when Phoenix isn't running:** `BatchSpanProcessor` handles this — non-blocking, background thread, silently drops spans if the OTLP endpoint is unreachable. Only downside is noisy warning logs. Mitigation:

1. One-time startup probe: `httpx.get("http://localhost:6006/healthz", timeout=2)` at init, log the result (reachable/unreachable), but continue regardless.
2. Optionally suppress OTel's noisy per-batch logging: `logging.getLogger("opentelemetry").setLevel(logging.CRITICAL)`.

If Phoenix comes up after the hub, traces start flowing on the next export cycle. No restart needed.

**Dev workflow:**

1. `phoenix serve` (or `devenv up` with a `processes.phoenix.exec = "phoenix serve"` entry)
2. `FIN_TRACING__ENABLED=true` (or `[tracing] enabled = true` in config.toml)
3. `fin serve` → traces flow to Phoenix

#### Dependencies

```toml
[project]
dependencies = [
    # ... existing ...
    "opentelemetry-sdk>=1.20",
    "opentelemetry-exporter-otlp>=1.20",
]

[dependency-groups]
dev = [
    # ... existing ...
    "arize-phoenix>=8.0",                          # local Phoenix server
    "opentelemetry-instrumentation-fastapi>=0.62b1", # HTTP transport spans
]
```

**Not added:** `logfire` (raw OTel is more portable), `arize-phoenix-otel` (convenience wrapper we don't need).

#### Span attributes

Follow OTel semantic conventions where they exist; use `fin_assist.*` namespace for platform-specific attributes.

| Attribute | Source | Notes |
|-----------|--------|-------|
| `gen_ai.agent.name` | OTel semconv | Agent name (e.g., "git") |
| `gen_ai.operation.name` | OTel semconv | "invoke_agent" for task span |
| `gen_ai.request.model` | OTel semconv | From pydantic-ai `InstrumentedModel` |
| `gen_ai.usage.input_tokens` | OTel semconv | From pydantic-ai `InstrumentedModel` |
| `gen_ai.usage.output_tokens` | OTel semconv | From pydantic-ai `InstrumentedModel` |
| `fin_assist.task.id` | Platform | A2A task ID |
| `fin_assist.context.id` | Platform | A2A context ID (conversation thread) |
| `fin_assist.step.number` | Platform | 0-indexed step counter |
| `fin_assist.step.kind` | Platform | "model_request", "tool_call", "tool_result", "deferred" |
| `fin_assist.tool.name` | Platform | Tool name (e.g., "git", "read_file") |
| `fin_assist.tool.args` | Platform | Tool call arguments (string) |
| `fin_assist.tool.exit_code` | Platform | Exit code for CLI tools |
| `fin_assist.tool.duration_ms` | Platform | Wall-clock duration for tool execution |
| `fin_assist.tool.timed_out` | Platform | Boolean for timeout |
| `fin_assist.approval.decision` | Platform | "approved", "denied", "pending" |
| `fin_assist.approval.reason` | Platform | Human-readable reason string |
| `fin_assist.serving_mode` | Platform | "do" or "talk" |

**Sensitive data:** `fin_assist.tool.args` could contain file contents or command arguments. Initially included (local-only, Phoenix is localhost). If concern arises, add `tracing.include_tool_args: bool = True` config toggle. No user prompts or model outputs set as attributes — those stay in pydantic-ai framework spans (also localhost-only).

#### Step boundaries for CallToolsNode

Currently `_PydanticAIStepHandle.__aiter__()` only emits `step_start`/`step_end` for `ModelRequestNode`. `CallToolsNode` events (`tool_call`, `tool_result`) arrive between step boundaries. **Change:** emit `step_start`/`step_end` for `CallToolsNode` too. Steps alternate: model → tools → model → tools → ...

Step counter increments for both node types:
- step 0: ModelRequestNode (model generates response)
- step 1: CallToolsNode (tool calls + results)
- step 2: ModelRequestNode (model processes tool results)
- etc.

#### Tool duration timing

The Executor sees `tool_call` and `tool_result` as separate StepEvents. Track wall-clock time between them: store `time.monotonic()` on `_ExecutionContext` when `tool_call` arrives, compute delta when `tool_result` arrives. Keyed by `tool_name` (tools run sequentially within a step).

#### Approval span lifecycle

The `fin_assist.approval` span is created at `deferred` event time with `decision="pending"`. When the user approves/denies and the task resumes, add a span event (`span.add_event("approval_decision", {decision, reason})`) to the approval span. This keeps the approval in the original trace rather than splitting it across two traces.

For the resumed task, start a new `fin_assist.task` span with `fin_assist.task.resumed_from = <original_task_id>` as a link attribute. Each trace is self-contained; the link attribute connects them.

#### Testing strategy

**New test file:** `tests/test_hub/test_tracing.py`

Tests use `InMemorySpanExporter` from `opentelemetry-sdk` instead of OTLP:

```python
from opentelemetry.sdk.trace.export import InMemorySpanExporter
from opentelemetry.sdk.trace import TracerProvider
```

**Test cases:**

1. **Tracing disabled** — no spans emitted when `TracingSettings(enabled=False)`
2. **Task span lifecycle** — `fin_assist.task` span created and ended, correct attributes
3. **Step span lifecycle** — `fin_assist.step` spans for each step boundary, parent is task span
4. **Tool execution span** — `fin_assist.tool_execution` span with name, args, exit_code, duration
5. **Approval span** — `fin_assist.approval` span for deferred events
6. **Span hierarchy** — all platform spans have correct parent-child relationships
7. **pydantic-ai integration** — when `instrument=True`, framework spans appear as children of platform step spans (integration test with `FakeBackend`)
8. **FastAPI instrumentation** — HTTP span is root, task span is child
9. **Phoenix unreachable** — `BatchSpanProcessor` doesn't block or raise when OTLP endpoint is down

**Test infrastructure:** `conftest.py` fixture that sets up a `TracerProvider` with `InMemorySpanExporter`, runs a task via `FakeBackend`, and returns collected spans for assertion.

#### Files touched

| File | Change |
|------|--------|
| `pyproject.toml` | Add `opentelemetry-sdk`, `opentelemetry-exporter-otlp` to deps; `arize-phoenix`, `opentelemetry-instrumentation-fastapi` to dev deps |
| `src/fin_assist/config/schema.py` | Add `TracingSettings`, add `tracing` field to `Config` |
| `src/fin_assist/hub/tracing.py` | **New** — `setup_tracing()`, TracerProvider + OTLP exporter init, startup probe |
| `src/fin_assist/hub/executor.py` | Add span creation to `_setup_task`, `_consume_events`, `_finalize`, `_pause_for_approval` |
| `src/fin_assist/hub/app.py` | Call `setup_tracing()` + `Agent.instrument_all()` + `FastAPIInstrumentor.instrument_app()` |
| `src/fin_assist/agents/backend.py` | Set model/provider attributes on current span in `_build_model()`; add `step_start`/`step_end` for `CallToolsNode` |
| `tests/test_hub/test_tracing.py` | **New** — span emission tests |
| `tests/conftest.py` | Add tracing fixture (InMemorySpanExporter + TracerProvider) |
| `handoff.md` | This design sketch; update progress |

**Estimated:** ~5 source files modified/created, ~2 new test files, ~350 LOC + tests.

#### Resolved design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Instrumentation approach | Two-layer: platform spans + `Agent.instrument_all()` | Framework spans for free; platform spans for domain logic |
| FastAPI auto-instrumentation | Include in dev deps | Low noise (3-5 spans/request); provides HTTP transport root; aids debugging A2A protocol issues |
| Phoenix launch model | Standalone, not embedded | Phoenix is a dev tool; no runtime coupling; `devenv processes` for dev workflow |
| Phoenix unreachable behavior | BatchSpanProcessor silently drops; startup probe logs status | No blocking, no crashes; one-time log for awareness |
| OTel setup method | Raw `TracerProvider` + `OTLPSpanExporter` | More portable than `phoenix.otel.register()`; ~10 lines; works with any OTel backend |
| Context propagation | Standard `contextvars` via `start_as_current_span()` | Automatic in asyncio; no manual wiring; pydantic-ai picks it up |
| Span for CallToolsNode | Add `step_start`/`step_end` | Steps alternate model→tools→model→tools; each node type gets a step span |
| `arize-phoenix` dependency tier | Dev-only (`[dependency-groups] dev`) | Heavy (scipy, sklearn, pyarrow); server is dev infrastructure; runtime only needs OTel SDK |
| Logfire | Not used | Raw OTel is more portable; no Logfire-specific API lock-in |

#### Open questions for implementation

1. **OTel log suppression granularity.** Suppress at `opentelemetry` logger level entirely, or only `opentelemetry.exporter`? The exporter logs are the noisy ones when Phoenix is down; the SDK logs are useful for debugging. Decide during implementation.
2. **FastAPI instrumentation scope.** Instrument the parent app only, or parent + sub-apps? Parent-only may miss per-agent route detail; sub-app instrumentation may produce duplicate spans. Test during implementation.
3. **`Agent.instrument_all()` timing.** Must be called before any `Agent` instance is created. Currently `_build_pydantic_agent()` is called lazily on first task. If `instrument_all()` is called at hub startup (before any task), all agents are covered. Verify timing during implementation.
4. **Devenv processes entry.** Should `phoenix serve` be in `devenv.nix` by default, or documented as optional? Lean: documented, not default. Adding it to devenv means every `devenv up` launches Phoenix even when not tracing.

---

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

#### Skills vs. `context/` overlap

`GitContext` in `context/git.py` is a hard-coded, limited subset of what the `git` scoped CLI tool already does — both run `subprocess.run(["git", "diff", ...])`. With per-subcommand approval (Phase A), `@git:diff` can resolve *through the skill* (diff → `never` approval) instead of a separate `ContextProvider`. This eliminates the duplication.

But Skills doesn't subsume `context/` as a whole. `FileFinder` and `ShellHistory` aren't CLI wrappers — they have `search`/`get_item` semantics, structured data models, and path-aware ranking. They're data providers, not command runners. The `@`-completion concept (user-driven context injection) is orthogonal to Skills (model-driven tool bundles) — two intake paths that sometimes call the same underlying command.

**Simplification path:** Phase A/B absorbs `GitContext` into skill-backed resolution. `@git:diff` becomes "invoke the `git` skill with `never` approval" instead of a dedicated provider. The `@`-completion UX stays in CLI; the resolver learns about skills as a source. `FileFinder` and `ShellHistory` remain as `ContextProvider`s. `skills/` should be a top-level package (peer to `agents/` and `context/`) — both hub and CLI need access.

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

**Phase D (Observability).** Design sketch resolved 2026-04-29 — two-layer instrumentation (platform + `Agent.instrument_all()`), FastAPI auto-instrumentation, Phoenix as standalone dev backend. See "Design Sketches: Phoenix + OTel Tracing".

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
