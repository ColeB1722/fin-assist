# Platform Stance

**Status:** all questions resolved 2026-05-17. Awaiting issue-hygiene pass + doc migration before deletion / compression.
**Owner:** Cole, with AI-assisted synthesis.
**Lifecycle:** this doc is *not* a forever-doc. Now that all decisions have resolved, the next two phases are (1) the issue-hygiene pass that executes Q6's enumerated GitHub mutations with Q7's #137 disposition in hand, and (2) migration of durable claims to [`architecture.md`](architecture.md) and [`decisions.md`](decisions.md). After migration, this file is either deleted or compressed to a one-paragraph historical pointer.

**What this doc is:** a decision frame for a cluster of strategic questions about fin-assist's relationship to the broader agent ecosystem — what protocol surfaces the hub exposes, what the CLI is (product or reference client), how that interacts with the long-pending workspace split (#128), and the underlying platform-vs-UX stance that resolves which question is even worth asking.

**What this doc is not:**

- Not `architecture.md`. That doc describes the system as built; this doc describes a decision in progress.
- Not `handoff.md`. That doc rolls per-session; this one is stable for the duration of the decision (weeks, not months).
- Not a position paper. The decision frame is intentionally laid out without a recommendation. Recommendations belong in the resolution of each question, not in the framing.

**How to consume this doc:**

- Sections 1–2 (Context, Ecosystem) are current-state and verifiable.
- Section 3 (Decision frame) lays out the questions without resolving them.
- Section 4 (Open questions, decomposed) is the elephant in bite-sized pieces. Each question has an internal ID (`Q1`, `Q2`, …); when a question graduates to a GitHub issue or a `decisions.md` row, that resolution is recorded inline.
- Section 5 (Recorded thinking) summarizes the prior reasoning in existing issues so the doc can stand alone without a reader hopping to GitHub for context.
- Section 6 (Working notes) is dated scratch space for between-session reasoning.

**Update cadence:** intentionally incomplete on first commit. Each follow-up commit takes one bite — one question section filled in, or one decision resolved — and updates this doc accordingly. The discipline is the same as `handoff.md`'s "no batched updates," applied at the level of strategic questions instead of session work.

---

## 1. Context (what's true today)

Everything in this section is **current-state and verifiable**. No speculation. If a claim here can't be confirmed from the code, the architecture doc, or a closed-out issue, it doesn't belong here.

### 1.1 The hub-vs-CLI shape

fin-assist is structurally two deliverables in one repository, separated by the A2A protocol:

- **Agent Hub** (`src/fin_assist/hub/`) — FastAPI server on `127.0.0.1:4096`. Hosts agents as A2A sub-apps under `/agents/{name}/`. Routes A2A traffic, persists conversation context in SQLite (`ContextStore`), manages task lifecycle via `Executor` + a2a-sdk's `DefaultRequestHandler`.
- **CLI** (`src/fin_assist/cli/`) — the one-and-only client today. REPL via `prompt_toolkit`, rendering via Rich, A2A client via `cli/client.py` (a2a-sdk's `Client.send_message`), session storage, prompt completion (`@file:`, `@git:`, `@history:`, `@env:`).
- **Platform abstractions** — sibling packages at the flat `src/fin_assist/` namespace, consumed by both deliverables: `agents/`, `config/`, `context/`, `credentials/`, `llm/`, plus top-level modules (`paths.py`, `providers.py`, `protobuf.py`, `tracing_shared.py`). This is a third implicit tier, acknowledged in `docs/architecture.md` § *Deliverables: Hub vs Client* but not formally named as a separate package.

The hub-vs-CLI firewall is **enforced in CI** via two `forbidden` contracts in `pyproject.toml` under `[tool.importlinter]`, run by `just lint-imports`:

- `hub/` must never import from `cli/`.
- `cli/` must never import from `hub/`, with a small allowlist for the in-process launcher path (`cli/main.py → hub.app|logging|pidfile|tracing`, `cli/tracing.py → hub.file_exporter`).

`cli/server.py` (process lifecycle: `start`/`stop`/`status`/`ensure_running`) is *not* on the allowlist — it spawns the hub via `Popen` + `httpx` and never imports `hub.*`. That cross-process boundary is the cleanest possible separation and is considered load-bearing.

### 1.2 Protocol surfaces fin currently speaks

| Surface | Role | Status | Module |
|---|---|---|---|
| **A2A** (server) | Hub exposes one A2A endpoint per agent; clients send tasks. JSON-RPC over HTTP with SSE for streaming. | Implemented, primary transport. | `hub/factory.py`, `hub/executor.py`, a2a-sdk v1.0 |
| **A2A** (client) | The CLI is an A2A client. No other A2A clients of the hub exist. | Implemented. | `cli/client.py` |
| **MCP** (client) | Hub-as-client connects to configured MCP servers at startup; their tools are namespaced `mcp.<server>.<tool>` and registered as `ToolDefinition`s. | Implemented in v0.1.1 via #84 / PR #152. | `agents/mcp.py` (`MCPToolProvider`) |
| **MCP** (server) | Hub exposes its agents as MCP tools to external hosts (Claude Desktop, Claude Code, opencode-as-host). | **Not implemented. No issue.** | n/a |
| **ACP** (server) | Hub speaks Agent Client Protocol so editors (Zed, JetBrains, Neovim, VS Code via vscode-acp) can drive fin agents. | **Not implemented. No issue.** | n/a |
| **ACP** (client) | Hub drives external ACP-speaking agents (cursor-agent, gemini-cli, claude-acp) as backends. | **Not implemented. No issue.** | n/a |

Two custom REST routes exist on the hub today (`POST /agents/{name}/skills/invoke`, `GET /agents/{name}/skills`) that are *not* A2A — they exist purely to serve the current CLI's skill-loading flow. They are slated for removal in v0.1.3 by #143 when skill loading moves into the A2A `message/send` flow.

### 1.3 The platform stance, as articulated 2026-05-17

From the conversation that prompted this doc, transcribed without paraphrase:

> I want to have a system that I can, with a reasonable amount of work, integrate with arbitrary systems in order to make that system agent-enhanced. […] I think I am more interested conceptually with fin as a platform, vs thinking through the user experience. While that has its time and place, it scratches a different itch from what I'm trying to accomplish with fin.

This is **not yet codified** in `architecture.md`. The architecture doc currently says:

> **CLI-first, TUI-later.** Start with a simple CLI client for fast iteration and testing, then layer on TUI and other clients. The server is the stable core; clients are interchangeable.

The two framings are not contradictory but they differ in emphasis: the architecture-doc framing treats the CLI as the *primary* client with others *layered on later*; the stated stance treats fin as *infrastructure*, with the CLI as one possible front-end among N. Which framing is canonical is one of the questions this doc resolves.

### 1.4 Recorded thinking on reorganization

Three open issues capture the prior thinking on structural change. Full summaries are in §5; the one-line versions:

- **#128 (unmilestoned)** — durable design thinking on a uv-workspace split into `fin-protocol` + `fin-hub` + `fin-cli`. Explicitly deferred until a forcing function fires; rejected multi-repo and "BFF as a separate product."
- **#132 (unmilestoned)** — proposes Zed/ACP integration as the *forcing function* for BFF decomposition. Reasons in the opposite direction from #128 on the BFF question; the disagreement has not been resolved on paper.
- **#146 (unmilestoned)** — `fin pkg` package manager. Explicitly distinguishes `uv tool install fin-hub` (platform binary) from `fin pkg install <agent>` (agent installer), endorsing a split of management CLI from conversational client.

### 1.5 Active milestone state

For context on what's currently committed work that this decision interacts with:

- **v0.1.1** — 7 open issues (foundation hardening: GitContext limits, SKILL.md runtime, /connect, dogfooding, per-subcommand approval). Independent of this decision.
- **v0.1.2** — README badges + demo. Will reflect whatever the platform stance is by the time it ships.
- **v0.1.3** — CLI grammar v2 (#137), dead-code removal (#143), async cascade (#154). **This is the milestone most directly affected by this decision** — if the CLI becomes "reference client, not product," the urgency of #137's grammar work drops significantly.
- **v0.2** — sub-agents. Mostly independent; the protocol-surfaces question is orthogonal to whether agents can invoke sub-agents.
- **v0.2.1** — UX polish. Same caveat as v0.1.2.
- **v0.3** — federated sub-agents + repo-as-package. Interacts with this decision via "what does ACP-client mean as a way to invoke external agents alongside A2A-federation."

---

## 2. Ecosystem snapshot (May 2026)

This section is dated because the ecosystem is moving fast. If this doc is being read more than ~3 months after the date above, **verify these claims still hold before relying on them**.

### 2.1 The three protocols and what they standardize

| Protocol | Boundary | What's standardized | Governance | Production adoption |
|---|---|---|---|---|
| **A2A** (Agent2Agent) | Agent ↔ agent | Discovery via Agent Cards at `/.well-known/agent-card.json`. Task lifecycle (submitted, working, completed, failed, auth-required, canceled). Structured artifacts. JSON-RPC + SSE + gRPC peers. Signed agent cards for identity verification. | Linux Foundation (donated by Google June 2025). v1.0 March 2026. | 150+ orgs. Microsoft Azure AI Foundry, AWS Bedrock AgentCore, Google Cloud, Salesforce, SAP, ServiceNow, Atlassian. SDKs: Python, Go, Java, JS, .NET. |
| **MCP** (Model Context Protocol) | Agent ↔ tools / resources / prompts | Tool definitions with JSON Schema inputs. `tools/list`, `tools/call`, `resources/list`, `resources/read`, `prompts/list`. Stdio + HTTP/SSE + streamable-HTTP transports. Tool annotations (`readOnlyHint`, `destructiveHint`). | Anthropic-led, broad adoption. | Claude Desktop, Claude Code, opencode, Codex, Cursor, GitHub Copilot. Hundreds of community servers. |
| **ACP** (Agent Client Protocol) | Client (editor/TUI) ↔ agent | JSON-RPC over stdio. Session lifecycle, streaming text/edit/tool-call updates, permission prompts, MCP-server forwarding from client to agent, real-time edit visualization. | Zed-led (Aug 2025), open under Apache 2.0. | Zed, JetBrains IDEs, Neovim (via Code Companion), VS Code (via vscode-acp). SDKs: Rust, TypeScript, Python, Java, Kotlin. |

### 2.2 The Zed framing

The reason ACP matters for this decision is the explicit framing Zed published when they introduced it (August 2025):

> Just as the Language Server Protocol unbundled language intelligence from monolithic IDEs, our goal with the Agent Client Protocol is to enable you to switch between multiple agents without switching your editor.

This is the LSP-for-agents move. It's the protocol that exists to make the client-agent boundary pluggable. fin's existing A2A boundary is the *agent-agent* boundary; MCP is the *agent-tool* boundary; ACP is the third boundary, currently not spoken by fin in either direction.

### 2.3 opencode as a data point

opencode is a Bubble Tea TUI-based agent harness with ~75+ LLM provider support. As of December 2025 ([PR #5095](https://github.com/anomalyco/opencode/pull/5095)) it accepts **ACP backends as LLM providers** — meaning opencode can drive cursor-agent, goose, gemini-cli, or any ACP-speaking agent as its underlying model. The PR author's framing:

> By enabling ACP as a backend provider, we don't need a unique translation layer for OpenCode to multiple CLI backends.

This is structurally the same realization that prompted this doc, applied in opencode's own architecture six months earlier. The implication for fin is that **opencode is simultaneously a candidate ACP client (driving fin via ACP-server) and a candidate ACP backend (driven by fin via ACP-client)** — the same protocol, two roles, both relevant.

opencode also has:

- A client/server architecture (`opencode serve`) — the TUI is one of several clients of an HTTP API.
- A plugin system with `~25+ lifecycle hooks` (`@opencode-ai/plugin`) covering provider hooks, tool registration, OpenTUI components.
- Local file-based plugin discovery (`.opencode/plugins/`, `.opencode/tool/`) — strong parallel to our planned `.fin/skills/` + `.fin/tools/` Phase C work in v0.2.

### 2.4 Pi and the "agent framework" position

Pi (the agent framework, not the protocol) is one of several frameworks (alongside Strands, LangGraph, CrewAI, Goose) that occupy the *agent definition + composition* position. Adopting Pi means fin-hub becomes a runtime hosting Pi-defined agents; this puts Pi in the platform position and fin in the runtime position. Same structural inversion as "adopt opencode as our TUI" — it changes which side of the relationship fin is on.

Pi has its own opinions about tool discovery, composition, and packaging — some of which align with our Phase C/D plans (`.fin/tools/`, repo-as-package) and some of which differ. Adopting Pi commits to Pi's opinions; building a Pi-compatibility surface alongside our own is a different (and additive) move.

### 2.5 What's notably missing from this snapshot

Things we did **not** survey thoroughly and should before finalizing any of the questions in §4:

- **gRPC adoption of A2A** — A2A v1.0 supports gRPC; some enterprise deployments may prefer it. fin uses JSON-RPC exclusively today.
- **A2A Signed Agent Cards** — v1.0 feature for cryptographic identity verification. Not used by fin (we're local-only) but relevant if remote topologies (Tailscale) become real.
- **MCP-server adoption ecosystem** — there are hundreds of MCP servers; we should look at how published servers structure themselves before deciding to ship a fin-hub-as-MCP-server.
- **VS Code's relationship to ACP** — `vscode-acp` is community-maintained; we should check whether Microsoft is going its own direction with the Copilot extension and what that implies for ACP reach.
- **MCP roots / sampling** — newer MCP features that change the agent-tool boundary; should be considered if we ship MCP-server.

### 2.6 Sources

Surveyed 2026-05-17 via web search. Key references:

- A2A: [a2a-protocol.org](https://a2a-protocol.org/), [a2aproject/A2A on GitHub](https://github.com/a2aproject/A2A) (23k stars, 150+ org coalition), [Google Cloud blog on v0.3 → v1.0](https://cloud.google.com/blog/products/ai-machine-learning/agent2agent-protocol-is-getting-an-upgrade).
- MCP: [modelcontextprotocol.io](https://modelcontextprotocol.io/), [Claude Agent SDK custom tools docs](https://code.claude.com/docs/en/agent-sdk/custom-tools).
- ACP: [agentclientprotocol.com](https://agentclientprotocol.com/), [Zed's launch announcement (Aug 2025)](https://zed.dev/blog/bring-your-own-agent-to-zed), [zed.dev/docs/ai/external-agents](https://zed.dev/docs/ai/external-agents), [zed-industries/agent-client-protocol on GitHub](https://github.com/zed-industries/agent-client-protocol).
- opencode: [opencode.ai/docs](https://opencode.ai/docs), [PR #5095 (ACP backend provider)](https://github.com/anomalyco/opencode/pull/5095), [PR author's framing](https://www.teamday.ai/harness/opencode).

---

## 3. The decision frame

The four questions below were framed and resolved together in the 2026-05-17 working session. Each carries its rationale inline; the full decomposed treatment with options-considered is in §4.

### Question A — Integration direction

> Is fin primarily infrastructure that other systems integrate into, or an orchestrator that composes other systems?

**Resolved (2026-05-17): both, with no sequencing implied.** The framing "(a) vs (b)" turned out to be a false dichotomy when mapped onto concrete protocol surfaces. The hub does both simultaneously because each direction maps to a different protocol *role*, not a different deliverable. Inbound surfaces (A2A-server, MCP-server, ACP-server) are how systems integrate fin into themselves. Outbound surfaces (MCP-client today; A2A-client and ACP-client later) are how fin composes external systems. These are independent vectors that can grow at their own cadence.

The platform stance that drove this decision: *"I want a system that I can, with a reasonable amount of work, integrate with arbitrary systems in order to make that system agent-enhanced."* Both directions serve that goal — inbound makes fin reachable; outbound makes fin compositional.

### Question B — Protocol surfaces to expose

> Which of ACP-server, MCP-server, ACP-client, others do we add, in what order?

**Resolved (2026-05-17): three inbound, three outbound, all on the hub.**

| Direction | Surface | Status | Consumers / peers |
|---|---|---|---|
| Inbound | A2A-server | Existing | CLI dev-REPL; future A2A peers |
| Inbound | **MCP-server** | New | Claude Desktop, Claude Code, opencode-as-host, Cursor — any MCP host |
| Inbound | **ACP-server** | New | Zed, JetBrains, Neovim, VS Code (via vscode-acp) |
| Outbound | MCP-client | Existing (v0.1.1 / #84) | Configured MCP tool servers |
| Outbound | **ACP-client** | New | cursor-agent, claude-acp, gemini-cli, goose |
| Outbound | A2A-client | v0.3 (federation) | Federated A2A agents |

A2A, MCP, and ACP are **sibling protocols at different layers, not substitutes**. A2A is shaped for agent-to-agent (task lifecycle, artifacts, signed identity); MCP is shaped for agent-to-tool (JSON-Schema tool defs, resources, prompts); ACP is shaped for editor-to-agent (streaming text/edit deltas, permission round-trips, MCP-server forwarding from client to agent). Both inbound *and* outbound ACP are bundled into one architectural commitment because the cost is largely shared (same protocol library, same session model) and the outbound side is what makes "compose arbitrary ACP agents into fin" tractable without forcing every external agent to grow an A2A face.

Sequencing of when each *new* surface lands is a separate, downstream question (see §4 Q5). The architectural commitment is to the destination shape.

### Question C — CLI stance

> Reference client (dev tool), first-class product (status quo), or removed entirely?

**Resolved (2026-05-17): dev tool only.** The CLI's scope contracts to two responsibilities:

1. **Hub system operations** — `start` / `stop` / `status` / `health`, agent configuration, credential management (`/connect`), and eventually `fin pkg` (#146) for agent installation.
2. **Simplified REPL for development QoL** — a minimal test harness to verify a newly configured agent responds, exercise an MCP server registration, or sanity-check a skill. Not an end-user product surface.

The conversational REPL does not grow into a fully-featured chat client. End-user conversational use happens through the inbound surfaces — MCP-host clients, ACP-speaking editors, future A2A clients. This collapses the previous "two deliverables" framing in `architecture.md` into one deliverable (the hub) with three inbound integration surfaces, of which the CLI's dev-REPL is just one A2A consumer among many.

The custom REST routes already slated for removal in v0.1.3 (#143) align with this stance — the dev-REPL talks A2A like every other inbound consumer; there are no CLI-shaped special cases on the hub.

### Question D — Workspace split timing

> Does the answer to A/B/C make #128 more urgent, less urgent, or unchanged?

**Resolved (2026-05-17): less urgent — deferred indefinitely.** The #128 ↔ #132 disagreement is resolved in favor of #128's "no decomposition without a forcing function" position, with the added clarification that **no forcing function is currently expected to fire**. The reasoning that drove #132 — "a second client forces the hub API to become client-agnostic" — no longer applies, because the strategy is not to grow a second *client* in the CLI sense. The CLI is contracting, not multiplying. New inbound consumers (MCP hosts, ACP editors) are not "clients of the hub API" in the BFF sense; they are *protocol peers* that interact through standardized inbound surfaces. The protocol *is* the boundary; no BFF layer is needed.

The hub-CLI import-linter firewall stays in CI for hygiene, but the workspace split is no longer on any horizon. #128 should reflect this resolution; #132's BFF framing is rejected on the merits, not just deferred. Issue updates are a follow-on session (see §4 Q6).

### Question E — Which new protocol surface ships first

> Of the three surfaces committed in Question B (MCP-server, ACP-server, ACP-client), which lands first?

**Resolved (2026-05-17): ACP-server first.** The platform-stance claim — *"fin is a platform with the CLI as one A2A consumer among many"* — is currently **unverified**. The CLI is the only consumer that exists today. Until a non-fin client drives the hub through a standardized protocol surface, the Question D resolution (new inbound consumers are *protocol peers*, not BFF clients) is asserted rather than tested. ACP-server is the smallest realistic surface that produces this verification: it forces the hub to serve a client whose shape, transport, and UX are not under fin's control.

**The dogfooding argument.** This is *not* the visibility-and-reach argument the original Q5 stub seeded (Zed/JetBrains/Neovim user base). The argument is narrower and more honest: a rich, externally-shaped integration point is the only way to exercise fin agents like a real consumer would. The current CLI is not a hostile test surface — fin controls both ends, and the protocol contract is shaped by the consumer's needs. ACP-server inverts that: the protocol contract is fixed (Zed-led, Apache 2.0, well-documented), and the hub has to fit. Bugs in the protocol-peer architecture surface as concrete client failures rather than design-doc speculation. Available ACP clients for the dogfooding loop: Zed (primary), Neovim via Code Companion, JetBrains, VS Code via `vscode-acp`. The user does not have to switch editors to test — Zed-as-test-client is sufficient.

**Secondary effects that make this the right first surface:**

- **Tests `Executor` under non-CLI request shapes.** Streaming text/edit deltas, permission round-trips, and ACP's client-to-agent MCP-server forwarding are paths the current CLI does not exercise. The hub's protocol-agnostic claim becomes verifiable.
- **Forcing function for Q7 (dev-REPL feature line).** Once a real editor can drive fin, "what does the dev REPL exclude?" becomes obvious — anything the editor does better. Q7 gets easier once ACP-server exists.
- **Validates Q4 on the merits.** If the protocol-peer architecture were wrong, ACP-server is where it would visibly fail (cross-cutting concerns leaking through the protocol, BFF-shaped translation needed in the hub, etc.). The absence of that pressure under a real second consumer is what would let Q4 ossify into a load-bearing claim.

**Scope discipline for the first cut.** ACP is a richer protocol than MCP-server would be — streaming, permission prompts, MCP-server forwarding from client to agent, edit visualization. The first cut is intentionally minimal: session lifecycle, streaming text, and permission round-trip. Edit visualization and full MCP forwarding land later or never, depending on what the dogfooding loop reveals. The point is to verify the architecture, not to ship a comprehensive ACP implementation.

**MCP-server and ACP-client remain committed** per Question B, sequenced behind ACP-server. Their order relative to each other is intentionally left open — different motivating evidence will likely emerge once ACP-server exists, and pinning their order now would burn that information.

**Milestone placement is Q6.** A working hypothesis (not a commitment): ACP-server first probably means a new v0.1.x or v0.2-adjacent slot, not v0.3 federation. v0.3 federation in `docs/architecture.md` is currently A2A-shaped; ACP-client (not ACP-server) is the surface that bundles cleanly with it. ACP-server is its own thing and likely deserves its own milestone window. Q6 confirms or contradicts.

### Question F — Holistic roadmap reconciliation under Q1–Q5

> Given Q1–Q5, what changes across the existing milestone roadmap, and where does ACP-server actually land?

**Resolved (2026-05-17): repurpose v0.1.3 as the ACP-server first cut; split v0.2.1; migrate #153 out of v0.1.2; migrate #154 to v0.2; close #133/#134; keep MCP-server and ACP-client unmilestoned.** A holistic milestone walk (Q6a) revealed that §1.5's "independent of this decision" assumptions were wrong in multiple places: v0.1.1 has more CLI-shape work than acknowledged (#124, #135, #156 — but all consistent with Q3's dev-tool framing, so the milestone holds); v0.1.2 contains substantive outbound-MCP-client work (#153) that does not fit a visibility milestone; v0.2.1 mixes CLI-polish (largely moot under Q3) with tracing-infrastructure (independent and valid); v0.3 is undercommitted at the issue level relative to its description, making it more malleable.

The reshuffled roadmap:

- **v0.1.1** — ships as-scoped (foundation hardening).
- **v0.1.2** — narrowed to true visibility: #127 (README) + #158 (MCP tech-debt ship-along). #153 migrates to a new MCP-client-expansion slot (with #139, #151).
- **v0.1.3** — *repurposed*. New anchor: first-cut ACP-server (session lifecycle, streaming text, permission round-trip per Q5's scope discipline) + #143 (dead-code removal from hub). #137 deferred to Q7's dev-REPL feature line decision; #154 migrates to v0.2.
- **v0.2** — sub-agents, as-scoped, plus migrated #154. Two notes: #64 (REPL session switching) is lower priority under Q3; #140 (second AgentBackend) is structurally a sibling of Q5's argument shape, validating the outbound-protocol claim where ACP-server validates the inbound-protocol claim.
- **v0.2.1** — *split*. Keep as tracing-infrastructure milestone (#106, #107, #108, #109, #111). CLI-polish issues mostly close (#67, #91, #94, #95, #97); a few defer to Q7 (#72, #90); one survives as tech-debt (#92).
- **v0.3** — federation + repo-as-package, as-scoped. Plausible future home for ACP-client per Q6c, not yet committed.
- **New unscheduled slot** — MCP-client expansion (#153 + #139 + #151); plausible future neighbor of MCP-server work.
- **Unmilestoned, architecturally committed** — MCP-server and ACP-client (per Q6c); awaiting evidence from ACP-server before placement.
- **Closed during hygiene pass** — #133 (Telegram client) and #134 (iOS client), both moot under Q3.

Execution (the GitHub mutations) is the issue-hygiene pass. This doc captures intent.

### Question G — Dev-REPL feature line

> What does the "minimal dev REPL" (per Q3) actually include and exclude, so it doesn't re-grow into a product surface by drift?

**Resolved (2026-05-17): verification-only.** The CLI's REPL exists to verify that an agent works after `/connect` + config. That is the entire job. Anything beyond verification — session management, conversation polish, multi-line edit, splash screens, rich rendering of tool results, `$EDITOR` integration for prompts — is out of scope. The principle is intentionally tight: the dev REPL is not a "small chat client" or a "developer-facing daily-driver"; it is the smallest thing that lets a developer confirm a newly configured agent responds correctly and that a skill loads and dispatches.

**What stays:**

- **Hub system operations** (per Q3): `fin start` / `stop` / `status` / `health`, `/connect`, `fin pkg` (#146 when it ships).
- **Basic A2A round-trip**: send a prompt, receive a response, see streaming tokens, see tool calls and approval prompts.
- **`@`-completion** (`@file:` / `@git:` / `@history:` / `@env:`): these stay because verifying a context-consuming agent *requires* injecting context. Removing completion would make some agents impossible to test from the dev REPL.
- **Positional grammar `fin do <agent> <skill> [prompt]`**: makes verification cleaner ("test this skill on this agent") and the two-turn `entry_prompt` semantics fix a real bug. The remainder of #137 (`--workflow` mode flag, `fin list skills` annotation rework) drops.
- **Core slash commands**: `/help`, `/exit`, `/connect`, `/agents`, `/skill:<name>` (skill loading is verification-shape).
- **Session persistence + `--resume`**: present-day mechanism. Out-of-REPL operations only (run `fin talk <agent> --list` then `--resume <slug>`).

**What's explicitly out (non-exhaustive):**

- **Interactive REPL session switching** (#64) — conversation management, not verification.
- **Splash screen / startup banner** (#67) — product polish.
- **Richer tool_result rendering beyond 120-char truncation** (#91) — visualization, not verification.
- **`fin do` vs `fin prompt` semantic split** (#94) — verification needs one entry point; duplicate semantics are exactly the drift Q7 prevents. `fin prompt` likely closes; #94 absorbs into the cleanup.
- **`/spec` verbose agent ASCII art** (#95) — product polish.
- **`$EDITOR` integration via `--edit`** (#97) — multi-line composition is a real client's job.
- **Telegram / iOS / other bespoke clients** (#133, #134) — moot under Q3, doubly moot under Q7.

**Deferred-to-evidence (Q6a flagged these for Q7):**

- **Progressive thinking output** (#72) — verifying agent behavior arguably benefits from seeing reasoning chains. *Resolution: defer to ACP-server work.* If ACP-server's streaming-text path handles thinking exposure, the dev REPL doesn't need its own. If not, file a follow-up.
- **Rendering constants consolidation** (#90) — pure tech-debt cleanup; only worth doing if the dev REPL keeps enough rendering surface to justify it. *Resolution: defer until the v0.2.1 split executes and the remaining dev-REPL rendering footprint is concrete.*

**Drift-prevention mechanism:** When `platform-stance.md` migrates to `decisions.md`, the verification-only principle ships with a non-exhaustive examples list (session switching, conversation polish, multi-line edit, rich rendering) so future contributors have something concrete to point at. The principle is the rule; the examples are the calibration.

**ACP-server is the forcing function — Q7 is a first cut.** Q5 already named this: once a real editor can drive fin, the exclusion list becomes obvious because the editor will do most of these things better. Q7 commits the framing now (so the issue-hygiene pass has the #137 disposition it needs); ACP-server work is expected to refine it. If ACP-server work reveals something the verification-only framing got wrong, file a follow-up against this resolution rather than re-litigating Q7 wholesale.

---

## 4. Open questions, decomposed

Q1–Q7 map one-to-one onto §3 Questions A–G and carry the options that were considered, including the ones not chosen, so the reasoning trail survives. Q6 is itself decomposed into Q6a (milestone walk), Q6b (ACP-server placement), and Q6c (MCP-server / ACP-client speculative slots), reflecting the holistic-decomposition framing used in the fourth session. All seven questions are now resolved; the next phase is the issue-hygiene pass and the doc migration to `architecture.md` + `decisions.md`.

### Q1: Integration direction (→ §3 Question A)

**Framing:** Whether fin is "infrastructure others integrate into" (inbound-shaped) or "orchestrator that composes others" (outbound-shaped), or both. The (a)/(b) framing surfaced in the initial conversation implied a sequencing question.
**Depends on:** none.
**Blocks:** Q2, Q3.
**Options considered:**
- *(a) Inbound-first.* Treat fin as infrastructure; outbound composition deferred.
- *(b) Outbound-first.* Treat fin as orchestrator; inbound surfaces only via existing A2A.
- **(c) Both, no sequencing.** Inbound and outbound are independent protocol roles, not competing product directions. Each surface lands when its motivating consumer or peer exists.
**Resolution:** resolved 2026-05-17 — option (c). The dichotomy dissolved once the question was mapped to protocol roles. Rationale in §3 Question A.

### Q2: Protocol surfaces (→ §3 Question B)

**Framing:** Of the surfaces fin does not yet speak (MCP-server, ACP-server, ACP-client), which to commit to architecturally. A2A-server and MCP-client are already shipped; A2A-client is committed via v0.3 federation.
**Depends on:** Q1.
**Blocks:** Q3, Q5.
**Options considered:**
- *Minimal: ACP-server only.* Smallest new surface; covers the editor integration use case.
- *ACP-server + MCP-server.* Reach editor ecosystem and MCP-host ecosystem.
- **ACP-server + MCP-server + ACP-client.** Both ACP directions bundled; full protocol coverage in both directions. *Chosen.*
- *All of the above + Pi compatibility surface.* Adopting an agent-framework opinion (Pi/Strands/LangGraph) was considered and rejected — it inverts which side of the relationship fin is on (fin becomes runtime under their definition layer).
**Resolution:** resolved 2026-05-17 — three new surfaces (MCP-server, ACP-server, ACP-client) committed architecturally. Bundling ACP-server and ACP-client into one design decision because the protocol library and session model are shared. Rationale in §3 Question B.

### Q3: CLI stance (→ §3 Question C)

**Framing:** Whether the CLI is a first-class end-user product, a reference client for the hub, or removed entirely. Affects the urgency of v0.1.3 CLI grammar work (#137).
**Depends on:** Q1, Q2.
**Blocks:** Q6, Q7.
**Options considered:**
- *First-class product (status quo).* CLI grows into a full TUI-shaped conversational client over time. Multiple clients planned (Telegram, etc.).
- **Dev tool only.** CLI does hub system ops + minimal test-REPL; conversational use happens through inbound MCP-server / ACP-server surfaces. *Chosen.*
- *Reference client only.* Even narrower — only what's needed to demonstrate the protocol. Rejected because hub system ops (start/stop, `/connect`, `fin pkg`) need a home and the CLI is that home.
- *Removed entirely.* Rejected — hub system ops still need a CLI surface and there's no compelling reason to push that to a separate binary.
**Resolution:** resolved 2026-05-17 — dev tool. Rationale in §3 Question C. Implications for v0.1.3 in Q6.

### Q4: Workspace split timing (→ §3 Question D)

**Framing:** Whether #128's deferred workspace split (`fin-protocol` + `fin-hub` + `fin-cli`) becomes more urgent, less urgent, or unchanged. The unresolved #128 ↔ #132 disagreement is also in scope.
**Depends on:** Q1, Q2, Q3.
**Blocks:** Q6.
**Options considered:**
- *More urgent (#132's position).* New protocol surfaces are "new clients" that force the boundary, so split now.
- **Less urgent — deferred indefinitely (#128's position, reinforced).** New surfaces are protocol peers, not BFF clients. The protocol *is* the boundary. *Chosen.*
- *Unchanged.* Rejected — the resolution should be explicit one way or the other.
**Resolution:** resolved 2026-05-17 — less urgent, deferred indefinitely. #132's BFF framing is rejected on the merits. Hub-CLI import-linter firewall stays for hygiene. Rationale in §3 Question D.

---

### Q5: Surface sequencing — which new protocol surface ships first? (→ §3 Question E)

**Framing:** Q2 commits to three new surfaces (MCP-server, ACP-server, ACP-client) but not the order. Each has a different cost profile, a different motivating consumer, and a different relationship to in-flight v0.1.x / v0.2 / v0.3 milestone work. The sequencing decision determines what (if any) new milestone work attaches and how the v0.1.x → v0.2 → v0.3 trajectory reshuffles. The dominant decision axis is **dogfooding fit** — which surface most directly tests the platform claim under realistic load — *not* user-facing visibility, since the platform stance is explicitly personal.
**Depends on:** Q2.
**Blocks:** Q6.
**Options considered:**
- *MCP-server first.* Smallest cost (fin already speaks MCP-client; the server side reuses much of the same library). Motivating consumers: opencode-as-host, Claude Desktop, Claude Code. **Considered but rejected as first** — the dogfooding loop is thin until multiple specialist fin agents exist worth delegating to, and "fin agents as opencode tools" is a feature-in-search-of-a-workflow at current maturity.
- *ACP-client first.* Enables composing existing ACP-speaking CLI agents (cursor-agent, claude-acp, gemini-cli, goose) into fin workflows. **Considered but rejected as first** — strong personal-tool-composition use case, but ACP-client adds *capability* without testing the platform *claim*. The hub still only has one inbound consumer (the CLI), so the protocol-peer architecture remains unverified.
- **ACP-server first.** *Chosen.* The first inbound consumer that is not under fin's control. Forces the hub to serve a non-fin client through a fixed external protocol contract. Validates the Q4 protocol-peer-not-BFF assertion on the merits, exercises `Executor` under non-CLI request shapes (streaming, permission round-trip), and creates the natural forcing function for Q7 (dev-REPL feature line).
- *All three in parallel.* Rejected — splits attention three ways before any single surface has produced architectural feedback. Sequencing exists precisely to extract that feedback.
- *None — finish v0.2 sub-agents first.* Rejected — v0.2 (sub-agents in-process) and the platform-claim verification are independent. v0.2 makes fin do more; ACP-server makes fin *prove it is a platform*. Different axes; no reason to gate one on the other.
**Resolution:** resolved 2026-05-17 — ACP-server first, with a minimal first cut (session lifecycle, streaming text, permission round-trip; defer edit visualization and full MCP forwarding). MCP-server and ACP-client remain committed (per Q2) and deferred; their order relative to each other is intentionally left open. Rationale in §3 Question E.

### Q6: Holistic roadmap reconciliation — what changes across the existing milestones, and where does ACP-server land?

**Framing:** Q1–Q5 created pressure across the entire in-flight roadmap, not just v0.1.3. A fresh `gh` pull (2026-05-17, fourth session) revealed that §1.5's "independent of this decision" assumptions were wrong in at least two places: v0.1.1 has more CLI-shape work than the summary acknowledged (#124, #135, #156); v0.1.2 has hidden protocol-substantive work (#153 — MCPContextProvider for outbound MCP-client resources) that does not fit a "visibility/marketing" milestone identity. Resolving Q6 in isolation — "which milestone for ACP-server" — would burn the chance to fix accumulated milestone drift and re-evaluate scope holistically.

Q6 is therefore decomposed into three sub-questions. Q6a does the holistic milestone walk; Q6b uses Q6a's output to place ACP-server; Q6c handles the still-deferred MCP-server and ACP-client surfaces. Each sub-question is one bite.

**Depends on:** Q3, Q5.
**Blocks:** Q7 (informed by Q6a's resolution of v0.2.1's identity), issue-hygiene pass (blocked on all of Q6).

#### Q6a — Does each in-flight milestone still make sense as scoped?

**Framing:** Walk every open milestone (v0.1.1, v0.1.2, v0.1.3, v0.2, v0.2.1, v0.3) through the Q1–Q5 lens. "No impact" is a useful explicit finding given that §1.5's prior assumptions of independence have already been contradicted twice. For each milestone, identify: (a) which issues remain valid under Q1–Q5, (b) which need re-scoping, (c) which are made moot, (d) whether the milestone's *identity* (its description / theme) still holds.

**Walk-through (verified against `gh` 2026-05-17):**

- **v0.1.1 (foundation hardening, 7 open).** Issues: #85, #89, #123, #124, #125, #135, #156. **Resolution: ships as-scoped, with a note.** All seven remain valid under Q1–Q5. #124 (`/connect`), #135 (dogfooding), and #156 (per-subcommand approval) are CLI-shape but explicitly belong to the dev-REPL responsibility (hub system ops + agent-config verification) that Q3 endorses. The milestone's identity is unchanged. The note worth recording: dogfooding the CLI (#135) is the *baseline* dogfooding, not the platform-claim verification dogfooding Q5 added. Both are valid; they test different things.

- **v0.1.2 (visibility / marketing, 3 open).** Issues: #127 (README badges + demo), #153 (MCP Part 2: MCPContextProvider for resources), #158 (MCPToolProvider isError/structuredContent handling). **Resolution: split the milestone's identity, migrate #153 out.** v0.1.2's stated identity is "visibility & marketing-surface pass" — #127 fits that exactly. #158 is fine as a ship-along (small MCP-client tech debt). But #153 is *substantive* outbound-MCP-client work — expanding fin to consume MCP resources, not just MCP tools — and does not belong in a marketing milestone. Migrate #153 to its own slot (likely paired with other outbound-MCP-client expansion: #139 design for MCP tool-approval policies, #151 MCP discovery caching). v0.1.2 stays a true visibility milestone with #127 + #158. The new MCP-client-expansion slot may end up adjacent to Q6c work on MCP-server, since they share library and config plumbing.

- **v0.1.3 (CLI grammar v2 + foundation, 3 open).** Issues: #137 (CLI grammar v2), #143 (dead-code removal from hub), #154 (async cascade). Also: the milestone *description* lists only #137 + #154; #143 is milestoned but absent from the body — pre-existing drift. **Resolution: restructure significantly.** Q3 (CLI as dev tool) substantially de-scopes #137: most of #137's grammar work was designed around the CLI being a fully-featured product surface. With the dev REPL contracting (Q7 will define the exact line), much of the positional `<agent> <skill>` parsing, `--workflow` mode flag, and `fin list skills` annotation work targets a UX surface that is no longer the priority. Three sub-resolutions:
  - **#137 — close or radically re-scope.** Close if Q7 (dev-REPL feature line) determines none of the grammar v2 work is needed for the contracted dev REPL. Re-scope to a minimal "fix the silent `entry_prompt` discard bug" issue if even the dev REPL needs the two-turn semantics. Decision deferred to Q7 because it depends on the dev-REPL feature line.
  - **#143 — keep, milestone-agnostic.** Dead-code removal from the hub (skills/invoke + /skills custom REST routes) is correct independent of CLI shape and aligns with Q3 (no CLI-shaped special cases on the hub). Could ship anywhere; suggest pairing with ACP-server work since that's the new "fewer hub-side special cases" frontier.
  - **#154 — keep, migrate.** `ToolProvider.discover()` async cascade is foundation work for v0.2 sub-agents and unrelated to CLI shape. Migrate to v0.2 directly — the milestone description in v0.1.3 even explains "lifted into this milestone because sub-agent invocation paths in v0.2 multiply the call sites," which means v0.2 is the natural home now that v0.1.3's anchor (#137) is in question.
  - **v0.1.3 as a milestone — likely close.** With #137 in flux, #143 migratable, and #154 migrated to v0.2, v0.1.3 has no anchor. Close it; reuse the slot for ACP-server (see Q6b) or leave the version number for a different anchor.

- **v0.2 (sub-agents, 9 open).** Issues: #31, #63, #64, #102, #110, #113, #121, #140, #150. **Resolution: ships as-scoped, with two notes.**
  - *Note 1 — #64 (interactive REPL session switching) is now lower priority.* Q3 makes the dev REPL a test harness, not a session-management product. #64 can stay in v0.2 as nice-to-have but should not be a blocker. Could also be deferred to "if the dev REPL grows a feature it needs Q7 to bless."
  - *Note 2 — #140 (second AgentBackend) is structurally a sibling of Q5's argument shape.* The issue body explicitly calls itself a "validate protocol shape" exercise — same structural move as ACP-server (validate the *outbound-protocol* claim with a second implementation, vs ACP-server validating the *inbound-protocol* claim). This is a coincidence worth noting: v0.2 already contains one protocol-shape-validation exercise. ACP-server is the second, at a different layer. Both are independently valuable; neither displaces the other; no scope change to v0.2.

- **v0.2.1 (UX polish, 13 open).** Issues split sharply into two natures: **CLI-polish** (#67 splash, #72 progressive thinking, #90 rendering constants, #91 tool_result rendering, #92 render_stream state machine, #94 fin do/prompt clarity, #95 /spec, #97 --edit) and **tracing infrastructure** (#106 multi-exporter, #107 OTel LoggerProvider, #108 retry-aware spans, #109 backend connectivity probing, #111 tracing follow-ups). **Resolution: split the milestone.**
  - *Tracing infrastructure (5 issues)* — keep as v0.2.1 or rename to "v0.2.1 — tracing maturation." Independent of platform stance; valid platform work.
  - *CLI polish (8 issues)* — most are made moot by Q3. Concrete dispositions:
    - **Close**: #67 (splash for `fin serve` — Q3 makes this UX, not dev-tool, work), #91 (richer tool_result rendering — same), #94 (`fin do` vs `fin prompt` — Q7 absorbs this; dev REPL needs one entry point, not two), #95 (`/spec` verbose ASCII card — UX-shape), #97 (`--edit` flag for `$EDITOR` — UX-shape).
    - **Defer-to-Q7**: #72 (progressive thinking — *maybe* the dev REPL wants this; defer until Q7 defines the feature line), #90 (rendering constants — only matters if the dev REPL has substantial rendering; defer).
    - **Keep**: #92 (render_stream state machine — pure tech-debt simplification, ships with whatever rendering the dev REPL keeps).
  - The decision frame here is: most CLI polish work was justified by "the CLI is a product surface." Q3 removes that justification.

- **v0.3 (federation + repo-as-package, 3 open).** Issues: #71 (scheduled sentinel), #101 (agent self-evolution), #112 (cost calculation). **Resolution: ships as-scoped, with a note about description drift.** The milestone description is heavy on "federated sub-agents + repo-as-package + eval harness" but the three milestoned issues don't directly enact that vision — they're orthogonal. v0.3 is *undercommitted at the issue level*; the federation story will need its own issues filed when the work begins. This makes v0.3 *more malleable* than v0.1.x for absorbing new work (e.g., ACP-client per Q6c), since the milestone is more theme than concrete commitment. The Q5 working hypothesis ("ACP-server is structurally different from v0.3's A2A-shaped federation") still holds; ACP-client *could* bundle cleanly with v0.3 because both are outbound federation surfaces.

- **Unmilestoned issues that interact with Q1–Q5:** #128 (workspace split — deferred indefinitely per Q4), #130 (DB/S3 object storage — capable infrastructure, independent), #132 (ACP/BFF — Q4 rejects BFF framing on merits; ACP work now happens via Q5 hub-as-server, not decomposition), #133 (Telegram client — moot under Q3, close), #134 (iOS client — moot under Q3, close), #136 (history visualization — Q7 may absorb), #138 (config merge — independent), #139 (MCP tool approval design — natural pair with #153 in the migrated-from-v0.1.2 MCP-client-expansion slot), #146 (`fin pkg` — direction confirmed by Q3, still deferred), #147 (planning agent — independent), #148 (slash-command parameterization — Q7 absorbs), #149 (config language — independent), #151 (MCP discovery caching — pair with #153/#139).

**Resolution:** resolved 2026-05-17 (fourth session). Concrete dispositions captured above. Execution (the actual GitHub mutations: close #133/#134, migrate #153 + #154, restructure or close v0.1.3 + v0.2.1, file the new MCP-client-expansion slot) happens in the dedicated issue-hygiene pass, not during this resolution. Doc captures *intent*; hygiene pass executes.

#### Q6b — Where does ACP-server land?

**Framing:** With Q6a's milestone walk done, the candidate slots for ACP-server are clearer. The Q5 working hypothesis was "new v0.1.4 / v0.2-adjacent slot, not v0.3 federation." Q6a confirms part of that (v0.3 is A2A/federation-themed, ACP-server is structurally different) and opens a new candidate (v0.1.3 is being substantially restructured; the slot itself is becoming available).

**Depends on:** Q5, Q6a.

**Options considered:**

- **Take over v0.1.3.** With #137 likely closing/de-scoping, #143 migratable, #154 migrating to v0.2, the v0.1.3 milestone slot has no anchor. Repurpose it: rename to "v0.1.3 — ACP-server first cut" with #143 (dead-code removal) as a natural pairing (both are "fewer hub-side special cases" work). *Chosen.* This is the cheapest path — the milestone slot already exists, the version number is sequential, and v0.1.3's original "pre-v0.2 foundation work" framing actually *strengthens* under this repurposing: ACP-server validates the protocol-peer architecture before v0.2 builds sub-agent topology on top of it.
- *Insert v0.1.4 as a new slot, leave v0.1.3 as a near-empty close-out.* Possible but adds milestone-list noise for no gain. Rejected.
- *Defer until after v0.2 ships.* Considered briefly. Rejected because the Q5 dogfooding-as-verification argument applies *now*: every additional v0.2 work item built on the unverified protocol-peer assumption deepens the cost if that assumption is wrong. ACP-server is the cheapest way to falsify or confirm it; doing it before v0.2 is correct sequencing.
- *Bundle with v0.3 federation.* Rejected per Q5's analysis — v0.3 is A2A-shaped; ACP-server is structurally different. ACP-*client* is what bundles with v0.3 (see Q6c).

**Resolution:** resolved 2026-05-17 (fourth session) — **repurpose v0.1.3 as the ACP-server first cut**. Scope: first-cut ACP-server (session lifecycle, streaming text, permission round-trip per Q5's scope discipline) + #143 (dead-code removal from hub). Re-scope or close #137 contingent on Q7's dev-REPL feature line. Migrate #154 to v0.2 immediately.

#### Q6c — Where do MCP-server and ACP-client land (speculatively)?

**Framing:** Q2 commits to MCP-server and ACP-client architecturally; Q5 defers their sequencing intentionally so the order can be informed by what ACP-server reveals. Q6c is *not* about scheduling them — it's about whether they get speculative milestone slots now (for visibility / planning) or remain unmilestoned until the work is ready to commit.

**Depends on:** Q2, Q5.

**Options considered:**

- **Stay unmilestoned for now.** *Chosen.* Both surfaces are explicitly waiting for evidence from ACP-server: MCP-server is "deferred until multiple specialist fin agents exist worth delegating to" (Q5); ACP-client is "different motivating evidence will emerge once ACP-server exists" (Q5). Speculatively milestoning them now would either (a) pin a version number that has to move, or (b) signal commitment that the work is going to start soon, when the explicit Q5 stance is that the evidence comes first. Matches the existing hygiene of #128, #146, #128, etc. — durable thinking issues stay unmilestoned until a forcing function fires.
- *Speculative slots (e.g., v0.1.4 = MCP-server, v0.4 = ACP-client + A2A-client federation).* Rejected because Q5 explicitly preserves the optionality of "which evidence emerges first determines which surface lands next." Filing speculative slots collapses that optionality prematurely.
- *Bundle ACP-client with v0.3.* Considered — and architecturally clean (both are outbound federation surfaces). Rejected *for now*: v0.3 is already undercommitted at the issue level (Q6a), and adding ACP-client speculatively to v0.3 would be the second thing v0.3 hasn't enacted yet. Better to let v0.3 enact its existing description first, *then* re-evaluate whether ACP-client folds in.

**Resolution:** resolved 2026-05-17 (fourth session) — **MCP-server and ACP-client remain unmilestoned**, tracked as committed-architecturally-but-unscheduled. New issues for each may be filed during the hygiene pass to make the commitment visible; if so, they explicitly note "no milestone — awaiting evidence from ACP-server." The natural pairings (MCP-server with the migrated-from-v0.1.2 MCP-client-expansion slot; ACP-client with v0.3 federation) are noted as *plausible future homes*, not commitments.

---

### Q7: Dev-REPL feature line (→ §3 Question G)

**Framing:** Q3 resolves the CLI to "hub system ops + dev REPL for testing agent configurations" but doesn't define the dev-REPL's feature line. The risk is drift: without an explicit principle, the REPL accumulates polish PR-by-PR and quietly re-becomes a product surface. The Q6a milestone walk already triaged most of v0.2.1's CLI-polish issues against the (un-formalized) Q3 framing; Q7 makes that triage principled rather than ad-hoc, decides the two issues Q6a deferred (#72, #90), and pins #137's disposition (which Q6a explicitly blocked on Q7).

The dominant decision axis is **scoping principle** — what's the rule that decides whether a candidate CLI feature is in or out. Q1–Q6 already constrain a great deal; Q7 is largely about pinning the principle so it's enforceable rather than interpreted on a per-PR basis.

**Depends on:** Q3, Q6.
**Blocks:** #137 disposition (in the hygiene pass); #72 and #90 disposition (in the v0.2.1 split execution).

**Options considered:**

- **Verification-only.** *Chosen.* The REPL exists to verify that an agent works after `/connect` + config. Anything beyond verification is out. Tight, defensible, and directly downstream of Q3's "minimal test harness" framing. Includes `@`-completion (verifying a context-consuming agent requires injecting context) and positional `fin do <agent> <skill>` grammar (verification is a per-skill operation).
- *Hub-ops + smoke test.* Even tighter — REPL is "does it respond when I ping it" + hub-ops only. Considered but rejected: would force removing `@`-completion, which makes context-consuming agents impossible to test from the CLI. Real test surface, not just polish.
- *Last-resort interactive.* Frame the REPL as "exists for cases where no real client supports the agent type yet." Implies the REPL shrinks over time. Considered but rejected: the trajectory is real (per Q5, ACP-server starts the trend; MCP-server / future A2A clients continue it) but it's a *consequence* of verification-only, not a different principle. Verification-only naturally shrinks the REPL as real clients cover more cases.
- *Test harness + verification (broader).* Includes "verify agent behavior across realistic multi-turn prompts," not just "does it respond." Considered but rejected: this is what a real client is for. Multi-turn behavioral testing is a v0.2 sub-agent / `evals/` story, not a dev-REPL story.

**Sub-resolution: #137 disposition.** Radically re-scope. Keep two pieces of the original #137:

1. **Positional grammar** `fin do <agent> <skill> [prompt]` — verification-shape (test a specific skill on a specific agent).
2. **`entry_prompt` two-turn fix** — the silent `entry_prompt or prompt` discard is a real bug regardless of CLI shape.

Drop the rest: `--workflow` mode flag (no "workflow" concept in a verification REPL), `fin list skills` workflow-mode annotation (annotation is correct but it's now a smaller surface), the elaborate mode-resolution table (no modes to resolve). Update #137's scope in the hygiene pass; the milestone description for the repurposed v0.1.3 reflects "minimal #137" alongside ACP-server first cut and #143.

**Sub-resolution: #72 (progressive thinking) and #90 (rendering constants).** Defer both:

- **#72** — defer to ACP-server work. If ACP-server's streaming-text path handles thinking-token exposure cleanly, the dev REPL inherits the same path or doesn't need its own. If ACP-server reveals a gap, file a follow-up.
- **#90** — defer until v0.2.1 splits and the remaining dev-REPL rendering footprint is concrete. Tech-debt cleanup is worth its cost only if there's enough rendering surface to clean up.

**Sub-resolution: drift-prevention mechanism.** Principle + non-exhaustive examples list, migrated to `decisions.md`. The principle ("REPL exists to verify an agent works after `/connect` + config; anything beyond verification is out") is the rule; the examples list (session switching, splash, rich tool_result rendering, `$EDITOR`, conversation polish) is the calibration. Future PRs that add CLI features get pointed at the principle; if the contributor argues their feature is verification-shape, the discussion happens against a concrete reference rather than vibes.

**Resolution:** resolved 2026-05-17 (fifth session). Q7 is a first cut — ACP-server work is expected to refine it. If implementation reveals the verification-only framing is wrong somewhere, file a follow-up against this resolution rather than re-litigating Q7 wholesale.

---

---

## 5. Recorded thinking

One-paragraph summaries of the prior reasoning in existing issues, so this doc can stand alone.

### #128 — Workspace split: extract fin-protocol and fin-cli-client packages (unmilestoned)

Filed 2026-05-10 as durable thinking, not committed work. Argues that fin-assist is two deliverables (Hub + CLI) separated by A2A, that the hub-CLI firewall is already enforced via `import-linter`, and that the eventual shape is a **uv workspace inside the monorepo** with three packages (`fin-protocol`, `fin-hub`, `fin-cli`) — not a multi-repo split. Explicitly defers extraction until a forcing function fires (second client / remote deployment / third deliverable). Considers and rejects "BFF as a separate product" as *"just an SDK with a worse name."* A 2026-05-10 addendum acknowledges a fourth implicit tier — the shared platform abstractions sitting flat in `src/fin_assist/` — and defers naming it until the forcing function fires.

### #132 — ACP client (Zed integration) as BFF decomposition catalyst (unmilestoned)

Frames Zed/ACP integration as the *decomposition forcing function*, not the goal. *"The primary value isn't the Zed integration itself — it's the decomposition forcing function."* Argues that adding a second client forces the hub API to become genuinely client-agnostic rather than CLI-accidental. **Reasons in the opposite direction from #128 on the BFF question** — the disagreement is unresolved on paper. Open questions in the issue: what does the hub API look like when it's not shaped by CLI REPL patterns? Does A2A already provide enough abstraction, or do we need a client-agnostic layer above it? Does fin expose an ACP endpoint alongside A2A, or does ACP map directly to A2A?

### #146 — Agent package manager (fin pkg) (unmilestoned)

Filed 2026-05-16 as durable design thinking, deferred until v0.2 / v0.3 ship. Vision: `fin pkg install <repo-or-path>`, `fin pkg update`, etc. — cargo/uv/apt semantics for fin primitives. Explicitly distinguishes `uv tool install fin-hub` (platform binary) from `fin pkg install <agent>` (agent installer). *"Two tools, two concerns — same split as helm/kubectl or cargo/rustup."* Endorses splitting management CLI from conversational client by implication. Names #132/#133/#134 (clients) as downstream consumers — *"once a package manager exists, those become 'install fin-cli-telegram from github.com/x/y' rather than bespoke per-client integration work."*

---

## 6. Working notes

Dated scratch space. Most recent entries on top.

### 2026-05-17 (fifth session) — Q7 resolved (dev-REPL feature line)

Worked through Q7 in one session, framing-only as agreed at the start. The session opener acknowledged the Q5/Q7 chicken-and-egg: Q5 explicitly named ACP-server as the forcing function for Q7, but Q6a deferred #137's disposition to Q7, which the hygiene pass needs. Resolution: Q7 is a first cut, refinable when ACP-server work surfaces new information. The principle is committed; the calibration list is committed; revisits happen as follow-ups against the resolution, not as full Q7 re-litigation.

Three sub-decisions resolved together:

1. **Principle: verification-only.** REPL exists to verify an agent works after `/connect` + config. Tight, downstream of Q3's "minimal test harness" framing. Considered three alternatives (hub-ops + smoke test, last-resort interactive, broader test harness) and rejected each — verification-only is the right scoping rule because it both excludes the right things (product polish, conversation management) and *includes* the right things (`@`-completion for context-consuming agents, positional grammar for per-skill verification).

2. **#137 radically re-scopes.** Keep positional `fin do <agent> <skill> [prompt]` grammar (verification-shape) and the `entry_prompt` two-turn fix (genuine bug). Drop everything else: `--workflow` mode flag (no "workflow" concept in a verification REPL), the elaborate mode-resolution table, the `fin list skills` annotation rework. The repurposed v0.1.3 milestone description (set in the hygiene pass) will reflect "minimal #137" as a third anchor alongside ACP-server first cut and #143.

3. **Drift prevention: principle + non-exhaustive examples list.** When `platform-stance.md` migrates to `decisions.md`, the verification-only principle ships with a concrete examples list (session switching, splash, rich tool_result rendering, `$EDITOR`, etc.) so future contributors have something specific to point at. Principle is the rule; examples are the calibration.

Q6a's two deferred-to-Q7 items resolved cleanly:

- **#72 (progressive thinking)** — defer to ACP-server work. If ACP-server's streaming-text path handles thinking-token exposure, the dev REPL inherits it; if not, file a follow-up. The verification-only principle doesn't take a strong position on thinking-token rendering — it depends on whether ACP-server's path is sufficient.
- **#90 (rendering constants)** — defer until v0.2.1 splits and the remaining dev-REPL rendering footprint is concrete. Tech-debt cleanup is worth its cost only if there's enough rendering surface left after Q7 prunes.

A meta-observation worth recording: Q7's framing was easier than expected because Q1–Q6 already constrained so much. The session was 90% "make the principle explicit and pin two deferred items" and 10% genuinely-open decision. This is the right shape for late-stage decision work — the load-bearing questions get debated upstream; the downstream questions become consequences of upstream resolutions, with shrinking optionality. If a downstream question feels hard, that's evidence an upstream question got framed wrong, not evidence the downstream question is bad.

The next phase (issue-hygiene pass) is now fully unblocked. All Q6 enumerated mutations now have concrete dispositions including #137. After the hygiene pass, the doc-migration phase retires this file. Then dev work resumes — starting milestone deferred to end-of-hygiene-pass session per the agreed sequencing.

### 2026-05-17 (fourth session) — Q6 resolved (holistic roadmap reconciliation)

Worked through Q6 in one session, using the Q6a/Q6b/Q6c decomposition agreed at the start. Cole's framing for Q6 was explicit: *"I really want to take a holistic decomposition view, meaning we need to consider how the decisions and context in `docs/platform-stance.md` impacts currently planned work, not just which milestone they fit into in isolation."*

The session started with a fresh `gh` pull of all open milestones and unmilestoned issues — and that was load-bearing. §1.5's milestone summary turned out to be stale or wrong in at least two places:

- v0.1.1 was described as "independent of this decision" but contains #124 (`/connect`), #135 (CLI dogfooding), #156 (per-subcommand approval) — all CLI-shape work. Under Q3 these are still valid (dev-REPL responsibilities) but it's not accurate to call the milestone independent.
- v0.1.2 was described as "README badges + demo" but actually contains #153 — MCPContextProvider for outbound MCP-client resources. That's substantive protocol work and does not belong in a marketing milestone.

The big resolutions, in the order they settled:

1. **#133 / #134 (Telegram, iOS clients) are moot under Q3.** Easy close in the hygiene pass. Q3's "no other clients planned" stance directly invalidates them.
2. **v0.1.3 has no anchor anymore.** #137's CLI-grammar scope evaporates under Q3; #143 is portable; #154 is foundation for v0.2. The slot itself is available.
3. **ACP-server takes over v0.1.3.** Cheapest path — slot exists, version number is sequential, the "pre-v0.2 foundation work" framing strengthens under repurposing (validate the protocol-peer architecture *before* v0.2 builds sub-agent topology on top of it).
4. **v0.2.1 splits.** The CLI-polish vs tracing-infrastructure dual nature became impossible to ignore once mapped onto Q3. Most CLI-polish work was justified by "CLI is a product surface"; Q3 removes that justification. Tracing infrastructure is independent.
5. **MCP-server and ACP-client stay unmilestoned.** Q5 explicitly preserved optionality on which surface lands second; speculatively milestoning them would burn that. Matches existing hygiene (#128, #146 — durable thinking without milestones).

Two structural observations worth recording for future sessions:

- **#140 (second AgentBackend) is the structural sibling of Q5's argument.** The issue body explicitly names itself "validate protocol shape." ACP-server validates the *inbound* protocol claim; #140 validates the *outbound* model claim. Same shape, different layer. v0.2 already contains one protocol-shape-validation exercise; Q5 adds a second at a different layer. Neither displaces the other.
- **v0.3 is more malleable than v0.1.x.** Three milestoned issues vs a heavy "federation + repo-as-package" description means v0.3 is theme-without-commitment. ACP-client *could* land there cleanly (per Q6c) once evidence emerges, because v0.3 hasn't enacted its existing description yet.

Q7 (dev-REPL feature line) is now the only open question. It's also now the gating question for whether #137 closes or radically re-scopes (Q6a flagged this dependency explicitly).

The issue-hygiene pass is unblocked. Execution candidates: close #133/#134, migrate #153 (and pair with #139/#151) to a new MCP-client-expansion slot, migrate #154 to v0.2, repurpose v0.1.3 around ACP-server + #143, split v0.2.1 (close #67/#91/#94/#95/#97; defer #72/#90; keep #92), file new issue for ACP-server work, update #128 / #132 / #146 with the Q4 and Q3 resolutions, update v0.1.2 description to remove the MCP work that's migrating out.

### 2026-05-17 (third session) — Q5 resolved (ACP-server first)

Worked through Q5 in one session. The initial framing I proposed (ACP-client first, on a personal-tool-composition argument) was corrected by Cole mid-session: the real dogfooding gap isn't *"what can fin do that I can't already do manually"* — it's *"do we even know fin works as a platform?"* That reframe flipped the answer.

The corrected framing: the Q4 resolution (new inbound consumers are protocol peers, not BFF clients) is currently *unfalsified*. Until a non-fin client drives the hub through a standardized protocol surface, Q4 is asserted rather than verified. ACP-server is the smallest realistic surface that produces this verification — it's the first inbound consumer whose shape, transport, and UX are not under fin's control.

Key clarifications during the session:

- "Highest user-facing visibility" was the wrong frame for ACP-server. The right frame is "richest external integration point available today, therefore the strongest test of the platform claim." That's a dogfooding argument, not a reach argument.
- ACP-client (composing external CLI agents into fin workflows) is a *capability* argument, not a *platform-verification* argument. Capability matters but it doesn't test what Q4 claimed.
- MCP-server (opencode-as-host, Claude-Desktop-as-host) is a "fin agents as someone else's tools" loop. Strong in principle, thin in practice until multiple specialist fin agents exist worth delegating to.
- Cole doesn't have to switch editors (Helix is daily-driver) to dogfood ACP-server. Zed-as-test-client is sufficient; the dogfooding loop is "open Zed, drive fin, find what breaks."
- Bundling ACP-client with v0.3 A2A federation still makes sense in principle (per session 2), but that's a downstream decision now that Q5 picks a different surface first.

Open follow-ons unchanged: Q6 (milestone placement, especially with ACP-server now in the picture) and Q7 (dev-REPL feature line, which ACP-server's existence will help define). The Q6 working hypothesis added to §3 Question E: ACP-server likely deserves its own milestone slot, not v0.3 federation, because v0.3 federation is A2A-shaped and ACP-server is structurally different. Q6 confirms or rejects.

Order of MCP-server and ACP-client (both deferred) intentionally left open — different motivating evidence will emerge once ACP-server exists, and pinning the order now would burn that information.

Issue-hygiene pass still deferred — now blocked on Q6 explicitly (was implicitly blocked on Q5+Q6 before). Candidates unchanged from session 2 plus: new issue likely needed for ACP-server work itself (filed as part of the hygiene pass, not during Q5/Q6 resolution).

### 2026-05-17 (second session) — §3 and §4 resolved (Q1–Q4)

Worked through the decision frame in one session. The shape that emerged is "harmonize, don't decompose": rather than splitting the repo or growing a BFF layer, fold the CLI's role inward (dev tool only) and grow outward through standardized protocol surfaces on the hub. Three new surfaces committed (MCP-server, ACP-server, ACP-client) plus the existing A2A-server / MCP-client / planned A2A-client.

Key clarifications that landed during the session:

- The (a)/(b) integration-direction framing dissolved when mapped to protocol roles — inbound vs outbound are independent vectors, not a sequencing decision.
- A2A, MCP, ACP are sibling protocols at different layers (agent↔agent, agent↔tool, client↔agent), not substitutes. The "do they overlap?" intuition was checked explicitly and the answer is no — each shapes a different consumer's mental model.
- ACP-client is bundled with ACP-server architecturally because the cost is largely shared and ACP-client is what makes "compose external ACP agents into fin" tractable without forcing each external agent to grow an A2A face.
- #132's BFF framing is rejected on the merits, not just deferred. The protocol *is* the boundary; new inbound consumers are protocol peers, not BFF clients.

Three meta-questions from session 1 are now resolved or absorbed:

- Question D placement: kept in this doc as Q4 because the resolution is genuinely architectural; the *update to #128* is the follow-up action (Q6 / issue hygiene pass), not the resolution itself.
- (a)/(b) framing: thrown out, replaced by inbound/outbound protocol-role decomposition.
- ACP-server vs ACP-client: treated as separate options under Q2 with the explicit decision to bundle them architecturally despite being separable.

Surfaced for next session (Q5/Q6/Q7):

- **Sequencing.** Which new surface ships first? MCP-server has the smallest cost (reuses MCP library already in tree); ACP-server has the highest user-facing visibility; ACP-client unlocks composition of existing ACP agents. No commitment yet.
- **v0.1.3 fate.** With CLI demoted to dev tool, #137 (CLI grammar v2) loses most of its scope. #143 and #154 are independent. Whether v0.1.3 ships as-is, folds into v0.1.2, or restructures around Q5 is open.
- **Dev-REPL feature line.** Q3 doesn't define what "minimal dev REPL" excludes. Worth pinning down so the REPL doesn't re-grow into a product surface by drift.

Issue hygiene deferred to a separate session per the framing-vs-resolution discipline in `AGENTS.md`. When that session happens, candidates are: #128 (workspace split deferred indefinitely, not "until forcing function"), #132 (BFF rejected on the merits; ACP integration happens via hub-as-server), #146 (pkg manager direction confirmed), #137 (likely de-scope or close), and possibly a new issue for the dev-REPL scope (Q7).

### 2026-05-17 — doc seeded

First commit: skeleton, context, ecosystem snapshot. Decision frame and open questions stubbed but not populated. Next session: populate §3 with the actual questions and their framings (intentionally deferred to keep AI-assisted framing from fossilizing before the human reasons through it).
