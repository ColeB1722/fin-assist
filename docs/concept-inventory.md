# Concept Inventory

The set of first-class concepts the hub maintains, and the rule for what counts as one. This document is the canonical destination-state reference for hub architecture; `handoff.md` carries the in-flight migration sketch.

## The rule

**The hub maintains a concept only when no protocol carries it.** Anything a pressure-tested protocol (A2A, MCP, ACP) already defines as a first-class entity is offloaded to that protocol. The hub's job is to host agents and orchestrate them — not to re-invent abstractions that exist in the surrounding ecosystem.

Two consequences fall out:

1. **Tools come from MCP servers.** The hub maintains an MCP server registry, not a tool registry. Tools are an MCP concept; the hub's only job is to know which MCP servers exist and which agents have access to them.
2. **Inbound context comes from clients via ACP.** Editors push selection, file, diagnostic context through the ACP session protocol. The hub does not pull context through a rolled-our-own provider registry.

What remains genuinely hub-shaped:

- **Agents** — the addressable unit a client talks to. Defined in TOML, hosted by the hub.
- **Skills** — the unit of capability composition inside an agent. Project SKILL.md, user SKILL.md, and inline TOML all flow into one unified skill registry.
- **MCP servers** — infrastructure the hub knows about; agents opt in per-agent.
- **Models** — selected by name from the framework's known-model set; per-agent config.
- **Approval policies** — pure behavior; per-agent.

That's the inventory. Five concepts. Everything else is a protocol concern or a skill-local concern.

## Authoring patterns

### Infrastructure is global, behavior is per-agent

The pattern from tools (the cleanest pre-alignment example) generalizes: **infrastructure is registered globally** (MCP servers, skills); **behavior is per-agent** (which skills are bound, which MCP servers are accessible, which approval policies apply, what the system prompt says).

`config.toml` is purely orchestration. It does not define infrastructure inline (with one ergonomic shorthand — see below). It binds existing infrastructure to agents and shapes the agent's behavior.

### Two authoring conveniences for skills

To keep ergonomics good without sacrificing the "global registry" mental model, skills can be authored two ways:

1. **Top-level `[skills.<name>]`** — registers globally. Agents bind explicitly: `[agents.git] skills = ["commit"]`. Best for skills shared across multiple agents.
2. **Inline `[agents.<agent>.skills.<name>]`** — registers globally *and* auto-binds to that agent. Best for one-off, agent-specific skills.

Same registry, two authoring shapes. The mental model stays clean (everything is in a registry); the ergonomics stay good (one-offs don't require two TOML blocks).

### SKILL.md files

Skills can also be authored as Markdown files following the [agentskills.io](https://agentskills.io) open standard:

- **Project skills**: `.fin/skills/<name>/SKILL.md`
- **User skills**: `~/.config/fin/skills/<name>/SKILL.md`

These are discovered at startup and merged into the same global skill registry alongside TOML-defined skills.

**Precedence (highest to lowest):**

1. Project SKILL.md (`.fin/skills/<name>/SKILL.md`)
2. User SKILL.md (`~/.config/fin/skills/<name>/SKILL.md`)
3. Top-level TOML (`[skills.<name>]`)
4. Inline TOML (`[agents.<agent>.skills.<name>]`)

**Agent binding for SKILL.md skills:** declared in frontmatter via `agents: [git, shell]`. The skill ships self-contained — drop the file in, declare which agents can load it, done. No separate config edit required to make a SKILL.md skill discoverable to an agent.

### Skill-bound tools

Skills can declare their own tools alongside their prose. These are not registered globally — they live with the skill and are only loadable when the skill is loaded.

**Shape:** a Python module at `.fin/skills/<name>/tools.py` (or `~/.config/fin/skills/<name>/tools.py`) with `@tool`-decorated functions. The decorator carries description, approval policy, and (optionally) a name override.

```python
# .fin/skills/commit/tools.py
from fin_assist.skills import tool, ApprovalPolicy

@tool(
    description="Stage all changes in the current repository.",
    approval=ApprovalPolicy(default="always"),
)
def stage_all() -> str:
    """Run git add -A."""
    ...
```

**Why skill-bound, not global:**

- Tools are skill-specific by nature — `commit_message` only makes sense when the commit skill is loaded.
- Sub-agents (v0.2) inherit a skill's tools when they load that skill, no extra wiring.
- Skill-packages (`.fin/skills/<name>/`) become the unit of redistribution — drop a directory in, get the skill + its tools as one bundle.

**Why Python decorator, not shell script:** Python composes with type hints, docstring schemas, and the test harness. Shell-script tools (the agentskills.io `allowed-tools: ["!git status"]` pattern) are deferred — Python covers the cases we care about, and shipping both forms doubles the surface area without a clear win.

### MCP servers are per-agent opt-in

MCP servers are global infrastructure — they're defined in `[mcp.servers.<name>]` and live as processes managed by the hub. But agents must explicitly opt in:

```toml
[agents.git]
mcp_servers = ["github", "filesystem"]
```

This matches the tools/skills binding pattern: global definition, per-agent binding. No more "every agent gets every MCP server" implicit-availability.

### System prompts: deferred to #89

System prompts today are resolved through a name-based Python registry (`SYSTEM_PROMPTS` in `src/fin_assist/agents/registry.py`). `AgentConfig.system_prompt = "chain-of-thought"` references the registry; arbitrary string content is also accepted as a fallback. This is half-aligned with the destination state — it *is* a registry, but it's hardcoded and not extensible from config.

Issue [#89](https://github.com/ColeB1722/fin-assist/issues/89) asks whether prompts should be loadable from markdown files (parallel to SKILL.md). The concept-inventory alignment **does not touch prompts** — that question lives with #89.

When #89 picks up, two shapes to consider (sketched in `handoff.md`):

- **Option 1: Two-shape pattern, mirroring skills.** Inline `system_prompt = "..."` (string content) OR `system_prompt = "@prompt-name"` (name reference) resolves through: `[prompts.<name>]` TOML → `.fin/prompts/<name>.md` → `~/.config/fin/prompts/<name>.md` → hardcoded Python registry as fallback. Same precedence rule as skills. No breaking changes.
- **Option 2: Delete the Python registry, require config.** All current `SHELL_INSTRUCTIONS` / `CHAIN_OF_THOUGHT_INSTRUCTIONS` / `TEST_INSTRUCTIONS` move to shipped-default markdown files in the repo (loaded via the same lookup). Aggressive; breaks current configs that reference Python registry names.

Default lean: option 1. The decision lives with #89.

## What this displaces

The reframe deletes several concepts that exist in the codebase today. Listed here so the migration cost is honest:

| Removed concept | Replacement | Cost |
|---|---|---|
| `ToolRegistry` aggregating builtin + MCP + file tools | `MCPServerRegistry` (MCP only) + skill-bound `@tool` discovery | Delete `create_default_registry()`, migrate any built-in tools worth keeping into skills, rename registry to reflect MCP-only purpose |
| Built-in tools (`read_file`, `git`, `gh`, `shell_history`, `run_shell`) | Skill-bound `@tool`-decorated functions in appropriate skills | All five rehome (conservative path resolved during execution). Nothing deleted in this iteration; future iterations may delete `run_shell` once skill-bound pattern is settled |
| `ContextProvider` / `ContextProviderRegistry` (shipped PR #152) | ACP for inbound editor context; thin CLI-local helpers for `@-completion` | Delete the abstraction. `@-completion` becomes CLI-local prompt-composition helpers; `FileFinder`'s gitignore + fuzzy-match logic extracted into a CLI utility module to preserve the existing perf work. `ContextItem` dropped — helpers return plain strings |
| `AgentSpec.base_tools` listing built-in tool names | `AgentSpec.mcp_servers` listing MCP server names; skill-bound tools are loaded with the skill | Rename + retype the field; `tool_policies` still applies, indexed by `mcp.<server>.<tool>` or skill-bound tool name |
| Inline TOML skills as the *only* registration shape | Inline TOML *and* top-level TOML *and* SKILL.md files, all merged into one registry | Additive — existing configs still work; new shapes available |

## Non-goals

- **No prompt registry.** Until reuse pressure exists.
- **No "tools" as a hub abstraction.** Tools live in MCP servers (external) or in skills (skill-bound). The hub does not maintain a tool-shaped concept apart from those two locations.
- **No rolled-our-own context-injection layer.** ACP and MCP cover the surface.
- **No multi-flavor skill-bound tooling.** Python `@tool` decorator only. Shell scripts and binaries are not a supported shape in this iteration.

## Resolved execution decisions

Resolved during the eighth-session conversation (2026-05-18). Migration order and milestone shape live in `handoff.md`; the destination-state implications are summarized here.

1. **Built-in tool fate.** All five current built-ins (`read_file`, `git`, `gh`, `shell_history`, `run_shell`) rehome as skill-bound `@tool`-decorated functions in appropriate skills. Nothing is deleted outright in this iteration — the conservative path is taken to preserve test coverage and avoid simultaneously breaking working behavior and changing concepts. Future iterations may delete some (`run_shell` is the most likely candidate) once the skill-bound pattern is settled.

2. **`@-completion` backing.** The CLI gets thin, fresh helpers per `@-prefix`, with the gitignore + fuzzy-match + caching logic from today's `FileFinder` extracted into a CLI-local utility module (e.g. `cli/file_scan.py`) so the existing performance work isn't lost in the rewrite. The four current provider classes (`FileFinder`, `GitContext`, `ShellHistory`, `Environment`) are not preserved — their boilerplate-heavy shape carries the `ContextProvider` mental model we're rejecting. `ContextItem` is also dropped; CLI helpers return plain strings (or raise) and display errors inline.

3. **Migration order.** Context-deletion ships first (it's the ACP-unblock and mechanically isolated). Then the big step: unified skill registry + skill-bound `@tool` + built-in rehoming as one PR (these are coupled). Finally MCP per-agent opt-in as a small tail. See `handoff.md` for code-level touchpoints and milestone scope.

4. **MCP server scope.** Hub starts MCP servers lazily based on the union of agents' `mcp_servers` opt-in lists. Globally-defined in `[mcp.servers.<name>]` (same as today); per-agent bound via `AgentConfig.mcp_servers = [...]`. Same pattern as skills: global infrastructure, per-agent binding. The CLI itself does not consume MCP servers — it only forwards config to the hub at startup (which is the current behavior; no change).

5. **System prompt scope.** Deferred. The current Python registry (`SYSTEM_PROMPTS` in `agents/registry.py`) is half-aligned with the destination state — it's a registry, but hardcoded. Issue [#89](https://github.com/ColeB1722/fin-assist/issues/89) discusses making prompts file-loadable. The alignment work does not touch prompts; #89 picks this up separately. Two candidate shapes are sketched in `handoff.md` for when that issue graduates. Default lean: option 1 (TOML + `.md` files, mirroring the skills pattern), but the decision lives with #89.

## Relationship to existing docs

- `docs/architecture.md` — hub topology, protocol surfaces, deliverables. This file *refines* its "agents are the unit; protocols carry the rest" stance by enumerating the concept inventory.
- `docs/skills.md` — skill internals (loader, manager, runtime). Will be updated when the unified skill registry lands; until then it documents the inline-TOML-only world.
- `docs/decisions.md` — design-decision log. Specific decisions made under this alignment land there as rows.
- `handoff.md` — in-flight migration sketch with current code state, audit findings, and proposed migration order.
