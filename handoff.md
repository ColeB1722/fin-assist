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

**2026-05-18 (eighth session — concept-inventory alignment surfaced as blocking for ACP):** The execution plan from the seventh session's resolution (Path C, dependency-driven interleaving starting with #125+#123) was paused mid-execution to dig into a broader architectural question raised during the design conversation for #125's agent-binding decision.

The conversation generalized from "how do SKILL.md skills bind to agents?" to "what is the hub's concept inventory and what authoring patterns govern it?" Audit of current state revealed organic-growth misalignment: tools and models follow "infrastructure global, behavior per-agent," but skills, system prompts, MCP servers, and context providers don't — each grew its own pattern independently.

**Destination state (resolved this session):**

- Tool registry → **MCP server registry only**. Built-in tools deleted; skill-specific tools live as skill-bound `@tool`-decorated Python modules.
- Context providers → **deleted**. ACP carries inbound editor context; MCP carries data-shaped context (resources). The `ContextProvider` abstraction shipped in PR #152 is reverted as part of this alignment.
- Skills → **unified registry** merging project SKILL.md > user SKILL.md > top-level TOML > inline TOML. SKILL.md frontmatter declares `agents: [...]` binding.
- MCP servers → **per-agent opt-in** (`mcp_servers = [...]` in `AgentConfig`), not global-implicit.
- System prompts → **scope is open**. Default lean is inline; explicitly flagged for revisit per the eighth-session conversation. See open question 5 in `docs/concept-inventory.md`.
- `config.toml` → **pure orchestration**; binding-only with the inline-shorthand convenience for skills.

Canonical destination-state reference: `docs/concept-inventory.md` (new this session). Migration sketch lives below in Design Sketches.

**Why this is blocking for ACP-server (#162):** the original v0.1.3 plan was to ship ACP on top of the current concept inventory. Concrete risk: ACP-server has to bridge between *"ACP context"* (carried inbound by the protocol) and *fin's* `ContextProvider` registry — gluing two abstractions instead of one. Deleting `ContextProvider` first turns ACP-server into "unpack ACP context into the agent's prompt envelope," which is the intended shape. Same logic applies to `ToolRegistry` aggregation: ACP-server wants to forward MCP tools cleanly, and the existing `ToolProvider` aggregation layer adds a translation seam that disappears once the registry is MCP-only.

**Cost to name honestly:**

- PR #152 shipped `ContextProviderRegistry` (Phase A of the now-rejected ToolProvider/ContextProvider sketch). That code gets deleted as part of this alignment. Roughly: `src/fin_assist/context/base.py` registry shape, `create_default_context_registry()`, all `ContextProvider` subclasses' registration glue, and the wiring through `cli/main.py` and `hub/factory.py`. The provider classes themselves (`FileFinder`, `GitContext`, `ShellHistory`, `Environment`) may survive as MCP-server-backed equivalents or as CLI-local conveniences — TBD during execution per open question 2 in `docs/concept-inventory.md`.
- The "ToolProvider + ContextProvider Protocols" sketch below is now **superseded**. Retained in this file with a header marker so the old context isn't lost mid-conversation; deletes when the alignment ships.

**Milestone shape (resolved end of eighth session):** new `v0.1.2 — Concept inventory alignment` milestone with three step-issues (one per migration step). Existing v0.1.2/v0.1.3 renumber to v0.1.3/v0.1.4. #125 migrates from v0.1.1 into the new v0.1.2 (folded into Step 2). #85 stays in v0.1.1 but rescopes (now about CLI `@git:` helper size limits, not `GitContext` provider). #123 stays in v0.1.1 (orthogonal to alignment). See Concept Inventory Migration sketch in Design Sketches for full milestone table + GitHub mutations checklist.

**All five open questions resolved end of session.** Concrete decisions:

1. **Built-in tool fate:** all 5 rehome as skill-bound `@tool`s (conservative path; nothing deleted).
2. **`@-completion` backing:** thin CLI helpers fresh; `FileFinder`'s scan logic extracted to a CLI utility module.
3. **Migration ordering:** context-deletion first → skills+tools as one big PR → MCP scoping tail.
4. **MCP server scope:** lazy startup based on union of agent opt-ins.
5. **System prompts:** deferred to #89 with two-option sketch in handoff.md.

---

**2026-05-17 (seventh session — doc migration complete + transport-precision fix):** Durable claims from `docs/platform-stance.md` migrated to the forever-docs. The platform-stance work is fully retired; the next session resumes dev work.

- **→ `docs/architecture.md`** — *Deliverables: Hub vs Client* renamed to *Deliverables: Hub vs CLI* and rewritten ("hub as the deliverable; CLI is a dev tool"). New *Inbound protocol surfaces* subsection names A2A-server (existing), MCP-server (committed, unmilestoned), ACP-server (v0.1.3, see [#162](https://github.com/ColeB1722/fin-assist/issues/162)) plus the outbound surfaces. Vision intro replaced "CLI-first, TUI-later" with "Hub as the deliverable; clients are protocol peers." Design principle #5 rewritten. Non-goal added ("CLI that grows into an end-user conversational client"). CLI entry-points section gained a forward-pointing note that the verification-only contraction is in-flight via v0.1.3 + v0.2.1.
  - **Transport-precision fix (review follow-up):** the CLI row originally implied A2A was the transport for *all* CLI ↔ hub traffic. Tightened to distinguish (a) plain HTTP via `httpx` for hub-level routes (`/health`, `/agents`, per-agent `/skills` and `/skills/invoke`), (b) A2A only for agent-traffic messaging in the dev REPL, (c) `/connect` + `fin pkg` as local file I/O that never touch the hub. The supporting *protocol is the contract* paragraph was rewritten to match. `decisions.md` Q3 row received the same precision pass. Verified against `cli/server.py` (process-lifecycle via `httpx`), `cli/client.py` (mixed `httpx` + a2a-sdk: GET `/agents`, GET/POST `/agents/{name}/skills*` are plain HTTP; only `send_message`/`stream_agent` are A2A).
  - **Firewall rationale rewrite (commit 10, review follow-up):** the import-linter contracts kept their mechanism but their stated rationale was stale (it framed the firewall as a workspace-split forcing function from the pre-stance "two deliverables" world). Rewrote in three places: architecture principle #7 now leads with "the firewall is what makes the protocol-peer architecture testable rather than aspirational; the CLI is held to the same contract as Zed-via-ACP / Claude-Desktop-via-MCP"; §*Why this matters now* swapped the workspace-split framing for the "if we removed the CLI tomorrow, would external clients see the same hub API?" framing plus a Q5 / #162-verification justification; `pyproject.toml` header comment + launcher-allowlist inline comment + `justfile` `lint-imports` description all received matching rewrites. Mechanism unchanged — the two `forbidden` contracts and the 5-entry launcher allowlist are exactly as they were.
- **→ `docs/decisions.md`** — stale `CLI-first development` row updated to `CLI as dev tool, not product`. New `## Platform stance` section with: a header explaining the stance origin + the core verbatim quote; a table covering Q1 (integration direction), Q2 (protocol surfaces), Q3 (CLI as dev tool), Q4 (workspace split), Q5 (ACP-server first), Q7 (verification-only); a long-form `### Verification-only dev REPL — the feature line` subsection with "what stays" + "what's explicitly out" tables that name the closed/deferred issues by number (the calibration list per Q7's drift-prevention contract).
- **→ `docs/platform-stance.md`** — compressed from 572 lines to a 13-line historical pointer. Names the migration targets, explains why it's a stub instead of a deletion (~13 issue comments still link to it), and points at `git log -p -- docs/platform-stance.md` for the full archaeology.

The decision frame's working notes (§6 dated session logs for all five decision sessions + the recorded thinking on #128 / #132 / #146) are preserved in git history only.

**2026-05-17 (sixth session — issue-hygiene pass complete):** All Q6 + Q7 enumerated GitHub mutations executed (~22 mutations + 3 milestone description rewrites + 1 new issue). State of the world after the pass:

- **Closed:** #133 (Telegram), #134 (iOS), #132 (ACP/BFF), #67 (splash), #91 (rich tool_result), #94 (`fin do`/`prompt`), #95 (`/spec`), #97 (`--edit`). Eight issues retired as moot under Q3 + Q7.
- **Commented (durable thinking, unmilestoned):** #128 (workspace split deferred indefinitely), #146 (`fin pkg` direction confirmed unchanged).
- **Re-scoped:** #137 — radically narrowed to positional grammar + `entry_prompt` two-turn fix; original full grammar v2 design preserved in issue body under "Historical scope" header for archaeology.
- **Migrated:** #154 v0.1.3 → v0.2; #153 v0.1.2 → unmilestoned (joins #139 + #151 as natural MCP-client expansion cluster, no tracking issue filed per Q6c).
- **Unmilestoned (deferred to evidence):** #72 (progressive thinking, defer to ACP-server), #90 (rendering constants, defer to post-v0.2.1-split).
- **Filed:** **#162 — ACP-server first cut.** Session lifecycle, streaming text, permission round-trip per Q5's scope discipline. Anchor of repurposed v0.1.3.
- **Milestone descriptions rewritten:** v0.1.2 (narrowed to #127 + #158), v0.1.3 (repurposed: #162 + #143 + minimal #137), v0.2.1 (tracing-only + #92 tech-debt ship-along).

**Final milestone shape:**

| Milestone | Open | Scope |
|---|---|---|
| v0.1.1 | 7 | Foundation hardening (unchanged) |
| v0.1.2 | 2 | Visibility: #127 README + #158 MCP ship-along |
| v0.1.3 | 3 | **ACP-server first cut** + #143 + minimal #137 |
| v0.2 | 10 | Sub-agents + migrated #154 |
| v0.2.1 | 6 | Tracing maturation + #92 |
| v0.3 | 3 | Federation + repo-as-package (unchanged, undercommitted at issue level) |

**Carryover from sessions 1–5 (decision frame, now migrated):** the platform stance is "harmonize, don't decompose" — the hub grows three new protocol surfaces (MCP-server, ACP-server, ACP-client) alongside the existing A2A-server / MCP-client / planned A2A-client; the CLI contracts to hub system ops + a verification-only dev REPL; the #128 workspace split is deferred indefinitely (#132's BFF framing rejected on the merits). All seven decision questions resolved 2026-05-17 and now live in [`docs/decisions.md`](docs/decisions.md#platform-stance) (rationale) + [`docs/architecture.md`](docs/architecture.md#deliverables-hub-vs-cli) (architectural shape). The hygiene pass executed Q6's mutations with Q7's #137 disposition in hand.

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

**Open in v0.1.1 (4 issues):** #85 (GitContext limits), #123 (skill tracing wiring), #125 (SKILL.md runtime wiring), #156 (per-subcommand approval at executor). #124 moved to v0.1.2 (pairs with README/demo), #135 moved to v0.1.3 (validates post-ACP state), #89 unmilestoned (design-first, needs conversation before commitment).

**2026-05-19 (ninth session — PR 1 #156 implemented):** Per-subcommand approval at executor level is implemented on branch `feature/per-subcommand-approval`. Key change: `_wrap_with_approval` in `backend.py` evaluates `ApprovalPolicy.evaluate(args)` at call time and raises `ApprovalRequired` for `mode="always"` matches. Tools are no longer registered with `requires_approval=True`; instead the callable itself raises `ApprovalRequired` and pydantic-ai defers only that call. This enables `git diff` → execute immediately, `git push` → defer, within the same tool.

Changes: `backend.py` (new `_wrap_with_approval` + `_build_args_string`, replaced `_policy_requires_approval` → `_tool_has_approval_policy`, updated `_get_approval_description` to accept `call_args`), `tools.py` (updated docstring + descriptions), `executor.py` (structured logging on deferred events), 254 lines of new tests. All `just ci` checks pass.

Next: PR 2 (`step-1-delete-context-providers`, #165 + closes #85) — the ninth-session execution plan in Design Sketches has full TDD order.

## Next session

**Start PR 2 (#165) implementation** — delete `context/` package, extract to `cli/file_scan.py` + `cli/completions.py`, rewrite `resolve_at_references`. Full plan in the "Ninth-session execution plan" sketch below.
   - Implementation: extract `file_scan.py`, write helpers, delete `src/fin_assist/context/`, remove `ContextProvider` plumbing from backend + hub + CLI startup
   - Pre-merge doc updates per AGENTS.md: update `docs/concept-inventory.md` "What this displaces" row for context providers (mark as done); update `handoff.md` (mark Step 1 shipped under Recent work); update v0.1.1 #85 issue scope; close v0.1.2 Step 1 issue when PR merges
   - Run `just ci`; open PR to main
5. **After Step 1 merges:** ACP-server work (#162 in v0.1.4) is unblocked; Step 2 (skills + tools) starts.

### Carryover gotchas

- **PR #152 reversion narrative.** When Step 1's PR description is written, be honest: `ContextProviderRegistry` shipped in #152 and is being reverted. Link to the platform-stance work that drove the reversal so future archaeology has the trail.
- **`ContextSettings` fate.** Currently threaded through hub + CLI as a hub-level setting. After Step 1, the size limits live with CLI helpers. Decide during Step 1 whether `ContextSettings` survives as a CLI-local config or gets inlined into the helpers. Lean: keep as CLI-local (still tunable; just no longer plumbed through the hub).
- **`#123` (skill tracing) timing.** Orthogonal to alignment; ships when convenient. Could be a small standalone PR before Step 1, between Step 1 and Step 2, or alongside Step 2. Don't gate Step 1 on it.

### Earlier session context — seventh-session resolution (superseded by eighth session)

The seventh session resolved a starting-point decision (Path C — selective v0.1.1 prefix, then #162) with a 7-step dependency-driven execution plan. **That plan is superseded** by the concept-inventory alignment surfaced in the eighth session. The v0.1.4 (renumbered from v0.1.3) ACP-server work (#162) is now gated on the alignment milestone (v0.1.2). The portions of the seventh-session plan that survive (#85 rescoped, #156, #123) stay in v0.1.1.

The seventh-session reasoning chain is preserved in `git log` (see commit history around 2026-05-17) and `docs/decisions.md § Platform stance` for the architectural decisions that grounded it.

### Original seventh-session execution plan (preserved for reference)

**Resolution: Path C — selective v0.1.1 prefix, then #162.** Ship the v0.1.1 work that's directly load-bearing for ACP-server's first cut, then jump to #162. Backfill the rest of v0.1.1 as it closes out (or migrate to v0.1.2 / v0.2 as appropriate).

**Why Path C, not Path A or B:**

- **Path A (finish v0.1.1 first)** burns ~week+ on issues that are only partially load-bearing for ACP-server. #85 (GitContext limits), #124 (`/connect`), and #89 (system prompts as markdown) are orthogonal to ACP-server. #135 (dogfooding) is sort of meta — ACP-server itself becomes a more honest dogfooding loop than `fin talk`. Every day of v0.1.1 is a day Q4's protocol-peer claim stays unverified.
- **Path B (jump straight to #162)** builds ACP-server's permission round-trip on top of `ApprovalPolicy.evaluate()` that's only consulted at top-level mode for scoped CLI tools (#156 wires per-rule fnmatch gating), and ships ACP-server on top of a skill-loading path where `fin list skills` shows files that `fin do --skill` rejects (#125 + #123). That's shipping a protocol-peer that exposes the same incoherence to Zed. Likely surfaces more friction than it prevents.
- **Path C respects the dependency graph, ignores the milestone number.** Versioning-narrative cost is small: v0.1.1 doesn't ship as a clean milestone until later. Material cost is zero — Git tags don't care about issue order within a milestone.

### Execution plan (eighth session, 2026-05-18)

**Branching strategy: dependency-driven interleaving, all on main.** Research confirms the dominant best practice for sequential dependencies across milestones: merge each PR to main independently in dependency order, rather than milestone-per-branch. Milestones are tracking labels, not branch names. Each PR targets main directly — no stacking, no feature flags. (Source: stacked-PR pattern, trunk-based development, "merge early / never branch from another feature" rule.)

**Issue mutations (eighth session):**

- #124 → v0.1.2 (pairs with README/demo work)
- #135 → v0.1.3 (validates post-ACP state, becomes v0.1.3 exit gate)
- #89 → unmilestoned (design-first, needs conversation before commitment per AGENTS.md §Issues vs milestones)

**Final milestone shape:**

| Milestone | Open | Scope |
|---|---|---|
| v0.1.1 | 4 | #125 + #123 (skill coherence), #156 (approval gate), #85 (GitContext limits) |
| v0.1.2 | 3 | #127 README + #158 MCP ship-along + #124 `/connect` |
| v0.1.3 | 4 | #137 (positional grammar) → #143 (dead-code removal) → #162 (ACP-server) → #135 (dogfooding exit gate) |
| v0.2 | 10 | Sub-agents + migrated #154 |
| v0.2.1 | 6 | Tracing maturation + #92 |
| v0.3 | 3 | Federation + repo-as-package |

**Execution order (dependency graph):**

1. **#125 + #123** — one PR to main. SKILL.md runtime wiring + skill tracing share the same code paths. Load-bearing: protocol-peer should not expose skill loader inconsistency.
2. **#156** — one PR to main. Per-subcommand approval at executor gate. Load-bearing: ACP-server's `session/request_permission` uses the same mechanism.
3. **#85** — one PR to main. GitContext size limits. Standalone, not load-bearing for ACP.
4. **#137** — one PR to main. Positional grammar + entry_prompt two-turn fix. Changes how skill-load signals flow; must land before #143 deletes the old routes.
5. **#143** — one PR to main. Dead-code removal of `/skills` + `/skills/invoke` REST routes. Natural consequence of #137; pairs with ACP wiring.
6. **#162** — one PR to main. ACP-server first cut. Depends on #125/#123 and #156 being in place.
7. **#135** — one PR to main. Dogfooding repo agent. v0.1.3 exit gate — validates post-ACP state.

**Unscheduled:** #89 (system prompts — unmilestoned, design-first). Returns to a milestone when the design conversation resolves.

**Open questions (now resolved):**

- **#124 placement:** → v0.1.2. Pairs with demo/README work.
- **#89 placement:** → unmilestoned. Design-first per its own issue body; AGENTS.md says issues are for conversation, milestones for committed work.
- **#135 placement:** → v0.1.3. Validates post-ACP state; better exit gate than v0.1.1 entry gate.
- **Interleaving vs sequential:** → dependency-driven interleaving, all on main. Milestone boundaries are tracking labels, not branch boundaries.

**Earlier session context (kept for reference):**

- **2026-05-15:** Windows `fin start` background-detachment fixed (multi-layer bug: Unix-only `fcntl`, wrong `creationflags`, `pythonw.exe` swap that broke uv installs). Final combination: `CREATE_NO_WINDOW` + `STARTUPINFO(SW_HIDE)`. See [`docs/decisions.md`](docs/decisions.md#fin-start-background-spawn-on-windows).
- **2026-05-10:** Audited `AgentCardMeta` field wiring — `serving_modes` is the only enforced field; the rest (`supported_context_types`, `supported_providers`, `supports_model_selection`, `supports_thinking`) are declarative-only. Provider filtering + model selection + thinking gate deferred to v0.2.1 milestone notes.

---

## Design Sketches

### Concept Inventory Migration (sketched 2026-05-18, resolved end of eighth session)

**Status:** Decided. Destination state in `docs/concept-inventory.md`; all five open questions resolved; milestone shape decided. This sketch holds the in-flight migration plan (code touchpoints + step-by-step ordering) until the first migration PR lands.

#### Resolved decisions (one-line summary; full reasoning in `docs/concept-inventory.md`)

1. **Built-in tool fate.** All five (`read_file`, `git`, `gh`, `shell_history`, `run_shell`) rehome as skill-bound `@tool` functions. Conservative path — nothing deleted in this iteration.
2. **`@-completion` backing.** Thin CLI-local helpers per `@-prefix`, written fresh. `FileFinder`'s gitignore+fuzzy-match+caching logic extracted to a CLI utility module (e.g. `cli/file_scan.py`) to preserve perf work. `ContextItem` dropped; helpers return plain strings.
3. **Migration ordering.** Modified Option B: context-deletion first → skills+tools+built-ins as one big step → MCP scoping as small tail.
4. **MCP server scope.** Hub starts MCP servers lazily based on the union of agents' `mcp_servers` opt-in lists. CLI itself doesn't consume MCP (no change from today).
5. **System prompts.** Deferred to #89. Two-option sketch below for when #89 picks up.

#### Migration steps — final ordering

**Step 1: Context provider deletion + CLI `@-completion` rewrite.** (ACP-unblock; mechanically isolated; smallest blast radius.)

- Delete `src/fin_assist/context/` package (`base.py`, `files.py`, `git.py`, `history.py`, `environment.py`) — entire module gone
- Extract `FileFinder._scan_paths` + `_load_gitignore_spec` + `_matches_spec` into new `src/fin_assist/cli/file_scan.py` as plain functions (no class, no ABC)
- Write thin CLI helpers in `src/fin_assist/cli/completions.py` (or fold into `cli/prompt.py`): one helper per `@-prefix`. `@file:` uses `file_scan`; `@git:diff` / `@git:status` / `@git:log` shell out fresh; `@history:` reads shell history fresh; `@env:VAR` reads `os.environ` fresh
- Remove `ContextProvider` plumbing from `agents/backend.py` (tool delegation no longer needs it)
- Remove `ContextProviderRegistry` from `cli/main.py` startup + `hub/factory.py`
- Remove `context_settings: ContextSettings` parameter threading through the hub (the size limits now live with the CLI helpers, not in a hub abstraction) — *or* keep `ContextSettings` as a CLI-local config (TBD; lean: keep, it controls helper behavior)
- Update tests: delete `tests/test_context/`, write fresh `tests/test_cli/test_completions.py` + `tests/test_cli/test_file_scan.py`
- Absorbs #85 (GitContext size limits → CLI `@git:` helper size limits)

**Step 2: Unified skill registry + skill-bound `@tool` + built-in rehoming.** (The big one; ships as one PR to keep the replacement story coherent.)

- Add top-level `[skills.<name>]` parsing in `config/schema.py`
- `SkillLoader.load_all()` merges sources: project SKILL.md > user SKILL.md > top-level TOML > inline TOML
- SKILL.md frontmatter `agents: [...]` parsed for binding
- `AgentSpec.get_skill_definitions()` consults the unified registry, no longer reads only from `AgentConfig.skills`
- New `@tool` decorator in `src/fin_assist/agents/skill_tools.py` (location TBD; could be `skills/tools.py` for clearer scoping)
- `SkillLoader` discovers skill-bound tools: for each skill, look for `tools.py` in the skill directory; import; collect `@tool`-decorated functions
- `SkillManager.load_skill()` registers the skill's tools; `unload_skill()` removes them (skill manager already has lifecycle hooks for this)
- Built-in rehoming: move each of the five built-ins from `agents/tools.py` `create_default_registry()` into a shipped-default skill:
  - `read_file` → `core` skill (shipped default at `~/.config/fin/skills/core/`)
  - `git` → `git` skill
  - `gh` → `git` skill (gh subcommands are part of the git workflow) or separate `github` skill (TBD during execution)
  - `shell_history` → `shell` skill
  - `run_shell` → `shell` skill
- Delete `create_default_registry()` builtin definitions; the function shrinks to MCP-only
- Absorbs #125 (SKILL.md runtime wiring) — folded entirely
- Includes #123 (skill tracing wiring) if scheduling allows; otherwise ships independently
- `cli/main.py:_resolve_skill` reads from the unified registry

**Step 3: Per-agent MCP opt-in with lazy startup.** (Small mechanical change.)

- Add `mcp_servers: list[str] = []` field to `AgentConfig` in `config/schema.py`
- At hub startup, compute `union = set().union(*[agent.mcp_servers for agent in agents])`; only spawn MCP server processes in `union`
- `agents/backend.py` tool registration filters: an agent's tool set includes only MCP-tools from servers in its `mcp_servers` opt-in list
- Tests: agent-with-no-mcp-servers gets no MCP tools; servers not in any opt-in are not spawned
- Validation: warn at startup if `[mcp.servers.X]` is defined but no agent opts in (X is unused)

#### Code touchpoints (updated for resolved ordering)

Step 1 (Context deletion):

| File | Change |
|---|---|
| `src/fin_assist/context/` (whole package) | DELETE |
| `src/fin_assist/cli/file_scan.py` (new) | Extract `_scan_paths` / `_load_gitignore_spec` / `_matches_spec` as plain functions |
| `src/fin_assist/cli/completions.py` (new, or extend `cli/prompt.py`) | Thin helpers per `@-prefix`, returning plain strings |
| `src/fin_assist/agents/backend.py` | Remove `ContextProvider` plumbing |
| `src/fin_assist/cli/main.py` | Remove `create_default_context_registry` calls + parameter threading |
| `src/fin_assist/hub/factory.py` | Remove context registry from `create_hub_app` |
| `tests/test_context/` | DELETE; replaced by `tests/test_cli/test_completions.py` + `tests/test_cli/test_file_scan.py` |

Step 2 (Skills + tools):

| File | Change |
|---|---|
| `src/fin_assist/config/schema.py` | Add top-level `[skills.X]` table parsing; `SkillConfig.agents` for SKILL.md binding |
| `src/fin_assist/agents/skills.py` | `SkillLoader.load_all()` merges sources with precedence; SKILL.md frontmatter `agents:` parsed |
| `src/fin_assist/agents/skill_tools.py` (new) | `@tool` decorator; skill-directory discovery |
| `src/fin_assist/agents/spec.py` | `get_skill_definitions()` consults unified registry |
| `src/fin_assist/agents/tools.py` | `create_default_registry()` shrinks to MCP-only; built-ins removed |
| Shipped-default skills (new) | `core/` (read_file), `git/` (git, gh), `shell/` (shell_history, run_shell) |
| `src/fin_assist/cli/main.py` | `_resolve_skill` reads unified registry; `fin list skills` reflects new sources |
| `src/fin_assist/hub/factory.py` | `/skills` + `/skills/invoke` (existing) use unified registry |
| `tests/test_agents/test_skills.py` | Merge + binding tests |

Step 3 (MCP scoping):

| File | Change |
|---|---|
| `src/fin_assist/config/schema.py` | `AgentConfig.mcp_servers: list[str] = []` |
| `src/fin_assist/agents/backend.py` | Tool registration filters by agent's opt-in list |
| `src/fin_assist/agents/mcp.py` | `MCPToolProvider` consumes union, not full set |
| `src/fin_assist/cli/main.py` / `hub/factory.py` | Lazy startup logic; warn on unused server |
| `tests/test_agents/test_mcp.py` | Opt-in filtering + lazy-startup tests |

#### Milestone shape

**Resolved:** new `v0.1.2 — Concept inventory alignment` milestone, three issues (one per step). Existing `v0.1.2` (visibility) renumbers to `v0.1.3`; existing `v0.1.3` (ACP-server) renumbers to `v0.1.4`. `#125` migrates from `v0.1.1` into the new `v0.1.2` (folded into Step 2 issue). `#123` stays in `v0.1.1` (orthogonal). `#85` stays in `v0.1.1` but is rescoped (now about CLI `@git:` helper size limits, not `GitContext`).

Final milestone shape after mutations:

| Milestone | Open | Scope |
|---|---|---|
| v0.1.1 | 3 | #85 (rescoped: CLI helper size limits), #123 (skill tracing), #156 (per-subcommand approval) |
| **v0.1.2 (new)** | 3 | **Step 1 (context deletion), Step 2 (skills + tools), Step 3 (MCP opt-in)** |
| v0.1.3 (was v0.1.2) | 3 | #127 README + #158 + #124 |
| v0.1.4 (was v0.1.3) | 4 | #137, #143, #162 ACP-server (gated on v0.1.2 Step 1), #135 |
| v0.2 | 10 | Sub-agents (unchanged) |
| v0.2.1 | 6 | Tracing maturation (unchanged) |
| v0.3 | 3 | Federation + repo-as-package (unchanged; v0.2/v0.3 milestone descriptions need updating to drop stale `FileToolProvider` references) |

#### System prompts: two-option sketch (for when #89 picks up)

The alignment work doesn't touch prompts. When #89 graduates, the two candidate shapes:

**Option 1 — Two-shape pattern (mirrors skills):** `system_prompt` field accepts either inline string content OR a `@name` reference resolving through: `[prompts.<name>]` TOML → `.fin/prompts/<name>.md` → `~/.config/fin/prompts/<name>.md` → hardcoded Python registry as fallback. Same precedence rule as skills. No breaking changes; current configs that reference `"chain-of-thought"` etc. still work via the Python-registry fallback.

**Option 2 — Delete the Python registry, require config:** Current `SHELL_INSTRUCTIONS` / `CHAIN_OF_THOUGHT_INSTRUCTIONS` / `TEST_INSTRUCTIONS` move to shipped-default markdown files in the repo (e.g. `fin_assist/data/prompts/chain-of-thought.md`). The hardcoded `SYSTEM_PROMPTS` dict goes away. Breaks current configs unless we ship the markdown files in the package data.

**Default lean: Option 1.** Same reasoning as skills — additive change, no breakage, clear precedence.

**Note for #89 author:** the destination state for prompts depends partly on whether skills end up having `prompt_template` references (see `SkillConfig.prompt_template` in `config/schema.py:205`). If skills carry prompt fragments, prompts and skills might want to share a lookup mechanism. Worth checking the skill code surface when picking up #89.

#### Issues to update on GitHub (eighth-session mutations)

Captured here as a checklist; mutations execute during the eighth-session end-of-session GitHub pass.

- [ ] Comment on closed #129: its Phase A resolution shipped but is being reverted as part of this alignment; the new direction is in `docs/concept-inventory.md`
- [ ] Rename existing v0.1.2 milestone → v0.1.3
- [ ] Rename existing v0.1.3 milestone → v0.1.4
- [ ] Create new v0.1.2 milestone "Concept inventory alignment" with description pointing at `docs/concept-inventory.md` + this migration sketch
- [ ] File 3 step-issues under new v0.1.2 milestone (one per migration step)
- [ ] Move #125 from v0.1.1 into new v0.1.2 (commenting that it's folded into Step 2 issue)
- [ ] Rewrite v0.1.1 description: drop stale `ToolProvider` and `ContextProvider` architecture notes; remove #125 reference; rescope #85 mention
- [ ] Rewrite v0.1.3 (was v0.1.2) milestone description: still visibility, but ships after alignment so demo shows new state
- [ ] Rewrite v0.1.4 (was v0.1.3) milestone description: ACP-server now depends on v0.1.2 alignment Step 1
- [ ] Rewrite v0.2 milestone description: drop "File-based tool discovery note" referencing `FileToolProvider`; point at `docs/concept-inventory.md` for the new direction (skill-bound `@tool`)
- [ ] Update #85 issue body: scope shifts from `GitContext` provider size limits to CLI `@git:` helper size limits

#### What this sketch is not

- **Not a destination-state spec.** That's `docs/concept-inventory.md`.
- **Not a code patch.** The touchpoints tables are for planning, not implementation.

#### When this sketch retires

This sketch retires when the first migration PR (Step 1: context deletion) opens. At that point: the durable destination state is in `docs/concept-inventory.md`; the milestone exists with three issues; the work is committed. This sketch deletes.

---

### ~~ToolProvider + ContextProvider Protocols: Unifying Provider Registration (sketched 2026-05-10, extended 2026-05-16)~~ — SUPERSEDED 2026-05-18

**Status:** **Superseded by the Concept Inventory Migration sketch above (2026-05-18).** The architectural premise (unify tool sources under a `ToolProvider` aggregation; build a parallel `ContextProviderRegistry`) is no longer the direction. The destination state in `docs/concept-inventory.md` deletes both abstractions:

- `ToolProvider` aggregation → `MCPServerRegistry` (MCP only); built-in tools rehome to skills via `@tool` decorator
- `ContextProviderRegistry` → deleted entirely; ACP carries inbound context, MCP carries data-shaped context

PR #152 shipped Phase A of this sketch's plan (`ContextProviderRegistry` in `src/fin_assist/context/base.py`). That code is being reverted as part of the alignment.

This sketch is retained in this file with a strikethrough header so:

1. Eighth-session readers see the pivot context inline (the "what changed and why" surfaces here)
2. The industry-pattern research (Strands, mcpp, Pi, AgentPatterns.ai, InitRunner, R2R) isn't lost — some of it informed the eventual skill-bound `@tool` decision

It deletes when the alignment migration ships. Until then, treat any reference to "ToolProvider protocol" or "ContextProviderRegistry" in milestone descriptions or issue bodies as stale; the canonical state is `docs/concept-inventory.md`.

The original sketch body follows for reference.

---

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
