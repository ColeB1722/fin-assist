# Handoff Document

Rolling context for session handoffs. Updated as checkpoints are reached.

**Current state (2026-05-02):** 924 tests passing, `just ci` green. Skills API v0.1 fully implemented. Phase 5 documentation verified current. Part 1 manual tests passed (server lifecycle A7-A14, platform capabilities L1-L4). Ready for Part 2 interactive tests (requires human at TTY) and v0.1.0 tag.

**Recent work (this session):**

1. **Phase 5 documentation review** — Verified all docs current: architecture.md has Skills Architecture section, manual-testing.md has 2e/2f, README has skills entry, AGENTS.md has skill authoring section
2. **Part 1 manual tests** — Server lifecycle (A7-A14) and platform capabilities (L1-L4) all pass. Known cosmetic: OTLP exporter stderr noise when Phoenix not running (devenv tracing default)
3. **Previous session** — Skills API v0.1 (Phases 0–4) + CodeRabbit review triage (PR #114): removed `WorkflowConfig`/`--workflow` dead code, bug fixes, style fixes, `fin list skills` grouped by agent

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
- `supported_context_types` published in agent cards, never consumed by clients
- Skill composability (skills invoking skills) — v0.2
- Agent-to-agent orchestration — v0.2
- MCP tool source — v0.1.1
- Per-subcommand approval evaluation at executor level — v0.1.1
- Eval harness — v0.3
- Phase 4 architectural discussions — issues [#89–#94](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+is%3Aissue+89+90+91+92+93+94)

---

## Next Session

**Recommended picks (in priority order):**

1. **Part 2 interactive manual tests** — Run through `docs/manual-testing.md` sections 2a-2f at a TTY. Key tests: approval widget (B1-B7, highest risk), REPL (C1-C16), skills API (S1-S6), shell agent exercise (X1-X6). Part 1 (automated) is done.
2. **Tag v0.1.0** — After Part 2 interactive test pass.
3. **MCP tool source (v0.1.1)** — Add `MCPToolset` as a second tool source that registers discovered tools into `ToolRegistry`. The skill→tool binding is source-agnostic, ready for MCP.

### Sequenced roadmap

| # | Work | Status |
|---|------|--------|
| 1 | Tracing: OTel + OpenInference bridge | ✅ Complete — follow-ups [#104-#109](https://github.com/ColeB1722/fin-assist/issues?q=is%3Aopen+104+105+106+107+108+109) |
| 2 | Skills API v0.1 | ✅ Complete — Phases 0–4 + code review triage shipped (924 tests) |
| 3 | MCP tool source (v0.1.1) | ⬜ Queued — skill→tool binding is source-agnostic |
| 4 | Eval harness (per-agent) | ⬜ Queued — rides on tracing |
| 5 | Skill composability + agent-to-agent (v0.2) | ⬜ Queued |

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
| 9b | Full SSE Streaming | ✅ Covered by a2a-sdk migration |
| 10 | Non-blocking + interactive tasks | 📐 Superseded by deferred tools |
| 11 | Multiplexer Integration | ⬜ Not Started |
| 12 | Fish Plugin | ⬜ Not Started |
| 13 | TUI Client | ⬜ Not Started |
| 14 | Testing Infrastructure (Deep Evals) | ⬜ Queued |
| 15 | Skills + MCP Integration | ✅ Skills API v0.1 shipped (code review triaged); MCP queued for v0.1.1 |
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

### Skills API: v0.1 Implementation (shipped 2026-05-01, review triage 2026-05-02)

**Status:** Phases 0–4 complete + code review triage. 924 tests passing, `just ci` green.

**What was implemented:**

1. **`ApprovalRule` + `ApprovalPolicy.evaluate()`** — fnmatch-based per-subcommand approval rules. First-match semantics with `default` fallback. Replaces the old binary `always`/`never` mode.

2. **`SkillConfig` + `ApprovalConfig` + `ApprovalRuleConfig`** — config schema types for inline TOML skill definitions. Added to `AgentConfig.skills: dict[str, SkillConfig]`.

3. **`SkillDefinition`, `SkillCatalog`, `SkillLoader`, `SkillManager`** — runtime types in `agents/skills.py`. `SkillLoader` resolves both inline TOML and SKILL.md files. `SkillManager` tracks loaded skills, provides `load_skill` callable, and generates catalog text.

4. **SKILL.md file loader** — parses YAML frontmatter + markdown body following agentskills.io convention. Discovery from `.fin/skills/` and `~/.config/fin/skills/`. fin-assist extensions under `metadata.fin-assist.*`. Validates required `pattern`/`mode` keys in approval rules.

5. **Config migration** — `config.toml` migrated from `tools`/`workflows` to `skills` with per-skill approval rules. `WorkflowConfig` and `--workflow` CLI flag removed. `--skill` CLI flag.

6. **Dynamic skill loading** — `load_skill` tool registered when skills exist. Skill catalog injected into system prompt. `SkillManager.load_skill()` marks skills as active.

7. **`fin list skills`** — lists config-defined and SKILL.md-discovered skills, grouped by agent name.

**Key design decisions:**

- Skills are additive (no unloading in v0.1)
- Tools shared across skills; name collisions = config error
- `AgentSpec.tools` derives from skill union, falls back to flat `tools` list for backward compat
- Approval is conservative: if default="always" or any rule has mode="always", tool gets `requires_approval=True`. Fine-grained per-subcommand evaluation at executor level in v0.1.1
- `_CONTEXT_TYPE_MAP` → `_CONTEXT_TYPE_HINTS` module-level constant
- Dead code removed: `format_context()`, `build_user_message()`, `WorkflowConfig`

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
- Scoped CLI tools (`git`, `gh`) support per-subcommand approval via skills
- JSONL trace sink always-on when tracing enabled, writes to `$FIN_DATA_DIR/traces.jsonl`
- `OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false` set in `__init__.py` to suppress a2a-sdk noise
