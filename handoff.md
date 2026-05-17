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

**2026-05-17 (take-stock pass — sessions 4–7 closed out):** PR #152 (MCP + tooling context overhaul) and PR #159 (CI required-check deadlock fix) are both on `main`. Foundation hardening is materially complete; v0.1.1 milestone went from 9 → 7 open after a hygiene pass: closed four shipped-but-still-open issues (#141, #142, #115, #129) and milestoned #156 into v0.1.1, #158 into v0.1.2.

**Shipped via PR #152 (commit `045ce87`, sessions 4–6 condensed):**

- **#142 — skill type collapse.** `SkillDefinition`/`SkillCatalog` removed; `SkillConfig` is the unified type with a `name` field; `SkillManager` absorbs catalog rendering.
- **#84 + #141 — MCP integration + annotation-aware approval policies.** `mcp>=1.26.0` direct dependency; `MCPToolProvider` connects to configured MCP servers at startup; tools register as `mcp.<server>.<tool>`; `_annotations_to_policy` in `agents/mcp.py` maps `ToolAnnotations` → `ApprovalPolicy` per the table in `docs/decisions.md` §MCP integration; `MCPServerConfig`/`MCPSettings` in config schema. Wired through `cli/main.py`, `hub/factory.py`, `hub/app.py`. 22 new tests.
- **#129 + #115 — context provider architecture resolved (Option B Phase A).** `ContextProviderRegistry` in `src/fin_assist/context/base.py`; `FileFinder`, `GitContext`, `ShellHistory`, `Environment` all register via `create_default_context_registry()`. Both `@`-completion and tool-delegation paths now share one registry instance (split-brain problem from the 2026-05-10 audit is gone). `@env:VAR` resolves through the registry. Phases B–D have their own issues (#153 / v0.2 / v0.3).
- **PR #152 self-review triage (21 comments):** inline fixes for imports/typing/test patch targets/`load_from_config` simplification; folded comments into #139 / #154; filed #155 (built-in tool schemas as pydantic), #156 (per-subcommand approval at executor — now milestoned v0.1.1), #158 (MCP `isError` + `structuredContent` — now milestoned v0.1.2).
- **Triage discipline lesson:** when a self-review comment asks "is X true?" / "shouldn't Y exist?", *verify before filing a deferred-audit issue*. Cost is usually trivial; the deferral itself is the busywork. Captured in the "Verify before filing" rule.

**Shipped via PR #159 (commit `3420ee2`, session 7):**

- **CI required-check deadlock fixed.** `paths-ignore: [docs/**, *.md]` + ruleset-required `format`/`lint`/`test` was a deadlock for doc-only PRs (skipped workflow → required checks perpetually pending). Reworked `ci.yml` to drop `paths-ignore` *and* add a `ci-required` sentinel job (skipped = success). Ruleset updated to require only `ci-required`; future jobs added by listing them in `ci-required.needs`. Industry consensus (DevOps Directive Aug 2025) grounded the choice. Full write-up in `docs/decisions.md` § CI required checks.
- **Process lesson:** PR #152 was merged before its handoff doc-update commit (`a925b5d`) was pushed. The "Pre-Merge Documentation Discipline" section in `AGENTS.md` was renamed and tightened in response — code, tests, and docs are one logical unit per commit.

**Open in v0.1.1 (7 issues):** #85 (GitContext limits), #89 (system prompts — design-first), #123 (skill tracing wiring), #124 (`/connect`), #125 (SKILL.md runtime wiring), #135 (dogfooding repo agent), #156 (per-subcommand approval at executor).

## Next session

**Recommended sequence:**

1. **#125 + #123 together** — same code paths (SkillManager + tracing). One PR delivers "SKILL.md actually loads at runtime *and* emits a span when it does." Highest-leverage v0.1.1 closer; pre-empts a v0.1.2-demo embarrassment where `fin list skills` shows files that don't actually load.
2. **#85** — small, safe, closes the unbounded `git diff` output gap. Easy follow-up.
3. **#156** — per-subcommand approval at executor. Code comments in `agents/tools.py:306, 334` already reference this issue as a known v0.1.x deferral; landing it removes the "see #156" annotations.
4. **#124** — `/connect` UX. Probably best paired with v0.1.2 README/demo work since the demo benefits from a polished first-run flow.
5. **#135 dogfooding** — v0.1.1 exit gate. Best done *after* the above so it actually validates the foundation it's meant to validate.
6. **#89** — defer or split as a design-first issue. The "loadable markdown files" question is real but the design conversation hasn't happened yet; not a blocker for v0.1.1 ship.

**Sequence:** v0.1.1 (7 issues left, ~half-day to a few days of work) → [v0.1.2](https://github.com/ColeB1722/fin-assist/milestone/5) (visibility, README badges + demo, plus #151/#153/#158 MCP follow-ups) → [v0.1.3](https://github.com/ColeB1722/fin-assist/milestone/6) (CLI grammar v2 + async cascade) → [v0.2](https://github.com/ColeB1722/fin-assist/milestone/2) (sub-agents).

**Earlier session context (kept for reference):**

- **2026-05-15:** Windows `fin start` background-detachment fixed (multi-layer bug: Unix-only `fcntl`, wrong `creationflags`, `pythonw.exe` swap that broke uv installs). Final combination: `CREATE_NO_WINDOW` + `STARTUPINFO(SW_HIDE)`. See [`docs/decisions.md`](docs/decisions.md#fin-start-background-spawn-on-windows).
- **2026-05-10:** Audited `AgentCardMeta` field wiring — `serving_modes` is the only enforced field; the rest (`supported_context_types`, `supported_providers`, `supports_model_selection`, `supports_thinking`) are declarative-only. Provider filtering + model selection + thinking gate deferred to v0.2.1 milestone notes.

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

### ToolProvider + ContextProvider Protocols: Unifying Provider Registration (sketched 2026-05-10, extended 2026-05-16)

**Status:** Resolved / canonical. #129 closed with Option B; this sketch is now the implementation plan for v0.1.1–v0.3. Ship progressively through v0.2–v0.3.

**Extension (2026-05-16):** The context-provider system has the same fundamental shape as the tool-provider system. #129 (context provider architecture) resolved to parallel-phased rollout. The two tracks are designed together and ship in lockstep. See [comment on #129](https://github.com/ColeB1722/fin-assist/issues/129) for the full architecture argument; the parallel phasing table is below in "Progressive shipping plan."

**Problem:** `create_default_registry()` hardcodes 5 tools into `ToolRegistry`. Skills *reference* tools by name but can't *define* them. MCP (#84) adds a second tool source. The platform is becoming a tool host, but the registration architecture is still "platform defines, agents consume." This is the anti-pattern — tools should be discoverable from the agent's own repo/context, not hardcoded in the platform.

**Parallel problem for context (#129):** The context system has two incoherent paths (`@`-completion and tool calls) that share an ABC but no instances, no caches, no resolution logic. Context providers are second-class compared to tools — there's no `ContextProvider`-discovery mechanism, no way for skills/agents to declare which providers they need, and no path for MCP or file-based packages to contribute providers. Resolving this in lockstep with the ToolProvider extraction means the protocol shape can be designed once and applied twice.

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

#### Progressive shipping plan (parallel tracks)

| Phase | ToolProvider track | ContextProvider track | Milestone |
|-------|--------------------|------------------------|-----------|
| **A** | Extract `ToolProvider` protocol; refactor `create_default_registry()` into `BuiltinToolProvider`; `ToolRegistry.add_provider()`. Zero behavior change — same 5 tools, same API. | Extract `ContextProvider` protocol (already exists as ABC, needs registry shape); build `ContextProviderRegistry`; migrate the 5 existing providers (FileFinder, GitContext, ShellHistory, Environment, GitContext-status) onto it. Unify `@`-resolution and tool-delegation through one registry, fixing the `git`-tool-bypasses-`GitContext` problem. Finally wires Environment (#115). | v0.1.1 (#84, #129) |
| **B** | `MCPToolProvider` — MCP servers discovered from config → `discover()` returns `ToolDefinition` per MCP tool. | `MCPContextProvider` — MCP spec already separates tools from *resources*; this track surfaces resources as context providers. | v0.1.1 (#84) |
| **C** | `FileToolProvider` — `.fin/tools/` discovery + `@tool` decorator. First new capability where tools are not defined by the platform. | `FileContextProvider` — `.fin/context/` discovery. Plus config wiring for `base_context_providers` on `AgentSpec` and `context_providers` on `Skill`, parallel to `base_tools` / `tools`. Sub-agents (v0.2) inherit scoped provider sets the same way they inherit tools. | v0.2 (sub-agents need per-agent tool + context sets) |
| **D** | Repo-as-package: `.fin/tools/` + `.fin/skills/` + `evals/`. | Repo-as-package gains `.fin/context/`. Planning agent (#147) is the motivating package: ships `gh_state` + `recent_decisions` providers alongside `triage` / `breakdown` / `reflect` skills. | v0.3 (federated agents + eval) |

Phase A is the critical path for **both tracks** — if #84 ships without `ToolProvider`, MCP tools get bolted onto `create_default_registry()` and the retrofit is harder; if #115 (Environment) ships without `ContextProviderRegistry`, the second incoherent context path gets a sixth hardcoded entry and the retrofit is also harder. Each protocol costs ~50 lines; they should land together in v0.1.1 before #84 or #115 finalize.

**Mental model the two tracks share:** "platform-defined → MCP-contributed → file-defined → repo-packaged" is the progression of who-owns-what. Tools and context providers travel through the same progression. Skills *reference* both by name. Agents declare *base* sets of both. Packages bundle both. The dual structure means there is one packaging story, not two.

**Refresh semantics for context providers (open question):** Tools are stateless / self-managed. Context providers may want explicit caching — `gh_state` is expensive and should refresh on a schedule, not per-session. Lean: each provider self-manages, but the protocol carries `last_refreshed_at` for observability. Defer cache layer to providers that need it.

#### Relation to sub-agents (v0.2)

Sub-agents (`invoke_subagent`) construct a fresh `AgentSpec` with a constrained tool set **and** a constrained context-provider set. With `FileToolProvider` + `FileContextProvider`, a sub-agent's tools and providers can both come from its own `.fin/tools/` and `.fin/context/` directories rather than the global registries. The `Executor.run_subtask()` call creates scoped `ToolRegistry` and `ContextProviderRegistry` instances with only the sub-agent's contributions.

This also means `invoke_subagent` can be replaced: instead of a hardcoded built-in tool, it becomes a file-defined tool in `.fin/tools/subagent.py`. The platform ships *defaults*, not *mandates*. The same applies to context providers — `gh_state` is not a built-in, it's a provider the planning agent package contributes.

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

### 2026-05-17 — CI selective execution on doc-only PRs

Followed up on the "later" that PR #159's decisions.md explicitly anticipated. PR #161 (a handoff-only update) had spun the full suite (`format` + `lint` + `typecheck` + `test` + `test-windows`, ~6–9 min cached + a Windows VM) and the friction was real for in-between merges. Researched 2025 patterns ([costops.dev](https://costops.dev/guides/docs-changes-trigger-full-ci), [dorny/paths-filter](https://github.com/dorny/paths-filter)) and confirmed there's exactly one viable pattern that's both selective *and* compatible with required checks: job-level `if:` gating driven by `dorny/paths-filter`.

**Why not just move `handoff.md` to `docs/`:** doesn't solve the problem — there's no `paths-ignore` to match against (PR #159 deliberately removed it). Also flattens the deliberate signal that `handoff.md` is rolling-context vs. the forever-docs in `docs/`. AGENTS.md § "Doc surfaces" makes this distinction load-bearing.

**Implementation:** added a `changes` job to `ci.yml` that runs `dorny/paths-filter@v4` with `predicate-quantifier: 'every'` and a `**` + negation filter. The five expensive jobs gate on `needs.changes.outputs.code == 'true'`. Doc-only PRs skip them; the `ci-required` sentinel still aggregates and reports success per GitHub's skipped-job semantics. Lockfiles, `pyproject.toml`, `justfile`, `flake.*`, `devenv.*`, and `.github/workflows/**` deliberately count as "code" so environment/CI changes still exercise the full suite. Full rationale in [`docs/decisions.md` § CI required checks → Selective execution](docs/decisions.md#ci-required-checks).

### 2026-05-15 — Windows `fin start` background detachment fixed

The original 10s-timeout failure on a corporate-EDR Windows machine turned out to be three stacked bugs:

1. **`fcntl` import crash in `pidfile.py`** — Unix-only module. Resolved by merging the in-flight PR branch `55a153c` which replaced `fcntl` with the cross-platform `filelock` library + sidecar `.lock` file pattern. Also brought in `_pid_is_running_win32` / `_force_kill_win32` for Windows process-existence checks and `_cleanup_pid_files` for sidecar cleanup.
2. **Wrong subprocess creationflags** — `start_new_session=True` (default Unix idiom in `Popen`) maps to `CREATE_NEW_PROCESS_GROUP` on Windows, which corporate EDR blocks silently. Iterated through `DETACHED_PROCESS | CREATE_NO_WINDOW` (worked on personal Windows, console window flashed on corporate) and a `pythonw.exe` swap (broke uv-managed installs entirely — process exited immediately).
3. **Final working combination:** `CREATE_NO_WINDOW` + `STARTUPINFO(STARTF_USESHOWWINDOW, SW_HIDE)`, no `DETACHED_PROCESS`, no `CREATE_NEW_PROCESS_GROUP`, `python.exe` not `pythonw.exe`. Confirmed working on both personal and corporate Windows. Hub starts invisibly, `/health` responds, survives terminal closure.

Tests: `tests/test_cli/test_server.py::TestSpawnServe::test_windows_uses_hidden_console_session` asserts exact flag combination (runs on Windows CI). `test_unix_uses_start_new_session` prevents the Unix path being polluted with Windows flags. Both branches now have explicit regression coverage. 947 tests passing.

Full write-up in [`docs/decisions.md`](docs/decisions.md#fin-start-background-spawn-on-windows) documenting the *full* problem space (what we tried, why each attempt failed, why the final combination is the one we want). The "why deferred" rationale for each rejected flag is preserved so future contributors don't re-try them.

### 2026-05-12 — Windows dev ergonomics shipped

Cross-platform justfile (`set windows-shell`), platform-aware `DATA_DIR` in `paths.py` (`%LOCALAPPDATA%\fin` on Windows), CI `test-windows` job, and 14 test-fix buckets (sidecar PID lock, `encoding="utf-8"`, `_force_kill`/`TerminateProcess`, `re.escape` in match). See [`docs/decisions.md`](docs/decisions.md) (Windows section) and [`README.md`](README.md) (non-Nix quick start).
