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

**2026-05-10 (session 2):** Audited context provider wiring (#129). The two paths (@-completion and tool calls) are incoherent: separate instances, no shared cache, `git` tool bypasses `GitContext` entirely, `git_status` and `Environment` are unreachable. Filed #129 with three design options and a blocking note on #84 (ToolProvider shape depends on answer) and #115 (don't wire Environment with current pattern). Added v0.1.1 milestone note that #129 direction must be resolved before those two ship.

**2026-05-10 (session 1):** Audited `AgentCardMeta` field wiring. Finding: `serving_modes` is the only field with runtime enforcement; `supported_context_types` (computed, published, never consumed for filtering), `supported_providers` (always `None`, no config key), `supports_model_selection` (always `True`, never read), and `supports_thinking` (set but never read by CLI) are all declarative-only. Documented in milestone notes: context-type filtering paired with #115 in v0.1.1; provider filtering + model selection + thinking gate deferred to v0.2.1 with design questions. Also: `docs/architecture.md` edits from the doc-restructure session (deliverables table, local-first principle, maintenance contract, backend diagram) are on disk but uncommitted — awaiting user review.

**2026-05-10:** Added "ToolProvider Protocol" design sketch — unifies tool registration across builtin, MCP, and file-based sources. Informs v0.1.1 (#84) architecture; ships progressively through v0.3. Updated milestone descriptions for v0.1.1, v0.2, v0.3 with ToolProvider context. Added comment to #84 with implementation sequence.

**2026-05-09:** v0.1 shipped (PR #114, tag `v0.1`). 940 tests passing. v0.2 planning complete: backlog groomed (84 → 57 open issues), four-phase roadmap captured as milestones (v0.1.1 → v0.2 → v0.2.1 → v0.3). v0.2 anchor is in-process sub-agents as a context-compression primitive — see Design Sketch below.

**Context-strategy refactor (across three sessions):** documented the issue/milestone split and doc-surface roles in `AGENTS.md`; pruned this file from 625 → ~220 lines; split the 1464-line `docs/architecture.md` into `architecture.md` (slim contracts + diagrams), `tracing.md`, `skills.md`, `decisions.md`, `configuration.md`; rewrote `README.md` with user-lens framing; ran code-validation pass and corrected ~25 drift items (signatures, defaults, phantom commands, unwired features).

## Next session

**Recommended picks (in priority order):**

1. **Begin v0.1.1 work** — slimmed to 7 focused issues. Start with the `ToolProvider` protocol extraction (Phase A from the new Design Sketch) before #84 MCP implementation — it's a ~50-line refactor that prevents MCP from being bolted onto `create_default_registry()`. Then proceed with #84, #89, #85, #115, and the three drift-wiring issues (#123, #124, #125).
2. **Resolve open questions in the sub-agents Design Sketch below** before implementation begins. There are 5 questions; answering them unblocks v0.2.

**Sequence:** v0.1.1 (foundations) → [v0.1.2](https://github.com/ColeB1722/fin-assist/milestone/5) (visibility — badges + demo gif, [#127](https://github.com/ColeB1722/fin-assist/issues/127)) → v0.2 (sub-agents).

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

### ToolProvider Protocol: Unifying Tool Registration (sketched 2026-05-10)

**Status:** Design sketch. Informs v0.1.1 (#84 MCP) architecture; ship progressively through v0.2–v0.3.

**Problem:** `create_default_registry()` hardcodes 5 tools into `ToolRegistry`. Skills *reference* tools by name but can't *define* them. MCP (#84) adds a second tool source. The platform is becoming a tool host, but the registration architecture is still "platform defines, agents consume." This is the anti-pattern — tools should be discoverable from the agent's own repo/context, not hardcoded in the platform.

**Concept:** Introduce a `ToolProvider` protocol that decouples tool *discovery* from tool *registration*. `ToolRegistry` becomes an aggregator of providers rather than a flat dict. Each provider contributes tools at startup (or lazily). This unifies three tool sources under one API:

```text
ToolProvider (protocol)
├── BuiltinToolProvider     — migrated from create_default_registry()
├── MCPToolProvider         — v0.1.1 (#84)
└── FileToolProvider        — discovers .py tool files from configured directories
```

#### Industry patterns researched (2026-05-10)

| Pattern | Framework | Mechanism |
|---------|-----------|-----------|
| Decorator + file discovery | Strands, Selectools | `@tool` on functions; auto-scan `.py` from directories; hot-reload |
| Manifest + implementation | mcpp | `tool.yaml` (schema) + `mcpptool.py` (execute); lazy import on first call |
| Extension registration | Pi | `pi.registerTool()` at runtime; progressive disclosure; dynamic add/remove |
| Filesystem browsing | AgentPatterns.ai | Tools as files in directory tree; agent navigates on-demand (98% token reduction vs upfront registration) |
| Auto-discovery from modules | InitRunner | `custom` tool type: import module, scan for public functions → register all |
| Plugin registry | R2R | Built-in path + user-tools path; `inspect` for `Tool` subclasses |

Key takeaway: the two dominant models are **decorator-based auto-discovery** (scan `.py`, find `@tool` functions — most Pythonic) and **manifest + implementation** (separate schema from code — most portable). We should support both.

#### ToolProvider protocol

```python
class ToolProvider(Protocol):
    """Discovers and contributes ToolDefinitions to the registry."""

    def discover(self) -> list[ToolDefinition]:
        """Return all tools this provider contributes. Called at startup."""
        ...

    @property
    def name(self) -> str:
        """Provider identifier for logging and debugging."""
        ...
```

`ToolRegistry` gains a provider-aggregation layer:

```python
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._providers: dict[str, ToolProvider] = {}

    def add_provider(self, provider: ToolProvider) -> None:
        """Register a provider and merge its tools into the registry."""
        self._providers[provider.name] = provider
        for tool in provider.discover():
            self.register(tool)

    def get_provider(self, name: str) -> ToolProvider | None: ...
```

Existing `register()` / `get()` / `get_for_agent()` APIs unchanged — providers are an *ingestion path*, not a new query interface.

#### FileToolProvider — file-based tool discovery

This is the new capability. Analogous to how skills are discovered from `.fin/skills/`, tools are discovered from `.fin/tools/` (project-local) and `~/.config/fin/tools/` (user-global).

**Directory convention:**

```text
.fin/tools/
├── deploy.py          # single-function tool
├── db_query.py        # module with multiple tools
└── s3/
    ├── __init__.py
    ├── list_objects.py
    └── upload.py
```

**Discovery rules:**
1. Scan `.fin/tools/` and `~/.config/fin/tools/` for `.py` files
2. For each file, import the module and scan for functions decorated with `@tool` (our own decorator, not pydantic-ai's)
3. If no `@tool` functions found, fall back to scanning for public callables with type-hinted signatures + docstrings (InitRunner pattern)
4. Project-local takes precedence over user-global for name collisions
5. Skip files starting with `_`

**`@tool` decorator:**

```python
from fin_assist.agents.tools import tool, ApprovalPolicy

@tool(
    description="Deploy the current branch to staging",
    approval=ApprovalPolicy(default="always"),
)
def deploy(branch: str, env: str = "staging") -> str:
    """Deploy the current branch."""
    ...
```

The decorator is optional — plain functions with type hints and docstrings auto-register (schema derived from signature, like pydantic-ai's `tools=` argument). The decorator just lets you override description, approval policy, and name.

**How this differs from skills:**
- Skills *reference* tools by name; they don't define them
- File-based tools *define* new callables; they're a tool *source*
- A skill can reference a file-based tool the same way it references `git` or `read_file` — by name in `tools = [...]`

#### Progressive shipping plan

| Phase | What | Milestone |
|-------|------|-----------|
| **A: Protocol + BuiltinToolProvider** | Extract `ToolProvider` protocol; refactor `create_default_registry()` into `BuiltinToolProvider`; `ToolRegistry.add_provider()`. Zero behavior change — same 5 tools, same API. | v0.1.1 (#84 dependency) |
| **B: MCPToolProvider** | Implement as part of #84. MCP servers discovered from config → `MCPToolProvider.discover()` returns `ToolDefinition` per MCP tool. | v0.1.1 (#84) |
| **C: FileToolProvider** | New provider; `@tool` decorator; `.fin/tools/` discovery. First new capability — tools not defined by the platform. | v0.2 (sub-agents need per-agent tool sets) |
| **D: Repo-as-tool-package** | Agent experiment repos ship with `.fin/tools/` + `.fin/skills/` + `evals/`; clone → discover → run. Tool packages as a first-class concept. | v0.3 (federated agents + eval) |

Phase A is the critical path — if #84 ships without `ToolProvider`, MCP tools get bolted onto `create_default_registry()` and the retrofit is harder. The protocol costs ~50 lines; it should land before or alongside #84.

#### Relation to sub-agents (v0.2)

Sub-agents (`invoke_subagent`) construct a fresh `AgentSpec` with a constrained tool set. With `FileToolProvider`, a sub-agent's tools can come from its own `.fin/tools/` directory rather than the global registry. The `Executor.run_subtask()` call creates a scoped `ToolRegistry` with only the sub-agent's providers.

This also means `invoke_subagent` can be replaced: instead of a hardcoded built-in tool, it becomes a file-defined tool in `.fin/tools/subagent.py`. The platform ships *defaults*, not *mandates*.

#### Open questions

1. **Lazy vs eager discovery.** Should `FileToolProvider.discover()` import all `.py` files at startup (eager, like current `create_default_registry`) or defer imports until the tool is first called (lazy, like mcpp)? Lean: eager at startup — simpler, errors surface early, and the tool count is small (<50 per project).
2. **Approval policy for file-based tools.** Should file-defined tools default to `always` (safe) or `never` (convenient)? Lean: `always` — file-based tools are user code, unvetted. Explicit `@tool(approval=ApprovalPolicy(default="never"))` to opt out.
3. **Tool name collision resolution.** What happens when a file-based tool has the same name as a built-in or MCP tool? Lean: raise at startup with a clear error (consistent with `ToolRegistry.register()` duplicate-name behavior). Override via explicit allowlist in config if needed.
4. **`@tool` decorator location.** Should `@tool` live in `fin_assist.agents.tools` (next to `ToolDefinition`) or a new `fin_assist.agents.tool_decorator` module? Lean: `fin_assist.agents.tools` — keeps the tool API in one place.
5. **Package-level discovery.** Should we support `fin_assist.tools` namespace packages (like R2R's built-in path)? Or just filesystem directories? Lean: filesystem only for now — namespace packages are an advanced pattern that can come later if needed.

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

### 2026-05-12 — Windows dev ergonomics shipped

Cross-platform justfile (`set windows-shell`), platform-aware `DATA_DIR` in `paths.py` (`%LOCALAPPDATA%\fin` on Windows), CI `test-windows` job, and 14 test-fix buckets (sidecar PID lock, `encoding="utf-8"`, `_force_kill`/`TerminateProcess`, `re.escape` in match). See [`docs/decisions.md`](docs/decisions.md) (Windows section) and [`README.md`](README.md) (non-Nix quick start).

### 2026-05-09 (latest) — README rewrite + milestone re-split

- Rewrote README into technical-writing register (per user feedback that "user-lens" had become conversational). Structure: Concepts → Example → Architecture → Install → CLI reference → Documentation → Status. Replaced user-lens diagram with structural Architecture diagram. Paired TOML config with invocation example so reader has vocabulary before seeing the CLI session. 161 → 141 lines.
- Split v0.1.1 (was 35 issues, three mixed themes) into:
  - **v0.1.1 — Foundations** (7 issues): #84, #85, #89, #115, #123, #124, #125
  - **v0.1.2 — Visibility** (new milestone, 1 issue): [#127](https://github.com/ColeB1722/fin-assist/issues/127) (badges + demo gif)
  - **No milestone** (28 issues): chore batch — test cleanup, type hints, CodeRabbit refactors. Per AGENTS.md context strategy, "things to do when convenient" don't belong in milestones.
- Updated v0.1.1 milestone description to reflect the new 7-issue scope and document the chore-unmilestoning rationale.

### 2026-05-09 (earlier) — Code-validation pass on the new doc structure

- Ran a four-track validation pass (one sub-agent per doc) of every concrete claim in `architecture.md`, `skills.md`, `tracing.md`, `configuration.md` against `src/`. Each sub-agent returned a structured report citing `file:line` for every check.
- Found ~25 drift items, grouped into four buckets:
  - **Critical (3)** — features documented as live but not actually wired up: `fin_assist.skill_load` span never emitted, `start_task_span(skill_id=...)` never invoked, SKILL.md files discoverable by `list skills` but not loaded into runtime `SkillManager`.
  - **API drift (8)** — wrong signatures in arch.md "Key types" section: `AgentSpec.tools` → `skill_tool_names`, `run_stream` → `run_steps` returning `StepHandle` of `StepEvent`s (not text deltas), `AgentBackend` protocol has 8+1 methods not 5, `ContextItem.status` default `"available"` not `"ready"`, `create_hub_app` signature is `(agents: Sequence[AgentSpec], db_path: str = ":memory:", ...)` not `(config, credentials, *, db_path)`.
  - **Phantom commands (3)** — `_poll_task` (doesn't exist anywhere in `src/`), `fin-assist /connect` (no command exists), bare positional `fin do <agent> <skill>` (argparse only has one positional; what works is `fin do --agent git commit` via prompt-as-skill auto-promotion).
  - **Definition drift (12)** — thinking defaults, `system_prompt` "required" vs has default, `ProviderRegistry` doesn't read TOML, task-state enum missing `resumed_from_approval`, `DropSpansProcessor` is public not `_DropSpansProcessor`, `tracing_shared.py` omitted from Files list, etc.
- Filed three GH issues under v0.1.1: [#123](https://github.com/ColeB1722/fin-assist/issues/123) (skill tracing wiring), [#124](https://github.com/ColeB1722/fin-assist/issues/124) (`/connect` interactive setup), [#125](https://github.com/ColeB1722/fin-assist/issues/125) (wire SKILL.md files into runtime `SkillManager`).
- Applied fixes: rewrote `AgentSpec`/`AgentBackend`/`ContextItem`/`create_hub_app` API blocks in arch.md; demoted unwired skill spans to "scaffolding, not yet invoked" in skills.md + tracing.md; corrected `thinking`/`system_prompt`/`ProviderRegistry` claims in configuration.md; replaced phantom CLI commands with what actually works in arch.md + README; added `tracing_shared.py` to tracing.md Files. `just lint` clean.
- 6 files changed, +130/-89 lines. Branch `docs/planning` still 1 commit ahead of origin (d8920a6); drift-fix changes are unstaged for the user to review and commit.

### 2026-05-09 (later) — Doc split + README "project soul" pass

- Split `docs/architecture.md` (1464 lines) into focused docs:
  - `docs/architecture.md` (~330 lines) — slim: principles, contracts, hub structure, A2A integration, structural request flow. Keeps Hub Internals + Backend Layer Mermaid diagrams.
  - `docs/tracing.md` (~140 lines) — extracted tracing prose plus the full instrumented request-flow sequence diagram (with HITL pause/resume).
  - `docs/skills.md` (~170 lines) — extracted skills section.
  - `docs/decisions.md` (~70 lines) — Appendix Design Decisions + Open Questions table + External Federation deep-dive.
  - `docs/configuration.md` (~110 lines) — extracted config schema, env var convention pointer, credential storage.
- Rewrote `README.md` (256 → ~140 lines) with a user-lens framing: example `fin do git commit` interaction up top, single user-friendly Mermaid diagram surfacing skills/tools/agents/approval (replaces the 4 developer-lens diagrams which moved to `docs/`), getting-started flow, 30-second config example. Deleted the 17-row Status phase table (milestones own that now).
- Deleted from old architecture.md: ASCII System Overview + Component Diagram (160 lines, redundant with new Mermaid), Directory Structure tree (110 lines), Implementation Phases (150 lines, git log territory), Future Considerations long-term/deferred bullets, Related Documents/Issues sections.
- Fixed link references: `AGENTS.md` x5 (architecture.md → specific deep-dives where relevant), `handoff.md` x1, `src/fin_assist/agents/skills.py:19` (architecture.md → docs/skills.md). `.coderabbit.yaml` references kept (architecture.md still canonical for component contracts).

### 2026-05-09 (earlier) — Context-strategy refactor

- Added `Context Strategy` section to `AGENTS.md` documenting the surface/job/cadence table and the issue-vs-milestone rule.
- Slimmed `AGENTS.md` "Session Handoffs" subsection to match handoff.md's narrowed role.
- Pruned `handoff.md` from 625 lines to its actual job: current state header + Design Sketches + rolling session log. Removed the Implementation Progress table, the Sequenced Roadmap table (milestones own this now), the Tracing/_TaskTracer/Skills-API historical implementation logs (git log territory), the Historical Reference section, and the duplicated Notes/Quick-Start sections.

### 2026-05-09 (earlier) — v0.2 planning

- Backlog grooming pass: 84 → 57 open issues. Closed 27 stale items (shipped, Textual-era, duplicates, superseded). Chore-batched 9 small items into v0.1.1.
- Created four GitHub milestones with descriptions: [v0.1.1](https://github.com/ColeB1722/fin-assist/milestone/1), [v0.2](https://github.com/ColeB1722/fin-assist/milestone/2), [v0.2.1](https://github.com/ColeB1722/fin-assist/milestone/3), [v0.3](https://github.com/ColeB1722/fin-assist/milestone/4).
- Aligned on sub-agents as v0.2 anchor (rejecting transitive `requires` field on skills); split into in-process (v0.2) vs federated (v0.3) flavors with shared caller-side API. Captured as Design Sketch above.

### 2026-05-03 — Skill loading refactor (v0.1)

Implemented REPL `/skills` + `/skill:<name>` commands with `SkillCompleter` (rapidfuzz fuzzy matching, mirrors `@file:` pattern), skill tracing attributes/spans (`fin_assist.skill_load`, `fin_assist.cli.skill`), and updated docs. Tool gating, agent-level `tool_policies`, `base_tools` defaults, `skills/invoke` + `GET /skills` endpoints, REPL slash-command loading, `fin list skills`. 940 tests passing. v0.1 shipped as PR #114, tagged `v0.1`.
