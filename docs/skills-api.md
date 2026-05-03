# Skills API — Design Sketch

**Status:** Phase A shipped; Phase B partially implemented (inline TOML skills, `SkillConfig`/`SkillLoader`/`SkillManager`, `WorkflowConfig` removed, `AgentConfig.tools` removed). Design doc retained as reference — some sections describe the full Phase B vision not yet landed. Iterated 2026-04-29 — skills reframed as **capability packs** (tools + docs + scripts + approvals + serving-mode affinity) that hot-load into an agent as a unit; `lookup(skill_id)` replaced by `load_skill` transition + per-skill `extensions/` disclosure; skills gain `fin.serving_modes`; invocation UX collapses to "always skill-scoped, user or agent picks." See §9 for resolved/deferred questions. Git history carries prior iterations.

**Inspiration:** Anthropic's [skills.md](https://code.claude.com/docs/en/skills) pattern (directory of markdown files + frontmatter, progressive disclosure, on-demand body loading). [OpenCode's](https://open-code.ai/en/docs/skills) parallel implementation confirms the pattern is converging across agent tooling.

**Scope:** replaces the "Skills API" section of `handoff.md`. Supersedes (and, on implementation, closes) GitHub issues [#98](https://github.com/ColeB1722/fin-assist/issues/98), [#89](https://github.com/ColeB1722/fin-assist/issues/89), and [#84](https://github.com/ColeB1722/fin-assist/issues/84).

---

## 1. Motivation

Three concrete gaps drive this design:

1. **Scoped CLI tools with blanket approval.** The git agent (#79) introduced `git` and `gh` as prefix-scoped tools. Every subcommand requires approval today — `git diff` is as gated as `git push --force`. The TODO at `src/fin_assist/agents/tools.py:213` is explicit about this being a temporary state.
2. **Prompt steering is agent-scoped and one-off.** `WorkflowConfig` *(type removed — migrated to skills)* (on `AgentConfig`) lets an agent declare named tasks with entry prompts and system-prompt overrides. Useful, but workflows don't travel across agents, aren't discoverable from outside config, and require Python registration of prompt templates.
3. **No path for user- or community-authored capabilities.** Today, adding a task to fin means editing `src/fin_assist/llm/prompts.py` (register template), `src/fin_assist/config/schema.py` or `config.toml` (declare workflow), and shipping Python code. No "drop a markdown file in a directory" path.

The skills.md pattern addresses all three: per-task directories with markdown frontmatter + body, discovered via filesystem walk-up, loaded on demand, invocable as first-class structured actions.

The key reframe in this iteration: a **skill is a capability pack**, not a prompt. When it loads, it replaces the agent's system-prompt content, tool surface, and approval overrides as a unit. Skills span a gradient from narrow/procedural (`pr` — short body, one scoped CLI, tight approvals) to broad/toolbox (`git` — index-style body with on-demand extension lookup, permissive tools, loose approvals) to conversation-shaping (`systems-architect` — body of stance and frames, zero or minimal tools, talk-mode only). One shape, authored differently.

## 2. Concept model

Three concepts, strict containment, no overlap.

### Tool

A callable primitive. Examples: `git` (scoped CLI prefix), `gh`, `read_file`, `run_shell`.

- Has a **base approval policy** (`ApprovalPolicy` with subcommand rules — see Phase A).
- Has a schema (for LLM tool-call surface) and an async callable (for execution).
- Zero framework imports (`agents/` is platform, not transport).
- **Unchanged by Phase A** except for the subcommand-approval extension.
- **Scope narrows in Phase B.** `ToolRegistry` becomes a **built-in tool catalog** — the home for Python-implemented callables (`git`, `read_file`, etc.) that skills reference by name in frontmatter. It stops being the per-agent tool assembler it is today; per-task tool assembly moves to the skill loader. `AgentConfig.tools` *(field removed — tools now derive from skill union)* shrinks (or disappears) in favor of a `baseline_tools` concept on the agent. See §8 Phase B.

### Skill

A **capability pack** — a bundle of tools, prompt content, approval overrides, optional scripts, and optional extension docs that load as a unit. Maps 1:1 to A2A's `AgentSkill` type (already used in `src/fin_assist/hub/factory.py`). Backed by an on-disk `SKILL.md` file (frontmatter + body) plus optional sibling files.

A skill declares:

- **name, description** — `AgentSkill` fields (protocol-native, shared across agent tooling). `name` doubles as the skill identifier; description is short (one sentence, used in the general-mode skill list).
- **fin.tools** — list of tool IDs this skill uses. Resolved against the built-in tool catalog at load time.
- **fin.approval** — per-tool, per-subcommand policy overrides applied **only while this skill is active** (see §6). Loosen-only.
- **fin.serving_modes** — which CLI modes this skill is valid in. Defaults to both. Hard constraint, same semantics as `AgentCardMeta.serving_modes` and the to-be-migrated `WorkflowConfig.serving_modes` *(type removed — migrated to skills)*. See §4.
- **fin.entry_prompt** — first user message seeded when the skill is loaded via pre-commit invocation (§4). Optional for talk-skills.
- **fin.scripts** (optional) — declared scripts from the skill's `scripts/` directory, each becoming a generated `ToolDefinition` at load time.
- **body** — prose that becomes part of the system prompt when the skill loads. May reference sibling extension files; the `load_skill`/extension-lookup tool surface (§5) exposes them on demand.

**Frontmatter shape.** Top-level `name` and `description` match the emerging cross-tool `SKILL.md` convention (Anthropic's skills.md, OpenCode's skills). Fin-specific extensions live under a `fin:` namespace, mirroring the `[tool.ruff]` / `[tool.pytest]` pattern in `pyproject.toml`:

- A fin `SKILL.md` is readable by other tools that adopt the shared format — they see `name` and `description`, ignore the `fin:` block.
- A skill authored for another tool is loadable by fin (with defaults for missing `fin:` fields).
- The `fin:` block is the natural payload for the A2A card extension — frontmatter and wire format line up one-to-one.

Cross-directory discovery (reading `.claude/skills/` or `.opencode/skills/`) remains deferred — see §3.

Example `SKILL.md` frontmatter:

```yaml
---
name: pr
description: Create a PR from current branch — generates a conventional commit, pushes, opens PR with summary.
fin:
  serving_modes: [do]
  tools: [git, gh]
  approval:
    git:
      # Within this skill, `git push` is pre-approved (normally gated)
      - { pattern: "push*", mode: "never" }
  scripts:
    - name: pr-checklist
      path: scripts/pr-checklist.sh
      description: Print the PR review checklist.
      approval: never
  entry_prompt: |
    The user wants to create a pull request. The procedure is in this
    skill's body — follow it step by step. If any tool call fails, stop
    and ask for help.
---

# Creating pull requests

## Step 1 — Understand the change
[...body inlined into the system prompt when the skill loads. For deeper
references (edge cases, alternate flows), see the referenced extension
files — e.g., `extensions/force-push-rules.md` — fetched on demand.
See §5 for load/lookup semantics.]
```

### Agent

An agent declares:

- Base identity (name, description, system_prompt, serving_modes) — unchanged from today.
- **Attached skills** — list of skill IDs the agent exposes.
- **Baseline tools** (optional) — tools always available regardless of which skill (if any) is loaded. Used for minimal ad-hoc capabilities like `read_file` that the agent wants in every context.

An agent runs in one of two configurations per turn:

- **General** — no skill active. Effective toolset is `baseline_tools`. System prompt carries the agent's base system prompt plus a short list of loadable skill descriptions (filtered to skills matching the current serving mode). A `load_skill` tool is available iff the agent has ≥1 attached skill in the current serving mode.
- **Skill-loaded** — active skill S. Effective toolset is `baseline_tools ∪ S.tools ∪ S.scripts_as_tools`. System prompt carries the agent's base system prompt plus S's body. S's approval overrides prepend to base policies for S's declared tools. The skill-list and `load_skill` are **not** in scope; an `extension` lookup tool is registered iff S has an `extensions/` directory.

One skill is loaded at a time per turn. Loading is a **transition** — system prompt content, tool surface, and approval overrides all swap as a unit. The transition is one-shot within a task: once loaded, a skill stays loaded for the remainder of that task. See §4 for persistence across talk-session turns.

### What was "Workflow" — gone

Previous design iterations carried a fourth concept, `Workflow`, for prompt-steered sub-tasks. This is fully absorbed by Skill. A "workflow" was always just "a skill with specific steering, tool attachments, and an entry prompt" — the A2A-native framing makes that explicit and removes a redundant vocabulary tier.

Migration: current `AgentConfig.workflows` dict becomes skill files. Each workflow entry → one `SKILL.md`. The `WorkflowConfig` *(type removed — migrated to skills)* can be deleted after migration.

## 3. Storage and discovery

### Directory layout

```text
.fin/skills/<skill-id>/
  SKILL.md                # required: frontmatter + body
  scripts/                # optional: declared in frontmatter; become ToolDefinitions on load
    pr-checklist.sh
  extensions/             # optional: deeper docs referenced from body; fetched via lookup
    force-push-rules.md
    rebase-semantics.md
```

Single-file skills (no supporting assets) can live as `.fin/skills/<id>/SKILL.md` directly — the directory exists solely to be a home for the bundle if/when it grows.

`scripts/` and `extensions/` serve different purposes:

- **`scripts/`** — executable files that become LLM-callable tools when the skill loads. Each must be declared in frontmatter (`fin.scripts`) with name, description, and approval policy. Discovery is explicit, not auto-enumerate — declarations are reviewable.
- **`extensions/`** — prose documentation the body may reference. Not tools; content fetched via the extension-lookup tool (§5). Jump-table semantics: enumerable by file name within the skill, not free-form retrieval.

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

Today, `hub/factory.py:111-118` publishes one `AgentSkill` per agent card — a placeholder equal to the agent itself. Under this design, `AgentCard.skills` becomes the actual list of **attached** skills:

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

**Tools do not appear on the card.** A2A's `AgentCard` standardizes `skills` but has no `tools` field — the protocol treats tools as implementation detail of skills, not card-level capability. This design honors that: clients discover what an agent can do by reading its skill list; to learn what tools a given skill brings, clients invoke it.

Fin-specific skill metadata (tools list, approval overrides, entry_prompt reference) rides on an extension. The existing `fin_assist:meta` extension at `src/fin_assist/hub/factory.py:104` can grow a `skills` field, or a new `fin_assist:skills` extension can be added — minor call at implementation time.

**Walk-up discovered skills do not appear on the card.** The card lists statically attached skills only. CLI walk-up (§3) finds project-local skills and injects them at task creation time; they are runtime additions, not card-level identity. Cards re-render per request so attached-skill changes (skill file edits, mtime-triggered cache reloads) propagate without a server restart.

### Invocation model — always skill-scoped, user or agent picks

Every turn runs in one of two configurations: **general** (no skill) or **skill-loaded**. These are not "invocation modes"; they are states within a single turn that may transition (via `load_skill`) at most once per task.

**Three entry variants, one underlying state:**

| Entry | Mechanism | Starting state |
|---|---|---|
| **Pre-commit** | `fin do <agent> <skill-id>` (or `fin talk <agent> <skill-id>`) routes to `skills/invoke(skill_id)` RPC | Task starts in skill-loaded; `entry_prompt` seeds first user message if declared |
| **Agent-routed** | `fin do <agent> "<message>"` routes to `message/send`; general-mode system prompt includes skill list; agent may call `load_skill` | Task starts in general; transitions to skill-loaded iff agent chooses |
| **Stay general** | Same as above; agent does not call `load_skill` | Task stays in general throughout |

From the CLI's perspective: `fin do git pr` is a pre-commit shortcut for "I know which skill, don't route." `fin do git "make me a pr"` is agent-routed — slight latency from the routing tool call, some risk of mis-routing, but handles unclear intent. `fin do git "why did this test fail"` likely stays general — no skill matches cleanly, agent uses baseline capability only.

**Hub-side state driver.** The task carries `active_skill_id: str | None`. Initially `None` for message/send, set to the skill id for skills/invoke. Set exactly once via `load_skill`. That single piece of state drives (1) system-prompt composition, (2) tool-surface assembly, (3) approval override resolution (§6), and (4) event tagging for client presentation (see below).

### `skills/invoke` RPC method

A2A supports **Method Extensions** ("Extended Skills" in the spec): custom RPC methods declared via extensions. This design registers `skills/invoke` on agent endpoints for the pre-commit entry.

Shape (final schema TBD during implementation):

```text
Request:
  skill_id: string
  args: { ... }              # optional skill-specific arguments
Response:
  task_id: string            # standard A2A task created; client streams updates
```

On receipt: hub validates the skill_id against attached + walk-up skills, validates the skill's `serving_modes` matches the request's mode, builds the task with `active_skill_id` set from the start, seeds `entry_prompt` as the first user message if declared. Pre-commit tasks start in skill-loaded state, so by the §5 gating rule `load_skill` is never registered for them — the transition already happened at task creation.

### Persistence across a `talk` session

A2A tasks are turn-scoped; `fin talk` conversations are session-scoped. Skill persistence rules:

- **Talk-skill loaded in a talk session:** persists across turns. Loading `systems-architect` at turn 1 keeps it active at turns 2, 3, ... The skill is the conversation's shape, not a single turn's action.
- **Do-skill loaded in a talk session:** scoped to one task. Loading `pr` mid-conversation performs the action (with its own approval flow), task ends, conversation returns to the prior context (talk-skill or general).
- **Switching skills mid-session:** user-driven only. A CLI command (e.g., `/skill security-reviewer`) or re-running `fin talk <agent> <skill>`. Agent-initiated switches are not permitted — the one-shot-transition invariant applies per task, and at the session level the user owns the conversation's shape.
- **Session resume (`fin talk --resume <id>`):** persisted skill state is restored. If the session ended while `systems-architect` was loaded, resume loads `systems-architect` again.

### Nested-context rendering — UX note (parked)

Running a do-skill inside a talk session creates a nested-context UX problem: how does a client distinguish the do-skill sub-task from the surrounding talk conversation? Server-side requirements fall out cleanly:

- **Skill-transition events** on `StepEvent`: `skill_loaded(skill_id)`, `skill_completed(skill_id, outcome)`.
- **`active_skill_id` on artifact metadata** so renderers can group or frame artifacts by their originating skill.
- **Distinct tagging** of do-skill artifacts (`metadata.origin = "skill:<id>"`) so clients can filter or collapse them.

Client-side presentation (inline-marked, detached panel, summary collapse) is a Phase B CLI decision that will probably get revisited when the TUI lands. The hub ships the signal; clients decide the shape. Also aligns with the Phoenix span-attribute-per-skill work in Phase C.

### Invocation paths summary

| Path | When used |
|---|---|
| Pre-commit | `fin do <agent> <skill-id>` — user knows which skill, no routing |
| Agent-routed | `fin do <agent> "<message>"` — agent may call `load_skill` based on message |
| Stay general | `fin do <agent> "<message>"` — agent stays general, uses baseline only |
| `@`-completion | `@file:foo.py`, `@git:diff` — orthogonal, CLI-only context splicing |

`@`-completion is orthogonal to skills. It is a CLI ergonomic for splicing context into prompts before send, owned entirely by `cli/context/` (see §7). No A2A involvement, no hub roundtrip, no overlap with skill invocation.

## 5. Skill loading and extension lookup

Two behaviors, both backed by the skill filesystem layout, both available only in the state where they make sense. The exact tool shape (one tool with optional arg vs. two distinct tools, exact parameter names) is an implementation detail resolved in Phase B. The behavioral contract:

### Behavior 1: load a skill (general-state only)

**Purpose:** transition the task from general into skill-loaded state.

- **Argument:** `skill_id` — enumerable against the agent's attached + walk-up-discovered skills, filtered by current serving mode.
- **Effect:** atomically swaps system-prompt content (base prompt + skill body), tool surface (baseline + skill tools + skill scripts-as-tools), and approval overrides (skill's prepend to base). Registers the extension-lookup tool iff the skill has an `extensions/` directory. Unregisters itself (no double-loads; one transition per task).
- **Scope:** available only when `active_skill_id` is `None`. After one successful call, no longer in scope.
- **Failure mode:** unknown id, wrong serving mode, or skill failed to load — tool returns a clear error string; model recovers via normal tool-error handling; no state change.

### Behavior 2: fetch an extension (skill-loaded state only)

**Purpose:** on-demand retrieval of referenced docs within the active skill.

- **Argument:** `name` — matches a file in the active skill's `extensions/` directory (jump table, not free-form search).
- **Effect:** returns the file contents as a string. Read-only. No state change.
- **Scope:** registered only when the active skill has an `extensions/` directory. Hermetic per skill — no cross-skill access, no access to extensions from any skill other than the active one.
- **Failure mode:** unknown name — tool returns error string; model recovers.

### Rationale for the state-gated availability

1. **No wasted roundtrip.** A pre-committed or already-loaded skill doesn't need the model to route — routing machinery is absent from skill-loaded state.
2. **Pollution containment.** Skill bodies may contain literal tool calls (`git push --force-with-lease`). With behaviors gated to their valid state, each skill's body and approval overrides are scoped to its own active window. The two gates are duals of the same `active_skill_id` state that drives §6 approval resolution.
3. **Bounded prompt budget.** General state pays N × short-descriptions (cheap). Skill-loaded state pays 1 × body + extension index (targeted). Neither state pays both.
4. **Discoverable surface per state.** The tool list the model sees is exactly what's callable in the current state. No "sometimes available, sometimes not" tools to reason about in natural language.

### Jump table, not retrieval

Both behaviors are **jump-table lookups against enumerable keys**:

- `load_skill(id)` — id is enumerable against the current skill list; the list is in the system prompt.
- `extension(name)` — name is enumerable against files in the active skill's `extensions/` directory; names appear in the body where they're referenced.

Neither behavior is free-form retrieval. A tempting extension — "let the model search a docs corpus by topic" — is explicitly rejected:

| | Jump-table lookup (shipped) | Topic retrieval (not shipped) |
|---|---|---|
| Semantics | Enumerable keys, dict resolution | Query → ranked passages |
| Failure mode | Clean: key not found → error, model recovers | Fuzzy: zero/wrong/ok matches, tokens burned on rephrase |
| Prompt-budget cost | Bounded (N ids, M extension names) | Unbounded or gambling on discoverability |
| Implementation | ~dict wrap | Vector store or FTS, embedding model, chunking |
| Eval story | Did the key resolve? Trivial. | Precision/recall — its own eval harness |

If RAG-over-local-docs is ever valuable, it gets a different tool with different return semantics (ranked passages, not whole bodies). Conflating forces weasel-worded descriptions and trains the model on fuzzy resolution where precise would do.

### What Phase B explicitly doesn't do

- **No free-form topic retrieval** in either behavior.
- **No cross-skill extension access.** `extension(name)` reads only the active skill's `extensions/`.
- **No skill composition.** A skill's body cannot load another skill mid-execution; `load_skill` is unregistered once a skill is active. If composition emerges as a real need, the resolution is a `compose: [other-skill]` frontmatter field that re-enables scoped loading for explicitly declared ids. Parked as an open question — the cross-skill non-inheritance rules (tools, approvals, bodies all hermetic) make the feature do so little it hasn't justified the surface area.
- **No caching of results.** Hub already caches parsed `SKILL.md` and extension files; tool-call overhead is negligible.

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

A skill can declare per-tool approval overrides that apply **while that skill is loaded**:

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
- When skill `S` is loaded and declares overrides for tool `X`, those overrides are **prepended** to `X`'s rule list for the duration of `S`'s load.
- Rule resolution remains first-match-wins. Override rules match first; fall through to base policy.
- In general state (no skill loaded), only base policies apply.

**Why skill-scoped rather than agent-scoped merge:**

Merging all skills' overrides into a single agent-wide policy would mean the `pr` skill's loosened `git push` rule applies even while `commit` is loaded. That breaks scope discipline. Per-skill context keeps each skill's safety model local to the window in which that skill is active.

**Implementation plumbing:**

The executor needs to know "which skill's context is this tool call inside." The cleanest way: the task carries `active_skill_id` (set by `skills/invoke` at task creation or by `load_skill` mid-task); executor reads it when evaluating a tool call; `ToolDefinition.approval` lookup becomes `approval.for_skill(active_skill_id)` instead of a bare attribute read.

**One state, four effects.** `active_skill_id` drives (1) approval override resolution (this section), (2) system-prompt composition (§2, §4), (3) tool-surface assembly including the state-gated load/extension behaviors (§5), and (4) event tagging for client-side nested-context rendering (§4). All four collapse onto the same piece of state.

### Direction of overrides: loosen-only

Phase B ships **loosen-only** overrides. A skill can take a gated operation and ungate it within its scope (`always → never`); it cannot take an ungated operation and gate it (`never → always`).

**Enforcement is config-time, not runtime.** At skill-load time the loader compares each override against the tool's base policy. A tightening override fails the load with a clear error:

```text
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

### Phase B — Skills as capability packs

**Goal:** users can author skills as on-disk bundles, pre-commit via `fin do <agent> <skill>`, let the agent route via `load_skill`, and author both do- and talk-style skills.

**Scope:**

- `src/fin_assist/skills/` package (currently an empty placeholder at `architecture.md:291`):
  - `definition.py` — `SkillDefinition`, frontmatter schema (including `serving_modes`, `scripts`, approval overrides)
  - `loader.py` — parses `SKILL.md` (frontmatter + body), materializes declared scripts as `ToolDefinition`s, indexes `extensions/`
  - `discovery.py` — walk-up + user-global search logic (**CLI-side**)
  - `registry.py` — hub-side cache keyed by absolute path, mtime-invalidated
- `config/schema.py` changes:
  - Remove `AgentConfig.workflows` (migrated to skill files).
  - Add `AgentConfig.skills: list[str]` — skill ids attached to the agent.
  - Rename/narrow `AgentConfig.tools` *(field removed — tools now derive from skill union)* → `AgentConfig.baseline_tools` (always-on tools outside any skill).
- `agents/tools.py`: `ToolRegistry` scope narrows to built-in tool catalog. `get_for_agent()` removed; skills resolve tool names via `registry.get()` at load time. `ApprovalPolicy.for_skill(skill_id)` lookup; overrides merge.
- `hub/factory.py`: `AgentCard.skills` lists attached skills (walk-up skills are runtime-only); per-request card re-render so cache reloads propagate; fin-specific metadata via card extension.
- `hub/app.py`: register `skills/invoke` RPC method (A2A extension) for pre-commit entry. Implementation sets `active_skill_id` at task creation, seeds `entry_prompt` as first user message when declared.
- Executor: propagate `active_skill_id` through `StepEvent` for approval checks and client-side presentation. Emit `skill_loaded` / `skill_completed` events. Tag artifacts with `metadata.origin = "skill:<id>"` when produced under a loaded skill.
- `load_skill` and extension-lookup tools: state-gated per §5. Agents with zero attached skills never see `load_skill`.
- CLI:
  - `fin do <agent> <skill-id>` routes to `skills/invoke`.
  - `fin do <agent> "<message>"` routes to `message/send`; agent sees filtered skill list and may `load_skill`.
  - Walk-up discovery at command time; paths passed to hub on connect.
  - `fin talk` preserves skill state across turns per §4 persistence rules.
  - `fin list skills` reads agent cards, shows attached skills across all agents grouped by agent.
  - `fin validate skills` — diagnoses load errors across discovered skill locations with file+reason output.
- Skill loader fail-soft: invalid skills are skipped with a prominent boot-time summary; invalid references (missing tool, missing script) fail the skill's load, not the hub's.
- In-flight task pinning: once a skill is loaded into a task, subsequent edits to `SKILL.md` don't affect that task. Next task sees the new version via mtime-triggered reload.

**Migration of existing workflows:**

The git agent's three workflows (commit, pr, summarize) from `config.toml` become three `SKILL.md` files under `.fin/skills/`. `WorkflowConfig` *(type removed — migrated to skills)* type deleted.

**Exit gate:** at least three real skills authored:

- One do-skill migrated from existing workflows (`pr` or `commit`), invocable via `fin do git pr` and via agent-routed `load_skill`, with subcommand approvals working per skill context.
- One broad toolbox skill (`git`) with ≥1 extension file fetched via the extension-lookup tool during a turn.
- One talk-skill (candidate: `reviewer` or `systems-architect`) persisting across turns in a `fin talk` session.

**Estimate:** ~6 new source files, ~6 modified, ~6 new test files, ~650 LOC + tests + config migration.

**Does not ship:** MCP as a skill source, free-form topic retrieval, cross-directory discovery (`.claude/skills/` / `.opencode/skills/`), skill composition (`compose:` frontmatter), approval tightening, agent-initiated mid-session skill switching.

### Phase C — MCP, observability, stretch

**Goal:** skills from external sources (MCP), trace-backed visibility, optional extensions within the jump-table scope.

**Scope (speculative; exact contents depend on what Phase B surfaces):**

- **MCP as a skill source.** An MCP server's tools map to a skill bundle; `SKILL.md` can be synthesized or authored alongside. Closes current issue #84.
- **Phoenix/OTel integration** with `skill.id` as a span attribute, driven by the tracing work that should land *before* Phase C per the handoff roadmap.
- **Extension-lookup refinements** — e.g., per-skill `compose: [...]` for scoped cross-skill loading — **only** if Phase B usage shows real pain.
- **Tool-type taxonomy** may re-enter here as a natural consequence of MCP-sourced skills needing type-aware instrumentation.

**Blocks on:** Phase B shipped; Phoenix tracing shipped; a concrete MCP consumer identified (likely `mcp-server-git` or a filesystem server).

**Exit gate:** at least one MCP-sourced skill works end-to-end; trace in Phoenix shows `skill.id` attribute on spans; ability to filter traces by skill.

## 9. Open questions parked for implementation

These are explicitly not blocking the start of Phase A. They will be resolved during Phase B implementation when the concrete choices have more signal:

1. **Skill-id namespace.** Flat (`pr`) or namespaced (`git.pr`)? Flat is simpler; namespaces might help at scale. Lean flat until collision pain appears.
2. **Skill path transmission over A2A.** How exactly does the CLI send discovered paths to the hub on connection — extension on `message/send`, dedicated setup RPC, headers on the streaming channel? Practical choice.
3. **Hub-side cache eviction.** How long do parsed `SKILL.md` stay in memory after the last referencing connection closes? LRU vs. eager eviction.
4. **Extension choice.** Fold skill metadata into existing `fin_assist:meta` extension or add `fin_assist:skills` as a separate extension? Separation is cleaner if the meta extension grows much more; merge if it stays small.
5. **Tool-surface shape for load/extension behaviors.** §5 defines two behavioral contracts gated to different states. Whether they're one tool with an optional arg (e.g., `lookup(skill_id=..., ext=...)`) or two distinct tools (`load_skill(skill_id)`, `extension(name)`) is a naming/ergonomics call. Two tools is probably cleaner (honest doc strings, no mode-switching arg), but exact call at implementation.
6. **Body injection slot.** Does the skill body go into the system prompt, a dedicated slot, or a leading user message? Probably system prompt (it's steering, not user content), but pydantic-ai treats these differently and the right answer may depend on model-specific behavior.
7. **`entry_prompt` firing on agent self-load.** Does the skill's `entry_prompt` fire when the agent self-loads via `load_skill`, or only when the user pre-commits? Argument for "only pre-commit": avoids injecting a fake user message after the agent already chose. Argument for "both": consistent seeding. Decide during Phase B.
8. **`fin list skills` grouping.** Per-agent grouping, flat alphabetical with agent annotations, or user-selectable via flag. CLI ergonomics, easy to iterate on.
9. **Cross-directory discovery.** Opt-in reading of `.claude/skills/` and `.opencode/skills/` via `[skills] discovery_paths = [...]` config (see §3). Loader is structurally ready; ship when there's demand. Format compatibility is already in place via the `fin:` namespace convention.

**Resolved in design discussions:**

- **Cross-tool format compat** (2026-04-28): adopted. Top-level `name`/`description`, fin extensions under `fin:` namespace. See §2.
- **Free-form topic retrieval** (2026-04-28): rejected as a different product. Jump-table semantics for both load and extension behaviors. See §5.
- **Approval direction** (2026-04-28): loosen-only in Phase B, enforced at config-load time. Future escape hatch is a per-skill `approval_allow_tighten: true` opt-in. See §6.
- **Skills as capability packs, not prompts** (2026-04-29): skill loading replaces system-prompt content, tool surface, and approval overrides as a unit. One-shot transition per task via pre-commit or `load_skill`. See §2, §4, §5.
- **`serving_modes` on skills** (2026-04-29): skills carry hard-constraint `fin.serving_modes` matching agent/workflow semantics. Drives skill-list filtering in general mode and persistence scope across turns. See §2, §4.
- **Agent card truthfulness** (2026-04-29): `AgentCard.skills` lists statically attached skills only; tools never appear on the card (A2A has no such field); walk-up-discovered skills are runtime-only. See §4.
- **Skill list injection in general mode** (2026-04-29): inject iff agent has ≥1 attached skill in the current serving mode. See §2, §4.
- **Multi-turn persistence scope** (2026-04-29): persistence = skill's own `serving_modes`. Talk-skills persist across session; do-skills are task-scoped; switching is user-driven only; session resume restores loaded skill. See §4.
- **Skill unavailability** (2026-04-29): load-time errors fail-soft with prominent boot summary + `fin validate skills` CLI; runtime errors surface as tool output; in-flight tasks pin to loaded version; cards re-render per request. See §4, §8.
- **Skill composition** (2026-04-29): not in Phase B. Cross-skill loading forbidden during active skill; if demand emerges, `compose: [...]` frontmatter field re-enables scoped loading. See §5.
- **`ToolRegistry` scope** (2026-04-29): narrows from per-agent assembler to built-in tool catalog; skills resolve tool names via `registry.get()` at load time. See §2, §8.

## 10. Relation to the wider codebase

**Current state of the repo:**

- Scoped CLI tools: `src/fin_assist/agents/tools.py`
- `ApprovalPolicy`: `src/fin_assist/agents/tools.py`
- `AgentConfig.tools` *(field removed — tools now derive from skill union)* and `AgentConfig.workflows`: `src/fin_assist/config/schema.py`
- Agent card publishing with one-skill placeholder: `src/fin_assist/hub/factory.py`
- `fin_assist:meta` extension: `src/fin_assist/hub/factory.py`
- Empty `skills/` placeholder: referenced at `architecture.md` (not yet created in source tree)
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
