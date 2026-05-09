# Handoff Document

Rolling context for session handoffs. Updated as checkpoints are reached.

**Current state (2026-05-09):** v0.1 shipped (PR #114, tag `v0.1`). 940 tests passing. v0.2 planning complete: backlog groomed (84 → 57 open), four-phase roadmap (v0.1.1 → v0.2 → v0.2.1 → v0.3), sub-agent design sketch captured. v0.2 anchor is in-process sub-agents as a context-compression primitive — see Design Sketch.

**Recent work (this session):**

1. **Steps 11–14: Skill loading refactor completion** — Implemented REPL `/skills` + `/skill:<name>` commands with `SkillCompleter` (rapidfuzz fuzzy matching, mirrors `@file:` pattern), skill tracing attributes/spans (`fin_assist.skill_load`, `fin_assist.cli.skill`), and updated all docs (architecture.md Skills Architecture rewrite, AGENTS.md skill authoring section, Phase 15 checklist)
2. **Steps 1–10, 13 (previous session)** — Config schema migration (`ApprovalConfig` → `ToolPolicyConfig`, `base_tools`, `tool_policies`), `AgentSpec` tool gating, `SkillManager.loaded_tool_names()`, `_build_pydantic_agent()` gates tools by loaded skills, `skills/invoke` + `GET /skills` endpoints, CLI `invoke_skill()`/`list_skills()` client methods, `_resolve_skill()` 3-tuple return, all existing tests updated

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

- AgentBackend protocol simplification ([#80](https://github.com/ColeB1722/fin-assist/issues/80))
- `supported_context_types` / `_CONTEXT_TYPE_HINTS` — CLI/BFF boundary not drawn explicitly; context-to-tool mapping lives in `agents/spec.py` but is a client concern. Needs broader architecture discussion: define CLI (display) vs BFF (context resolution, prompt shaping) vs hub/agent boundary, AgentCardMeta cleanup, and where context ownership should land.
- MCP tool source — v0.1.1 ([#84](https://github.com/ColeB1722/fin-assist/issues/84))
- Per-subcommand approval evaluation at executor level — v0.1.1
- Sub-agents (in-process, context-compression primitive) — v0.2 (see Design Sketch below)
- Sub-agents (federated via A2A) + Eval harness — v0.3
- Phase 4 architectural discussions — issues [#89–#94](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+is%3Aissue+89+90+91+92+93+94)

---

## Next Session

**Recommended picks (in priority order):**

1. **Manual review of skill loading refactor** — Verify tool gating works end-to-end (unloaded skill tools unavailable), `/skills` and `/skill:<name>` in REPL, agent-level policies applied correctly, tracing spans emitted.
2. **Part 2 interactive manual tests** — Run through `docs/manual-testing.md` sections 2a-2f at a TTY.
3. **Tag v0.1.0** — After manual review + interactive test pass.

### Sequenced roadmap

Post-v0.1 work is organized into four phases. Each phase ships under its own tag.

**Pre-v0.1.1 — Backlog grooming** (✅ complete 2026-05-09): closed 27 stale issues (84 → 57 open). Verified shipped items, removed Textual-era issues (UI module deleted), collapsed duplicates, marked superseded items.

| Phase | Tag | Scope | Status |
|-------|-----|-------|--------|
| 1 | **v0.1.1** | MCP tool source ([#84](https://github.com/ColeB1722/fin-assist/issues/84)), per-subcommand approval at executor level, pluggable system prompts ([#89](https://github.com/ColeB1722/fin-assist/issues/89)), registry consistency + policy resolution audit, SQLite/storage hardening ([#40](https://github.com/ColeB1722/fin-assist/issues/40), [#42](https://github.com/ColeB1722/fin-assist/issues/42), [#75](https://github.com/ColeB1722/fin-assist/issues/75)), constant placement ([#122](https://github.com/ColeB1722/fin-assist/issues/122)), chore-batch (#26, #33, #41, #43, #45, #46, #65, #76, #116, #117, #118, #119) | ⬜ Queued |
| 2 | **v0.2** | Sub-agents in-process — context-compression primitive (see Design Sketch). Includes: HITL rationale ([#121](https://github.com/ColeB1722/fin-assist/issues/121)), context-aware compaction ([#102](https://github.com/ColeB1722/fin-assist/issues/102)), workflow chaining ([#63](https://github.com/ColeB1722/fin-assist/issues/63)), background tasks ([#110](https://github.com/ColeB1722/fin-assist/issues/110)), multi-choice HITL ([#113](https://github.com/ColeB1722/fin-assist/issues/113)). Exit gate: [#31](https://github.com/ColeB1722/fin-assist/issues/31) SDD+TDD pipeline runs end-to-end | ⬜ Queued |
| 3 | **v0.2.1** | UX polish — render_stream simplification ([#92](https://github.com/ColeB1722/fin-assist/issues/92)), progressive thinking ([#72](https://github.com/ColeB1722/fin-assist/issues/72)), richer tool_result ([#91](https://github.com/ColeB1722/fin-assist/issues/91)), CLI constants ([#90](https://github.com/ColeB1722/fin-assist/issues/90)), `/spec` command ([#95](https://github.com/ColeB1722/fin-assist/issues/95)), `$EDITOR` for `--edit` ([#97](https://github.com/ColeB1722/fin-assist/issues/97)), `fin do` vs `fin prompt` clarity ([#94](https://github.com/ColeB1722/fin-assist/issues/94)), tracing follow-ups (#106, #107, #108, #109) | ⬜ Queued |
| 4 | **v0.3** | Sub-agents federated via A2A (Flavor 2) + per-agent eval harness | ⬜ Queued |

**Already shipped pre-v0.1:**

- Tracing: OTel + OpenInference bridge — follow-ups #106-#109 deferred to v0.2.1
- Skills API v0.1 (PR #114) — 940 tests, tool gating, agent-level policies, REPL `/skills`

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
| — | Documentation sync | ✅ Complete (architecture.md, manual-testing.md, README, AGENTS.md) |
| — | Git agent (#79) | ✅ Complete |
| — | Phoenix/OTel tracing (PR #103) | ✅ Complete |
| — | Telemetry Hardening Phase 2 | ✅ Complete |
| — | JSONL file exporter (#105) | ✅ Complete |
| — | Tracing UX pass (#104) | ✅ Complete |
| — | PR #103 code review fixes | ✅ Complete |
| — | Skill loading refactor (tool gating + agent-level policies) | ✅ Complete — Steps 1–14, 940 tests |
| 9b | Full SSE Streaming | ✅ Covered by a2a-sdk migration |
| 10 | Non-blocking + interactive tasks | 📐 Superseded by deferred tools |
| 11 | Multiplexer Integration | ⬜ Not Started |
| 12 | Fish Plugin | ⬜ Not Started |
| 13 | TUI Client | ⬜ Not Started |
| 14 | Testing Infrastructure (Deep Evals) | ⬜ Queued |
| 15 | Skills + MCP Integration | ✅ Skills API v0.1 shipped + skill loading refactor (tool gating, agent-level policies, REPL commands, tracing); MCP queued for v0.1.1 |
| 16 | Additional Agents | 🔄 Git shipped |
| 17 | Multi-Agent Workflows | ⬜ Not Started |
| 18 | Documentation | ⬜ Not Started |
| — | Nix/Home Manager packaging | 📐 Sketched |

---

## Design Sketches

### Sub-agents as Context Compression (sketched 2026-05-09)

**Status:** v0.2 anchor. Idea aligned, ready to detail-design before implementation.

**Concept:** A running agent can invoke a *sub-agent* — a nested execution with restricted scope — to perform a discrete task and return a compact result. The parent's conversation only sees the sub-agent's final output, not its intermediate steps. This is a context-compression primitive: long, exploratory, tool-heavy reasoning happens inside the sub-agent and never reaches the parent's context window.

**Why this framing matters:** Earlier discussion considered a `requires` field for skills (skill A declares dependency on skill B; loading A loads B). That was rejected — transitive skill loading is a small detail easy to miss, balloons fast, and any depth cap is arbitrary. Sub-agents subsume that need: if you want skill B's capabilities while running skill A, invoke a sub-agent with skill B loaded. The boundary is explicit, not transitive.

#### Two flavors — only one ships in v0.2

| Flavor | What | When | Cost |
|--------|------|------|------|
| **1: In-process** | Sub-agent runs inside the same hub process. `Executor.run_subtask(spec, prompt)` spins up a nested `AgentSpec` execution with a constrained tool set. No A2A protocol involvement. | **v0.2** | ~1-2 weeks |
| **2: Federated** | Sub-agent runs as a separate A2A task, possibly on another agent or external process. Cross-process tracing via OTel Links. | **v0.3** | ~3-4 weeks |

**Both flavors share the same caller-side API.** The `invoke_subagent` tool signature is designed so that v0.3 federation is a drop-in extension: when the target agent is local, route through `Executor.run_subtask`; when external, route through `HubClient`. Callers don't change.

#### v0.2 design (Flavor 1)

**Tool surface:**

```python
invoke_subagent(
    agent: str | None = None,        # Default: same agent as parent
    skills: list[str] | None = None, # Skills to load in the sub-agent
    prompt: str = ...,               # The task to perform
) -> str                              # Sub-agent's final output
```

**Execution semantics:**

1. Parent agent's LLM calls `invoke_subagent`. Tool call goes through normal approval gate (agent-level `tool_policies`).
2. `Executor.run_subtask()` constructs a fresh `AgentSpec` execution context: target `AgentSpec`, `SkillManager` with requested skills loaded, fresh conversation history (just the prompt).
3. Sub-agent runs to completion as a self-contained task — its own `fin_assist.task` span, its own step loop, its own tool calls.
4. Sub-agent's final string output is returned as the tool result to the parent.
5. Parent's conversation now contains: tool call → tool result. **Sub-agent's intermediate reasoning, tool calls, and thinking are discarded from the parent's view.** Full transcript still in `traces.jsonl`.

**Constraints (v0.2):**

- **Same-process only.** If `agent` argument names an external A2A agent, raise — that's v0.3.
- **No HITL inside sub-agents.** Sub-agents must run autonomously. If a sub-agent's tool requires approval, fail the sub-agent (don't pause the parent). Forces clean separation; v0.3 can lift this.
- **No nested sub-agents.** A sub-agent cannot itself call `invoke_subagent`. Prevents unbounded depth. Revisit in v0.3.
- **Tool gating reused as-is.** Sub-agent's tool set = `target_spec.base_tools` + tools from requested skills. Identical to a fresh `fin do` invocation.
- **Approval policies inherited.** Sub-agent uses its target agent's `tool_policies`. The agent-level invariant (each tool has exactly one policy definition) is preserved.

**Reporting format:** Sub-agent decides. Its system prompt gets a fixed appendix: *"You are being invoked as a sub-agent. Your final output is the only thing the caller sees — be concise and complete."* No `report_format` arg in v0.2; deferred to v0.3 along with structured output types.

**Tracing:**

```text
fin_assist.task (parent agent)
  └── fin_assist.step
        └── fin_assist.tool_execution (invoke_subagent)
              └── fin_assist.subagent
                    └── fin_assist.task (sub-agent, full nested tree)
                          ├── fin_assist.step
                          │     └── chat {model}
                          └── fin_assist.step
                                ├── fin_assist.tool_execution
                                └── chat {model}
```

New attributes on `fin_assist.subagent` span:
- `fin_assist.subagent.target_agent` (str)
- `fin_assist.subagent.skills` (list[str])
- `fin_assist.subagent.parent_task_id` (str)
- `fin_assist.subagent.result_length` (int) — for context-compression-effectiveness analysis

**Phoenix UI benefit:** the compression is visually obvious — parent has 2 sub-spans (call, return), sub-agent has 30+. The tree shows exactly what was hidden from the parent's context.

#### Touchpoints (implementation map)

| File | Change |
|------|--------|
| `src/fin_assist/agents/tools.py` | Register `invoke_subagent` as a built-in tool in `create_default_registry()` |
| `src/fin_assist/hub/executor.py` | New `Executor.run_subtask(spec, skills, prompt) -> str` method; reuses existing step loop with constrained scope |
| `src/fin_assist/hub/_task_tracer.py` | Add `emit_subagent_span()` with attributes above |
| `src/fin_assist/hub/tracing_attrs.py` | Add `FIN_SUBAGENT_*` attribute constants |
| `src/fin_assist/agents/spec.py` | Validate that `invoke_subagent` is in `base_tools` for any agent that wants sub-agent capability (or always-available, TBD) |
| `tests/test_hub/test_subagent.py` (new) | Unit tests: result return, tool gating in sub-agent, no HITL allowed, no nested calls, tracing attributes |
| `tests/integration/test_subagent_e2e.py` (new) | Integration: parent invokes sub-agent via FakeBackend, parent's history correctly contains only tool result |

#### Companion v0.2 work

Sub-agents are the anchor, but several issues become much more useful once sub-agents exist:

- **[#102](https://github.com/ColeB1722/fin-assist/issues/102) Context-aware agent handoff (compaction)** — sub-agents *are* compaction; this issue's "self-curated" framing now means "what does the sub-agent return."
- **[#121](https://github.com/ColeB1722/fin-assist/issues/121) HITL rationale pass-through** — needed regardless, but particularly relevant when a parent's `invoke_subagent` call needs approval (the rationale is the prompt being delegated).
- **[#110](https://github.com/ColeB1722/fin-assist/issues/110) Background tasks + sandboxing** — long sub-agents shouldn't block the parent indefinitely; a "fire and forget" mode is a natural extension once basic sub-agents work.
- **[#113](https://github.com/ColeB1722/fin-assist/issues/113) Multi-choice HITL** — orchestration flows where parent agent surfaces sub-agent results and asks "which one?"
- **[#63](https://github.com/ColeB1722/fin-assist/issues/63) Sequential agent chaining** — once sub-agents work, chaining is just a parent that calls multiple sub-agents in sequence.
- **[#31](https://github.com/ColeB1722/fin-assist/issues/31) SDD+TDD pipeline** — exit gate. SDD agent invokes TDD sub-agents per task. If this works end-to-end, v0.2 is real.

#### Open questions for v0.2 implementation

1. **`invoke_subagent` always-available, or opt-in?** Easiest: always in `base_tools`, like `read_file`. Lets any agent compose. Trade-off: agents that shouldn't compose (single-purpose agents) get the tool anyway. Lean: always-available.
2. **Sub-agent credential resolution.** Does the sub-agent share the parent's credentials, or re-resolve via its own agent's required providers? Lean: re-resolve. Sub-agent is a "real" agent execution, not a continuation of the parent.
3. **Conversation-history serialization.** Sub-agents have no persistent context (no `context_id`). Each invocation is fresh. Does the JSONL sink record sub-agent turns separately, or as nested children? Lean: separate `task_id` in JSONL, with `parent_task_id` cross-reference for joining.
4. **Cancellation propagation.** If parent task is cancelled mid-sub-agent, does the sub-agent get cancelled too? Lean: yes; the `invoke_subagent` tool call inherits the parent's cancellation token.
5. **What does the parent's prompt see when the sub-agent fails?** Tool result with error string, or raise into the parent? Lean: tool result with error — preserves the parent's autonomy to retry, fall back, or surface to the user.

#### What we explicitly defer

- **Federated sub-agents (Flavor 2)** — v0.3
- **Structured output from sub-agents** — v0.3
- **Sub-agent invokes sub-agent (nesting)** — v0.3
- **HITL inside sub-agents** — v0.3
- **`report_format` argument** — v0.3
- **Cross-agent skill invocation outside sub-agents** — explicitly NOT a feature; if you want skill B's tools while running agent A's skill, invoke a sub-agent with skill B loaded.

---

### Dynamic Phasing in System Prompt (sketched 2026-05-09)

**Status:** Idea stage — wiring discussion deferred.

**Concept:** Inject the current development phase of each subsystem into the agent system prompt (and/or `agent.md`), so the LLM can factor maturity/stability into its planning. For example, if a skill or tool is still in an "experimental" phase, the agent would know to surface caveats, avoid relying on undocumented behavior, or suggest conservative approaches. A "stable" phase would signal that normal usage is safe. A "deprecated" phase would steer the agent away from the feature entirely.

**Why it matters:** Agents currently have no visibility into what's production-ready vs. prototypical. This creates a planning blind spot — the LLM might confidently recommend a feature that's half-baked or steer users toward patterns that are about to change. Phase-aware context would let the agent self-regulate without hard guardrails.

**Sketch of what phase metadata might look like:**

```toml
[agents.git]
phase = "stable"

[agents.git.skills.commit]
phase = "stable"

[agents.git.skills.pr-checklist]
phase = "experimental"
```

Or at the tool level:

```toml
[agents.git.tool_policies.git]
phase = "stable"
rules = [
  { pattern = "git push*", mode = "always" },
  { pattern = "git diff*", mode = "never" },
]

[agents.git.tool_policies.gh]
phase = "experimental"
```

**Open questions (deferred to wiring discussion):**

1. **Source of truth** — Does phase live in `config.toml`, `agent.md` frontmatter, a separate manifest, or is it derived from version/convention (e.g., `v0.x` = experimental)?
2. **Granularity** — Per-agent? Per-skill? Per-tool? All three with inheritance (tool inherits skill phase unless overridden)?
3. **Prompt injection point** — Appended to `agent.md`? Injected into `SkillManager.catalog_text()`? A dedicated context provider?
4. **Phase vocabulary** — `experimental` / `stable` / `deprecated`? Or more nuanced (e.g., `alpha`, `beta`, `ga`, `sunset`)?
5. **Agent behavior specification** — Should the prompt just state the phase and let the LLM infer behavior, or should each phase carry explicit behavioral directives (e.g., `"experimental": "Always ask before using; explain that the feature may change"`)?
6. **Lifecycle transitions** — How does a feature move from `experimental` → `stable`? Config change + changelog? Automated based on test coverage or time?

**Next step:** When ready to wire this up, decide on the open questions above and define a concrete touchpoint map (which files read phase, where it's injected into prompts, how it's surfaced to the user).

---

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

```text
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

### _TaskTracer Extraction (completed)

**Status:** Implemented in `hub/_task_tracer.py`.

**What changed:** `executor.py` had 6 tracing fields on `_ExecutionContext` and 8 tracing methods on `Executor`, interleaving A2A task lifecycle and OTel span lifecycle. Extracted all span creation, attribute setting, and context token management into `_TaskTracer` (new file `hub/_task_tracer.py`). `_ExecutionContext` now has a single `tracer: _TaskTracer` field; the executor delegates span operations via `ctx.tracer.start_task_span(...)`, `ctx.tracer.end_step_span()`, etc.

**Results:**
- `_ExecutionContext`: 13 fields → 8 (6 tracing fields → 1 `tracer` reference)
- `Executor`: lost `_start_step_span`, `_end_step_span`, `_start_tool_span`, `_end_tool_span`, `_make_link`, `_emit_approval_decided_span`, `_handle_deferred_event`, `_detach_task_context`, `_read_invocation_id_from_baggage`, `_active_tracer` property, `_tracer` field
- `execute()`: ~135 lines → ~50 lines of business flow
- `_pause_for_approval()`, `_finalize()`: inline span code replaced by single tracer calls
- `_dispatch_step_event()`: each event case now has 1 tracer call + A2A artifact logic
- `_handle_deferred_event()` split into `tracer.emit_approval_request_span(event)` + `_emit_deferred_artifact()`
- `executor.py` has zero OTel imports — all span lifecycle lives in `_task_tracer.py`
- All 880 tests pass unchanged

---

### Skills API: v0.1 Implementation (shipped 2026-05-01, review triage 2026-05-02, refactor 2026-05-03)

**Status:** Complete including skill loading refactor. 940 tests passing, `just ci` green.

**What was implemented:**

1. **`ApprovalRule` + `ApprovalPolicy.evaluate()`** — fnmatch-based per-subcommand approval rules. First-match semantics with `default` fallback. Replaces the old binary `always`/`never` mode.

2. **`SkillConfig`** — config schema type for inline TOML skill definitions. Added to `AgentConfig.skills: dict[str, SkillConfig]`. No approval field — policies moved to agent level.

3. **`SkillDefinition`, `SkillCatalog`, `SkillLoader`, `SkillManager`** — runtime types in `agents/skills.py`. `SkillLoader` resolves both inline TOML and SKILL.md files. `SkillManager` tracks loaded skills, provides `load_skill` callable, `loaded_tool_names()`, and generates catalog text.

4. **SKILL.md file loader** — parses YAML frontmatter + markdown body following agentskills.io convention. Discovery from `.fin/skills/` and `~/.config/fin/skills/`. fin-assist extensions under `metadata.fin-assist.*`.

5. **Config migration** — `config.toml` migrated from `tools`/`workflows` to `skills` with agent-level `tool_policies`. `WorkflowConfig` and `--workflow` CLI flag removed. `--skill` CLI flag. `base_tools` (default `["read_file"]`) for always-available tools.

6. **Tool gating** — `_build_pydantic_agent()` registers only `base_tools` + `SkillManager.loaded_tool_names()`. Skills not loaded = tools not registered. Called on every `step()`, so loading takes effect next turn.

7. **Agent-level tool policies** — `ToolPolicyConfig`/`ToolPolicyRuleConfig` replace per-skill `ApprovalConfig`. `_get_agent_tool_policy()` resolves policies per tool. Each tool has exactly one policy definition — no merge conflicts.

8. **`skills/invoke` + `GET /skills` endpoints** — `POST /agents/{name}/skills/invoke` pre-loads a skill server-side. `GET /agents/{name}/skills` lists available skills. `HubClient.invoke_skill()` and `HubClient.list_skills()` client methods.

9. **REPL `/skills` + `/skill:<name>`** — `/skills` lists available skills. `/skill:<name>` loads a skill mid-session via `invoke_skill_fn`. `SkillCompleter` with rapidfuzz fuzzy matching on `/skill:` prefix (mirrors `@file:` pattern).

10. **Skill tracing** — `fin_assist.skill_load` span via `_TaskTracer.emit_skill_load_span()`. `fin_assist.skill.id`, `fin_assist.skill.entry_point`, `fin_assist.skill.tools_unlocked` attributes. `fin_assist.cli.skill` on CLI root span. `skill_id` param on `start_task_span()`.

11. **`fin list skills`** — lists config-defined and SKILL.md-discovered skills, grouped by agent name.

**Key design decisions:**

- Skills are additive (no unloading in v0.1)
- Tools shared across skills; name collisions = config error
- Tool gating: `base_tools` + `loaded_tool_names()` only — LLM can't use unloaded tools
- Agent-level `tool_policies` replace per-skill `approval` — each tool has exactly one policy
- `base_tools` default `["read_file"]` — agents always need file reading
- `_build_pydantic_agent()` called on every `step()` — skill loading takes effect next turn
- `/skill:<name>` mirrors `@file:` pattern with `SkillCompleter` + rapidfuzz

**Bug fixes shipped alongside:**

- FileHistory dir creation (#54/#51) — `prompt.py:_build_session()` now creates parent dir
- Malformed session file crash (#81) — `display.py:render_session_list()` catches JSONDecodeError
- AgentCard version from package metadata (#78) — `factory.py` uses `importlib.metadata.version()`
- `MessageToDict` consolidation (#86) — all direct calls replaced with `struct_to_dict()` from `protobuf.py`

**New files:**
- `src/fin_assist/agents/skills.py`
- `tests/test_agents/test_skills.py`
- `tests/test_agents/test_approval_policy_evaluate.py`

**Modified files (key):**
- `src/fin_assist/agents/tools.py` — `ApprovalRule`, `ApprovalPolicy.evaluate()`, simplified `__post_init__`
- `src/fin_assist/agents/spec.py` — `skills` property (`dict[str, SkillConfig]`), derived `tools`, `_CONTEXT_TYPE_HINTS`, `get_skill_definitions()`
- `src/fin_assist/agents/backend.py` — skill-based approval overrides, `load_skill` tool, catalog in prompt, public API for skill manager
- `src/fin_assist/agents/skills.py` — YAML approval rule validation
- `src/fin_assist/config/schema.py` — `SkillConfig`, `ApprovalConfig`, `ApprovalRuleConfig`; removed `WorkflowConfig`
- `src/fin_assist/cli/main.py` — `_resolve_skill`, `--skill` flag, `fin list skills` grouped by agent
- `src/fin_assist/hub/factory.py` — `PackageNotFoundError` fallback, version from metadata
- `config.toml` — migrated to skills format

**Post-v0.1 roadmap:**

| Version | Feature |
|---------|---------|
| v0.1.1 | MCP tool source — `MCPToolset` registers discovered tools into `ToolRegistry` |
| v0.1.1 | Pluggable base system prompts — user-overridable prompt templates, not hardcoded Python constants |
| v0.1.1 | Per-subcommand approval evaluation at executor level |
| v0.2 | Skill composability (skills invoking skills) + agent-to-agent orchestration |
| v0.3 | Eval harness |

---

### Skills API: Original Design Sketch (for reference)

**Status:** Sketch resolved 2026-04-27. Ready to start Phase A.

**Why this exists:** scoped CLI + WorkflowConfig pattern from the git agent is a prototype for the broader Skills API. Split into three sequenced phases, each independently shippable.

**Grounding citations:**

- Scoped CLI prototype + TODO for per-subcommand approval: `src/fin_assist/agents/tools.py:213`, `src/fin_assist/agents/tools.py:295`
- Current `ApprovalPolicy` shape (only `never`/`always`, no rules): `src/fin_assist/agents/tools.py:40`
- `AgentConfig.tools` flat list of names: `src/fin_assist/config/schema.py:99` *(field removed — tools now derive from skill union)*
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
- Scoped CLI tools (`git`, `gh`) support per-subcommand approval via skills
- JSONL trace sink always-on when tracing enabled, writes to `$FIN_DATA_DIR/traces.jsonl`
- `OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false` set in `__init__.py` to suppress a2a-sdk noise
