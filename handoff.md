# Handoff Document

In-flight design sketches and rolling session context. See `AGENTS.md` for what this file is and isn't.

**Forever-docs:**
- Project overview & status table → [README.md](README.md)
- Architecture → [docs/architecture.md](docs/architecture.md)
- Workflow & conventions → [AGENTS.md](AGENTS.md)

**Live planning:**
- Committed work → [GitHub milestones](https://github.com/ColeB1722/fin-assist/milestones)
- Discussions / ideas / out-of-scope bugs → [GitHub issues](https://github.com/ColeB1722/fin-assist/issues)

---

## Current state

**2026-05-09:** v0.1 shipped (PR #114, tag `v0.1`). 940 tests passing. v0.2 planning complete: backlog groomed (84 → 57 open issues), four-phase roadmap captured as milestones (v0.1.1 → v0.2 → v0.2.1 → v0.3). v0.2 anchor is in-process sub-agents as a context-compression primitive — see Design Sketch below.

**Context-strategy refactor (this session):** documented the issue/milestone split and the doc-surface roles in `AGENTS.md`; pruned this file from the previous 625-line accumulator down to its actual job (sketches + rolling context).

## Next session

**Recommended picks (in priority order):**

1. **Begin v0.1.1 work** — start with MCP tool source ([#84](https://github.com/ColeB1722/fin-assist/issues/84)) or per-subcommand approval at executor level (see [v0.1.1 milestone](https://github.com/ColeB1722/fin-assist/milestone/1) for the full set).
2. **Resolve open questions in the sub-agents Design Sketch below** before implementation begins. There are 5 questions; answering them unblocks v0.2.
3. **Eventually:** split `docs/architecture.md` into focused files (`architecture.md` slim + `tracing.md` + `skills.md` + `decisions.md`) and beef up the README's "project soul" framing. Tracked as the next pass on the context-strategy refactor.

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

## Recent work

### 2026-05-09 — Context-strategy refactor

- Added `Context Strategy` section to `AGENTS.md` documenting the surface/job/cadence table and the issue-vs-milestone rule.
- Slimmed `AGENTS.md` "Session Handoffs" subsection to match handoff.md's narrowed role.
- Pruned `handoff.md` from 625 lines to its actual job: current state header + Design Sketches + rolling session log. Removed the Implementation Progress table, the Sequenced Roadmap table (milestones own this now), the Tracing/_TaskTracer/Skills-API historical implementation logs (git log territory), the Historical Reference section, and the duplicated Notes/Quick-Start sections.

### 2026-05-09 (earlier) — v0.2 planning

- Backlog grooming pass: 84 → 57 open issues. Closed 27 stale items (shipped, Textual-era, duplicates, superseded). Chore-batched 9 small items into v0.1.1.
- Created four GitHub milestones with descriptions: [v0.1.1](https://github.com/ColeB1722/fin-assist/milestone/1), [v0.2](https://github.com/ColeB1722/fin-assist/milestone/2), [v0.2.1](https://github.com/ColeB1722/fin-assist/milestone/3), [v0.3](https://github.com/ColeB1722/fin-assist/milestone/4).
- Aligned on sub-agents as v0.2 anchor (rejecting transitive `requires` field on skills); split into in-process (v0.2) vs federated (v0.3) flavors with shared caller-side API. Captured as Design Sketch above.

### 2026-05-03 — Skill loading refactor (v0.1)

Implemented REPL `/skills` + `/skill:<name>` commands with `SkillCompleter` (rapidfuzz fuzzy matching, mirrors `@file:` pattern), skill tracing attributes/spans (`fin_assist.skill_load`, `fin_assist.cli.skill`), and updated docs. Tool gating, agent-level `tool_policies`, `base_tools` defaults, `skills/invoke` + `GET /skills` endpoints, REPL slash-command loading, `fin list skills`. 940 tests passing. v0.1 shipped as PR #114, tagged `v0.1`.
