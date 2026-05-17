# Platform Stance

**Status:** in-progress decision (started 2026-05-17).
**Owner:** Cole, with AI-assisted synthesis.
**Lifecycle:** this doc is *not* a forever-doc. Once the decisions below resolve, durable claims migrate to [`architecture.md`](architecture.md) and [`decisions.md`](decisions.md), and this file is either deleted or compressed to a one-paragraph historical pointer. While in progress, it is the single source of truth for the reasoning; once resolved, it should not be.

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

---

## 4. Open questions, decomposed

Q1–Q4 map one-to-one onto §3 Questions A–D and carry the options that were considered, including the ones not chosen, so the reasoning trail survives. Q5+ are the downstream questions surfaced by the resolutions and remain genuinely open.

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

### Q6: v0.1.3 fate — what does "CLI grammar v2" mean if the CLI is a dev tool, and where does ACP-server land?

**Framing:** v0.1.3 currently contains #137 (CLI grammar v2), #143 (dead-code removal from hub), and #154 (async cascade). Q3's resolution (CLI as dev tool only) significantly drops the urgency of #137 — there's much less surface area to grammar-define. #143 still applies (dead-code removal from hub is independent of CLI shape). #154 also independent. Q5's resolution (ACP-server first) adds a second dimension: ACP-server needs a milestone window. The Q5 working hypothesis is that ACP-server likely deserves its own slot (not v0.3 federation, which is A2A-shaped), but the placement is not yet resolved.
**Depends on:** Q3, Q5.
**Blocks:** issue hygiene pass.
**Options under consideration:** to be enumerated in a follow-up session. Candidates include: ship v0.1.3 as-is with #137 de-scoped; fold #143/#154 into v0.1.2 and close v0.1.3; restructure v0.1.3 around ACP-server (treat the dev-REPL grammar work as part of the larger "what the dev REPL is" question Q7 surfaces); or insert ACP-server as a new v0.1.4 / v0.2-adjacent slot independent of the existing v0.1.3 contents.
**Resolution:** pending.

### Q7: What "dev REPL" actually means in scope

**Framing:** Q3 resolves the CLI to "hub system ops + dev REPL for testing agent configurations" but doesn't define the dev-REPL's feature line. Current REPL has `@file:` / `@git:` / `@history:` / `@env:` completion, prompt-toolkit session, Rich rendering, slash-command system. Some of that is "essential to verifying an agent works" (basic A2A round-trip, slash commands like `/connect`, `/agents`), some is "polish that arguably belongs in a real client" (multi-line edit, completion menus). A clear feature line keeps the dev-REPL from re-acquiring "product" characteristics by drift.
**Depends on:** Q3.
**Blocks:** none directly, but informs which CLI improvements are worth filing as issues.
**Options under consideration:** to be enumerated in a follow-up session.
**Resolution:** pending.

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
