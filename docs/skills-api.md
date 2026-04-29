# Skills API — Design Sketch

**Status:** Sketch, pre-implementation. Iterated 2026-04-28 — cross-tool format compat, `lookup` scope, and approval-direction decisions resolved (see §9). Sections marked "To be decided" are explicitly parked for resolution during implementation.

**Inspiration:** Anthropic's [skills.md](https://code.claude.com/docs/en/skills) pattern (directory of markdown files + frontmatter, progressive disclosure, on-demand body loading). [OpenCode's](https://open-code.ai/en/docs/skills) parallel implementation confirms the pattern is converging across agent tooling.

**Scope:** replaces the "Skills API" section of `handoff.md`. Supersedes (and, on implementation, closes) GitHub issues [#98](https://github.com/ColeB1722/fin-assist/issues/98), [#89](https://github.com/ColeB1722/fin-assist/issues/89), and [#84](https://github.com/ColeB1722/fin-assist/issues/84).

---

## 1. Motivation

Three concrete gaps drive this design:

1. **Scoped CLI tools with blanket approval.** The git agent (#79) introduced `git` and `gh` as prefix-scoped tools. Every subcommand requires approval today — `git diff` is as gated as `git push --force`. The TODO at `src/fin_assist/agents/tools.py:213` is explicit about this being a temporary state.
2. **Prompt steering is agent-scoped and one-off.** `WorkflowConfig` (on `AgentConfig`) lets an agent declare named tasks with entry prompts and system-prompt overrides. Useful, but workflows don't travel across agents, aren't discoverable from outside config, and require Python registration of prompt templates.
3. **No path for user- or community-authored capabilities.** Today, adding a task to fin means editing `src/fin_assist/llm/prompts.py` (register template), `src/fin_assist/config/schema.py` or `config.toml` (declare workflow), and shipping Python code. No "drop a markdown file in a directory" path.

The skills.md pattern addresses all three: per-task directories with markdown frontmatter + body, discovered via filesystem walk-up, loaded on demand, invocable as first-class structured actions.

## 2. Concept model

Three concepts, strict containment, no overlap.

### Tool

A callable primitive registered with the hub's `ToolRegistry`. Defined today in `src/fin_assist/agents/tools.py`. Examples: `git` (scoped CLI prefix), `gh`, `read_file`, `run_shell`.

- Has a **base approval policy** (`ApprovalPolicy` with subcommand rules — see Phase A).
- Has a schema (for LLM tool-call surface) and an async callable (for execution).
- Zero framework imports (`agents/` is platform, not transport).
- **Unchanged by this design** except for the subcommand-approval extension in Phase A.

### Skill

A named, invocable task. Maps 1:1 to A2A's `AgentSkill` type (already used in `src/fin_assist/hub/factory.py`). Backed by an on-disk `SKILL.md` file (frontmatter + body).

A skill declares:

- **name, description** — `AgentSkill` fields (protocol-native, shared across agent tooling). `name` doubles as the skill identifier; description is short (one paragraph, always-in-prompt).
- **fin.tools** — list of tool IDs this skill uses. Attaching the skill to an agent unions these into the agent's effective toolset.
- **fin.approval** — per-tool, per-subcommand policy overrides applied **only while this skill's invocation is active** (see §6).
- **fin.entry_prompt** — message injected when the skill is invoked via the A2A `skills/invoke` RPC method.
- **body** — the rest of `SKILL.md`, loaded on-demand via the `lookup` tool (see §5).

**Frontmatter shape.** The top-level fields `name` and `description` match the emerging cross-tool `SKILL.md` convention (Anthropic's skills.md, OpenCode's skills). Fin-specific extensions live under a `fin:` namespace, mirroring the `[tool.ruff]` / `[tool.pytest]` pattern in `pyproject.toml`. This means:

- A fin `SKILL.md` is readable by other tools that adopt the shared format — they see `name` and `description`, ignore the `fin:` block.
- A skill authored for another tool is loadable by fin (with defaults for missing `fin:` fields).
- The `fin:` block is the natural payload for the A2A card extension (`fin_assist:skills`) — frontmatter and wire format line up one-to-one.

Cross-directory discovery (reading `.claude/skills/` or `.opencode/skills/`) remains deferred — see §3.

Example `SKILL.md` frontmatter:

```yaml
---
name: pr
description: >
  Generate a conventional commit, stage the right files, push the branch,
  and open a PR with a summary derived from the diff.
fin:
  tools: [git, gh]
  approval:
    git:
      # Within this skill, `git push` is pre-approved (normally gated)
      - { pattern: "push*", mode: "never" }
  entry_prompt: |
    The user wants to create a pull request. The full procedure is
    included below — follow it step by step. If any tool call fails,
    stop and ask for help.
---

# Creating pull requests

## Step 1 — Understand the change
[full instructions body — eagerly injected into the system prompt
when this skill is invoked; `lookup` is not available in this mode.
See §5 for invocation-mode semantics.]
```

### Agent

An agent declares:

- Base identity (name, description, system_prompt, serving_modes) — unchanged from today.
- **Attached skills** — list of skill IDs the agent exposes.
- **Baseline tools** (optional) — tools the agent has available even outside any skill invocation (e.g., `read_file` for an agent meant to do ad-hoc code exploration).

An agent's **effective toolset** when no skill is active:

```
baseline_tools ∪ (tool for skill in attached_skills for tool in skill.tools)
```

An agent's **effective toolset** during a skill invocation:

```
baseline_tools ∪ active_skill.tools
```

(Other attached skills' tools aren't removed — we don't hide capabilities mid-turn — but the active skill's approval overrides take precedence for its declared tools. See §6.)

### What was "Workflow" — gone

Previous design iterations carried a fourth concept, `Workflow`, for prompt-steered sub-tasks. This is fully absorbed by Skill. A "workflow" was always just "a skill with specific steering, tool attachments, and an entry prompt" — the A2A-native framing makes that explicit and removes a redundant vocabulary tier.

Migration: current `AgentConfig.workflows` dict becomes skill files. Each workflow entry → one `SKILL.md`. The `WorkflowConfig` type can be deleted after migration.

## 3. Storage and discovery

### Directory layout

```
.fin/skills/<skill-id>/
  SKILL.md                # required: frontmatter + body
  scripts/                # optional: supporting files
    generate-pr.sh
  examples/               # optional: reference material
    good-pr.md
```

Single-file skills (no supporting assets) can live as `.fin/skills/<id>/SKILL.md` directly — the directory exists solely to be a home for the bundle if/when it grows.

### Search paths

**Project-local (walk-up from CLI's cwd):**

Starting at the CLI's cwd, walk upward through parent directories until the git worktree root (or filesystem root if not in a git repo). At each level, collect any `.fin/skills/` directory.

This means a monorepo can have global skills at the repo root and package-specific skills deeper in the tree. Running a command inside a package picks up both.

**User-global:**

`~/.config/fin/skills/` — user's personal skills, available in any project.

**Precedence on id collision:**

First-match-wins, nearest-cwd-first. Concretely:

1. `./.fin/skills/<id>/` (deepest, CLI cwd)
2. `<ancestor>/.fin/skills/<id>/` (walking up toward git root)
3. `~/.config/fin/skills/<id>/` (user-global)

A skill defined closer to the user's working context shadows a farther-out skill with the same id. Duplicates in farther-out locations are silently ignored (but a log line at DEBUG level notes the shadow).

### Cross-tool compatibility

Split into two concerns, deliberately asymmetric:

**File format compatibility (shipped in Phase B).** Fin's `SKILL.md` shape follows the emerging cross-tool convention — top-level `name` and `description`, fin-specific extensions namespaced under `fin:` (see §2). A skill authored for Claude Code or OpenCode that uses only the shared fields loads in fin without a translation layer; a fin-authored skill that uses only the shared fields loads in the other tools.

**Cross-directory discovery (deferred).** Fin reads only `.fin/skills/` and `~/.config/fin/skills/` in Phase B. Reading `.claude/skills/` or `.opencode/skills/` is not shipped — but the discovery loader takes its root list as a parameter, so opening up additional roots later is a config-plumbing change, not a refactor. The eventual surface is likely:

```toml
[skills]
# Default omitted; fin-only roots applied.
discovery_paths = [".fin/skills", ".claude/skills", ".opencode/skills"]
```

Opt-in, per-project. Ship when there's user demand.

### When discovery runs

**CLI is responsible for walk-up discovery.** The hub is a daemon; its cwd is not meaningful to any given user action. The split:

1. CLI performs walk-up at command-invocation time, collecting discovered skill paths.
2. CLI sends the path list to the hub on A2A connection.
3. Hub loads `SKILL.md` files from those paths on first use, caches by absolute path.
4. Cache invalidation: file mtime change → reload on next access. (Simple; no file watching needed for Phase B.)

**Rationale:** keeps the hub stateless about user directory context. Each CLI connection provides its own skill surface. Two terminals in two projects hitting the same hub get each project's skills independently. No persistent DB, no per-project index state, no launch-per-project requirement.

**To be decided during implementation:**

- Exactly how paths are transmitted — extension metadata on A2A `message/send`? Dedicated setup RPC? Header on the streaming call? Practical choice, doesn't change the model.
- How long hub-side cached skills live after the last referencing connection closes. Eager eviction vs. LRU cache.

## 4. A2A alignment

This is where the reframe earns its keep: fin's notion of "skill" maps onto A2A's `AgentSkill` type directly rather than being a parallel concept.

### Agent card publishing

Today, `hub/factory.py:111-118` publishes one `AgentSkill` per agent card — a placeholder equal to the agent itself. Under this design, `AgentCard.skills` becomes the actual list of attached skills:

```python
agent_card = AgentCard(
    name=agent.name,
    ...
    skills=[
        AgentSkill(
            id=skill.id,
            name=skill.name,
            description=skill.description,
            tags=skill.tags,
        )
        for skill in agent.attached_skills
    ],
    ...
)
```

Fin-specific skill metadata (tools list, approval overrides, entry_prompt reference) rides on an extension. The existing `fin_assist:meta` extension at `src/fin_assist/hub/factory.py:104` can grow a `skills` field, or a new `fin_assist:skills` extension can be added — minor call at implementation time.

### `skills/invoke` RPC method

A2A supports **Method Extensions** ("Extended Skills" in the spec): custom RPC methods declared via extensions. This design registers a `skills/invoke` method on agent endpoints.

Shape (sketch — final schema TBD during implementation):

```
Request:
  skill_id: string
  args: { ... }              # optional skill-specific arguments
Response:
  task_id: string            # standard A2A task created; client streams updates
```

Semantics:

1. Client calls `skills/invoke` with a skill_id the agent supports.
2. Hub creates an A2A task (same machinery as `message/send`).
3. Hub builds the system prompt with the skill's **full body** eagerly injected (not just the description — see §5 for the rationale).
4. Hub assembles the task's toolset **excluding** the `lookup` tool. The body is already in-context; other skills' bodies are intentionally out of reach.
5. Hub seeds the task with the skill's `entry_prompt` as the first user message.
6. Hub marks the task with `active_skill_id` — one piece of state driving three effects: approval override lookup (§6), `lookup` availability (§5), and eager-body injection (this step).
7. Task proceeds normally: streams events, requests approval when needed, emits artifacts, terminates.

From the CLI's perspective: `fin do shell pr` routes to `skills/invoke(skill_id="pr")` on the shell agent instead of `message/send`. `fin do shell "free-form message"` still uses `message/send` — unstructured invocation remains supported.

### Invocation paths summary

| Path | Entry point | When used |
|---|---|---|
| Unstructured | A2A `message/send` | `fin do <agent> "<message>"` — free-form task |
| Skill-invoked | A2A `skills/invoke` extension | `fin do <agent> <skill-id>` — named task, structured seeding |
| `@`-completion | CLI-only, pre-send | `@file:foo.py`, `@git:diff` — user forces context into the prompt |

`@`-completion is **orthogonal** to skills. It is a CLI ergonomic for splicing context into prompts before send, owned entirely by `cli/context/` (see §7). No A2A involvement, no hub roundtrip, no overlap with skill invocation.

## 5. The `lookup` tool

One of the skills.md pattern's core ideas is **progressive disclosure**: short descriptions in the system prompt (cheap, always-on), full bodies loaded on demand (expensive, only when needed). Fin adopts this via a built-in `lookup` tool available to every agent that has attached skills.

### Shape (Phase B)

```
lookup(skill_id: string) -> string
```

- Takes a skill_id.
- Returns the body of that skill's `SKILL.md` (everything after the frontmatter).
- Scoped to the invoking agent's attached skills — an agent can only lookup skills it has.
- Approval: `never` (reads are free).

That is the entire Phase B shape. One signature, one behavior, no corpus scoping, no tags, no caching semantics to learn.

### Availability by invocation mode

**Design decision:** `lookup` availability is a function of invocation mode. The two modes have distinct prompt shapes and distinct tool surfaces.

| Mode | Entry | System prompt additions | `lookup` tool |
|---|---|---|---|
| **Free-form** (`message/send`) | `fin do git "..."` | Short descriptions of all attached skills | Available |
| **Skill-invoked** (`skills/invoke`) | `fin do git pr` | Active skill's **full body**, eagerly injected | **Not available** |

**Rationale:**

1. **No wasted roundtrip.** If the user explicitly invoked skill `pr`, the model shouldn't need a tool call to load the procedure — we already know which one it needs. Eager injection collapses that indirection.
2. **Pollution containment.** A skill's body may contain literal tool calls (`git push --force-with-lease`). If that body is reachable via `lookup` while a different skill is active, the model could lift the wrong command into the wrong context. Cutting `lookup` during skill invocation makes each skill's safety model hermetic — body and approval overrides are both scoped to the active invocation. This mirrors the invocation-scoped approval rule in §6; the two behaviors are duals keyed off the same `active_skill_id` state.
3. **Distinct prompt-budget profiles.** Free-form pays N × short-descriptions cost (cheap, always-on), bodies on demand. Skill-invoked pays 1 × full-body cost (expensive but targeted), nothing else. Neither mode pays both.

**What about composition?** A skill whose body calls `lookup("other-skill")` would, under this rule, fail — `lookup` isn't registered during skill invocation. This is intentional for Phase B. If composition emerges as a real need, the resolution is a `compose: [other-skill]` frontmatter field that re-enables *scoped* `lookup` for explicitly declared skill ids. See open question #7.

### Why ship it in Phase B

- Locks in the right authoring habit from day one: "description in frontmatter, details in body."
- Enables the pattern where a skill's `entry_prompt` says "call `lookup('pr')` to load the procedure." This is the core reusability mechanism.
- Keeps prompt budget controlled: system prompt carries N short descriptions, not N full bodies.
- ~50 LOC to implement: hub has the bodies loaded already (§3), `lookup` just returns them.

### What Phase B explicitly doesn't do

- No free-form topic lookup (`lookup(topic="conventional-commits")`) — see below; this is a different product, not a deferred mode of the same tool.
- No arbitrary-corpus retrieval from `.fin/docs/` or similar. `lookup` reads only skill bodies.
- No caching of lookup results (hub already caches `SKILL.md` parsing; tool call overhead is negligible).
- No cross-agent leakage: skill_ids outside the invoking agent's attached skills return an error.

### `lookup(skill_id)` is a jump table, not a retrieval tool

A tempting extension is `lookup(topic)` — give the model a free-form string, resolve against a local docs corpus. Explicitly rejected, because it's a **different product** dressed in the same tool name:

| | `lookup(skill_id)` (shipped) | `lookup(topic)` (not shipped) |
|---|---|---|
| Semantics | Jump table: enumerable ids, dict resolution | Retrieval: query → ranked passages |
| Backing store | Skill bodies (already parsed, already in memory) | Arbitrary markdown corpus requiring indexing |
| Failure mode | Clean: id not found → error, model recovers | Fuzzy: zero matches, wrong matches, or ok matches — model burns tokens on rephrased queries |
| Prompt-budget cost | Tool description lists N ids (bounded) | Tool description describes a corpus vaguely (unbounded or gambling on discoverability) |
| Implementation | ~50 LOC dict wrap | Vector store or FTS engine, embedding model, index refresh strategy, chunking decisions |
| Eval story | Did the id resolve? Trivial. | Retrieval precision/recall — needs its own eval harness |
| When wrong | Look at the skill directory | Look at the corpus, the index, the chunker, the embedder |

If RAG-over-local-docs is ever valuable, it gets a **different tool name** (e.g. `recall`, `search_docs`) with its own return type (passages, not whole bodies) and its own failure semantics. Conflating the two forces the tool's description to be weasel-worded ("maybe a skill, maybe a doc") and trains the model on fuzzy resolution semantics where precise semantics would do.

**The name `lookup` is reserved for skill-id resolution.** Tool names leak into skill bodies (`entry_prompt: "call lookup('pr')..."`); renaming later means rewriting skill bodies. Keep the semantics stable from day one.

Phase C can extend `lookup`'s shape if real pain emerges within the skill-id scope (e.g., scoped composition per open question #7). It does not grow into free-form retrieval.

## 6. Approval policy

Phase A introduces per-subcommand rules on `ApprovalPolicy`:

```python
@dataclass
class ApprovalRule:
    pattern: str            # fnmatch-style glob against the args string
    mode: Literal["never", "always"]
    reason: str | None = None

@dataclass
class ApprovalPolicy:
    mode: Literal["never", "always"]                 # fallback if no rule matches
    rules: list[ApprovalRule] = field(default_factory=list)
    reason: str | None = None
```

This ships **before** skills (Phase A), purely as a `ToolDefinition` enhancement. Git agent's `git diff` stops prompting.

### Skill-scoped overrides (Phase B)

A skill can declare per-tool approval overrides that apply **while that skill is the active invocation**:

```yaml
fin:
  approval:
    git:
      - { pattern: "push*", mode: "never" }
    gh:
      - { pattern: "pr create*", mode: "never" }
```

**Semantics:**

- Tool `X` has a base policy defined at registration.
- When skill `S` is invoked and declares overrides for tool `X`, those overrides are **prepended** to `X`'s rule list for the duration of `S`'s invocation.
- Rule resolution remains first-match-wins. Override rules match first; fall through to base policy.
- When no skill is active (unstructured invocation), only base policies apply.

**Why skill-scoped rather than agent-scoped merge:**

Merging all skills' overrides into a single agent-wide policy would mean the `pr` skill's loosened `git push` rule applies even during a `commit` skill invocation. That breaks scope discipline. Per-invocation context keeps each skill's safety model local to its task.

**Implementation plumbing:**

The executor needs to know "which skill's context is this tool call inside." The cleanest way: the `skills/invoke` RPC marks the task with `active_skill_id`; executor reads it when evaluating a tool call; `ToolDefinition.approval` lookup becomes `approval.for_skill(active_skill_id)` instead of a bare attribute read.

**One state, three effects.** `active_skill_id` drives (1) approval override resolution (this section), (2) `lookup` tool availability (§5), and (3) eager body injection into the system prompt (§4). All three collapse onto the same piece of state — no new coupling introduced by any one of them.

### Direction of overrides: loosen-only

Phase B ships **loosen-only** overrides. A skill can take a gated operation and ungate it within its scope (`always → never`); it cannot take an ungated operation and gate it (`never → always`).

**Enforcement is config-time, not runtime.** At skill-load time the loader compares each override against the tool's base policy. A tightening override fails the load with a clear error:

```
Error in .fin/skills/production-deploy/SKILL.md:
  fin.approval.read_file[0] tries to tighten base mode 'never' → 'always'.
  Phase B supports loosening only; see docs/skills-api.md §6.
```

**Why asymmetric:**

1. **Loosening has a grounded use case** — it's the whole motivating UX problem. Running `fin do git pr` should not produce four sequential approval prompts for operations the user explicitly invoked the skill to perform.
2. **Tightening is speculative** — no current skill design needs it. The "production-deploy gates read_file" example is plausible but hypothetical.
3. **Tightening has a worse failure mode.** Loosening's worst case is "a thing ran I expected to be asked about" — bounded by what the skill declares. Tightening's worst case is "I invoked a skill expecting it to Just Work and it prompted me five times mid-flow" — happens *inside* supposedly-automated work, and is harder to predict because the user has no prior sense of which normally-free operations a given skill might gate.
4. **The one-direction mental model is shorter.** "Skills can only make their declared tools more permissive than baseline." One sentence. Two-directional overrides invite edge-case reasoning (what if two skills tighten and loosen the same tool, what if base and override both match, etc.) — nothing hard, but nothing we need to explain either.

**Escape hatch for future work.** If a real case for tightening emerges, the preferred path is an explicit per-skill opt-in rather than removing the check globally:

```yaml
fin:
  approval_allow_tighten: true   # off by default
  approval:
    read_file:
      - { pattern: "*", mode: "always" }
```

This keeps tightening visible at the skill level — a reviewer never has to wonder whether a skill tightens anything, they just check for the flag. Much better than silently relaxing the validation for all skills.

### To be decided during implementation

- How to surface the active skill in `StepEvent` / tracing spans (Phase D Phoenix integration). Likely a span attribute `skill.id`.

## 7. `@`-completion stays CLI-only

The `@`-completion system (`AtCompleter`, `resolve_at_references`, `ContextProvider`) is a user-side ergonomic — "easier copy-paste into the prompt." It does not go through the hub, does not know about skills, does not involve A2A.

### Clarification on ownership

Currently `ContextProvider` lives in `src/fin_assist/context/`. As part of this work (or a follow-up cleanup), it likely moves to `src/fin_assist/cli/context/` to reflect its actual scope. The hub never consumes these providers — the CLI calls them pre-send and splices resolved content into the message text.

**Why this matters for the design:** in earlier iterations, I proposed unifying `@`-completion with skill invocation (via the `skills/invoke` RPC method). That proposal is withdrawn. Two intake paths with zero code overlap is simpler than one path with dual modes. `@git:diff` and the `git` tool both run `git diff` underneath — they don't need to share a code path.

`ContextProvider` and its implementations (`FileFinder`, `GitContext`, `ShellHistory`) are kept as-is. They neither replace nor are replaced by skills.

## 8. Phasing

The design is split into three shippable phases. Each is independently useful; each exit gate is a real user-visible behavior.

### Phase A — Subcommand approval rules

**Goal:** `git diff` runs un-gated; `git push` still asks. Highest-value slice of the user's idea, aligned with the explicit TODO at `tools.py:213`.

**Scope:**

- Extend `ApprovalPolicy` with `rules: list[ApprovalRule]`.
- Scoped CLI tool callable becomes policy-aware: per-invocation evaluation of `args` against rules.
- Backend adapter: switch from static `requires_approval` flag to per-call `policy.evaluate(args)`.
- Rules are Python-defined in `create_default_registry()` — **no config schema change**.

**Exit gate:** through the git agent, `git diff` runs without an approval prompt; `git push` still pauses. TDD-first per `AGENTS.md`.

**Estimate:** ~4 source files touched, ~2 new test files, ~200 LOC + tests.

**Does not ship:** skills, `SKILL.md` discovery, `lookup` tool, `skills/invoke` RPC, card-level skill publishing.

### Phase B — Skills as A2A-native capabilities

**Goal:** users can author skills as markdown files, invoke them structurally via `fin do <agent> <skill>`, and compose them across agents.

**Scope:**

- `src/fin_assist/skills/` package (currently an empty placeholder at `architecture.md:291`):
  - `definition.py` — `SkillDefinition`, frontmatter schema
  - `loader.py` — parses `SKILL.md` (frontmatter + body)
  - `discovery.py` — walk-up + user-global search logic (**CLI-side**)
  - `registry.py` — hub-side cache keyed by absolute path, mtime-invalidated
- `config/schema.py` changes:
  - Remove `AgentConfig.workflows` (migrated to skill files).
  - Add `AgentConfig.skills: list[str]` — skill ids attached to the agent.
  - `AgentConfig.tools: list[str]` remains for baseline tools (outside any skill).
- `hub/factory.py`: `AgentCard.skills` lists attached skills; fin-specific metadata via card extension.
- `hub/app.py`: register `skills/invoke` RPC method (A2A extension). Implementation seeds a task with skill's `entry_prompt` and tags it with `active_skill_id`.
- `agents/tools.py`: `ApprovalPolicy.for_skill(skill_id)` lookup; overrides merge.
- Executor: propagate `active_skill_id` through `StepEvent` / approval checks.
- `lookup` tool registered globally; scoped per-agent at call time.
- CLI:
  - `fin do <agent> <skill-id>` routes to `skills/invoke`.
  - `fin do <agent> "<message>"` remains for free-form.
  - Walk-up discovery at command time; paths passed to hub on connect.
  - `fin list skills` reads agent cards, shows attached skills across all agents.

**Migration of existing workflows:**

The git agent's three workflows (commit, pr, summarize) from `config.toml` become three `SKILL.md` files under `.fin/skills/`. `WorkflowConfig` type deleted.

**Exit gate:** at least two real skills authored as `SKILL.md` files (likely: `pr` and `commit`, migrated from git agent workflows), invocable via `fin do git pr`, with subcommand approvals working per skill context. `lookup` tool usable from within a skill invocation.

**Estimate:** ~5 new source files, ~5 modified, ~5 new test files, ~500 LOC + tests + config migration.

**Does not ship:** MCP as a skill source, progressive-disclosure beyond `lookup`, free-form `lookup(topic)` retrieval, cross-directory discovery (`.claude/skills/` / `.opencode/skills/`), skill composition (`compose:` frontmatter), approval tightening.

### Phase C — MCP, observability, stretch

**Goal:** skills from external sources (MCP), trace-backed visibility, optional extensions to `lookup`.

**Scope (speculative; exact contents depend on what Phase B surfaces):**

- **MCP as a skill source.** An MCP server's tools map to a skill bundle; `SKILL.md` can be synthesized or authored alongside. Closes current issue #84.
- **Phoenix/OTel integration** with `skill.id` as a span attribute, driven by the tracing work that should land *before* Phase C per the handoff roadmap.
- **`lookup` extensions** — topic-based retrieval, corpus scoping (`.fin/docs/`), cross-skill lookup — **only** if Phase B usage shows real pain.
- **Tool-type taxonomy** (the previous Phase C sketch in handoff) may re-enter here as a natural consequence of MCP-sourced skills needing type-aware instrumentation.

**Blocks on:** Phase B shipped; Phoenix tracing shipped; a concrete MCP consumer identified (likely `mcp-server-git` or a filesystem server).

**Exit gate:** at least one MCP-sourced skill works end-to-end; trace in Phoenix shows `skill.id` attribute on spans; ability to filter traces by skill.

## 9. Open questions parked for implementation

These are explicitly not blocking the start of Phase A. They will be resolved during Phase B implementation when the concrete choices have more signal:

1. **Skill-id namespace.** Flat (`pr`) or namespaced (`git.pr`)? Flat is simpler; namespaces might help at scale. Lean flat until collision pain appears.
2. **Skill path transmission over A2A.** How exactly does the CLI send discovered paths to the hub on connection — extension on `message/send`, dedicated setup RPC, headers on the streaming channel? Practical choice.
3. **Hub-side cache eviction.** How long do parsed `SKILL.md` stay in memory after the last referencing connection closes? LRU vs. eager eviction.
4. **Extension choice.** Fold skill metadata into existing `fin_assist:meta` extension or add `fin_assist:skills` as a separate extension? Separation is cleaner if the meta extension grows much more; merge if it stays small.
5. **`lookup` error contract.** If an agent calls `lookup(skill_id)` for a skill it doesn't have attached, what happens? Tool returns error string vs. raises. Affects LLM recovery behavior.
6. **Skill composition and scoped `lookup` during invocation.** Phase B's §5 design decision makes `lookup` unavailable during skill invocation (pollution containment). This forecloses the pattern where skill `pr` delegates to skill `commit` via `lookup("commit")`. If that pattern turns out to matter, the resolution is a `compose: [commit]` frontmatter field on `pr` that re-enables `lookup` *scoped to the declared ids only*. Considered and set aside in the Phase B design discussion — the cross-skill non-inheritance rules (tools, approval, bodies all stay hermetic) make the feature do so little that it didn't justify the surface area. Revisit when a real authoring pattern demands it.
7. **Cross-directory discovery.** Opt-in reading of `.claude/skills/` and `.opencode/skills/` via `[skills] discovery_paths = [...]` config (see §3). Loader is structurally ready; ship when there's demand. Format compatibility is already in place via the `fin:` namespace convention.

**Resolved in design discussion (2026-04-28):**

- **Cross-tool format compat:** adopted. `SKILL.md` uses top-level `name`/`description` (shared convention) with fin extensions under a `fin:` namespace. See §2.
- **`lookup(topic)` free-form retrieval:** rejected as a different product. The name `lookup` is reserved for skill-id resolution. RAG-over-local-docs, if ever added, gets a distinct tool name (`recall`, `search_docs`). See §5.
- **Approval tightening:** loosen-only in Phase B, enforced at config-load time. Future escape hatch is a per-skill `approval_allow_tighten: true` opt-in, not a global validation removal. See §6.

## 10. Relation to the wider codebase

**Current state of the repo:**

- Scoped CLI tools: `src/fin_assist/agents/tools.py:213,295`
- `ApprovalPolicy` (current two-mode version): `src/fin_assist/agents/tools.py:40`
- `AgentConfig.tools` and `AgentConfig.workflows`: `src/fin_assist/config/schema.py:99`
- Agent card publishing with one-skill placeholder: `src/fin_assist/hub/factory.py:111-118`
- `fin_assist:meta` extension: `src/fin_assist/hub/factory.py:103-106`
- Empty `skills/` placeholder: referenced at `architecture.md:291` (not yet created in source tree)
- `ContextProvider` implementations: `src/fin_assist/context/`
- `@`-completion surface: `src/fin_assist/cli/prompt.py`

**Closes (on Phase B completion):**

- Issue #98 — this document supersedes its scope
- Issue #89 — markdown-backed prompts are the skill body mechanism
- Issue #84 — MCP integration becomes Phase C (skill source) rather than a standalone tool-source concern

**Enables (future work):**

- Remote skill install (`fin skill install <url>`) — skills are just directories, so installation is `cp` or `git clone`. A lightweight catalog DB might emerge for tracking installed versions, but it is not required for the core model.
- Skill-authored agents — once skills are composable, an "agent" becomes mostly a baseline prompt + skill list. Could eventually generate agents from skill bundles.
- Cross-agent skill reuse — a skill authored once can attach to any agent that matches its tool needs.

---

## Quick-start for implementation (Phase A)

1. Read `AGENTS.md` — TDD workflow.
2. Open `src/fin_assist/agents/tools.py` — current `ApprovalPolicy` at line 40, scoped CLI factory at line 295, TODO at line 213.
3. Write `tests/test_agents/test_approval_policy_evaluate.py` **first** — pattern matching, first-match-wins, fallback to `mode`, empty rules equivalent to current `ApprovalPolicy`.
4. Implement `ApprovalRule` dataclass and `ApprovalPolicy.evaluate(args)`.
5. Update scoped CLI callable to query policy per call.
6. Update backend adapter (pydantic-ai glue) to use per-call evaluation for deferred-tool decisions.
7. Update git agent's tool registrations with real rules (diff, status, log, show → `never`; push, reset, clean → `always`).
8. Verify: `fin do git commit` no longer prompts on `git diff`.
