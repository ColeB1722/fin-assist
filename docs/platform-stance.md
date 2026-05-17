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

*This section will be filled in subsequent commits. It contains the questions, not the answers.*

Placeholder structure (to be elaborated next):

- **Question A: Integration direction.** Is fin primarily infrastructure that other systems integrate into, or an orchestrator that composes other systems? (Both, in some sequence — what sequence?)
- **Question B: Protocol surfaces to expose.** Which of ACP-server, MCP-server, ACP-client, others do we add, in what order?
- **Question C: CLI stance.** Reference client (dev tool), first-class product (status quo), or removed entirely?
- **Question D: Workspace split timing.** Does the answer to A/B/C make #128 more urgent, less urgent, or unchanged?

---

## 4. Open questions, decomposed

*To be populated as we work through the decision frame. Each question gets an internal ID, a one-paragraph framing, options if applicable, and a resolution line once it lands.*

Question format:

```
### Q<n>: <short name>

**Framing:** <1-2 paragraphs on what the question is>
**Depends on:** <other Q-IDs that block this one>
**Blocks:** <other Q-IDs this one blocks>
**Options under consideration:** <enumerated>
**Resolution:** <pending / resolved <date> — see <pointer>>
```

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

### 2026-05-17 — doc seeded

First commit: skeleton, context, ecosystem snapshot. Decision frame and open questions stubbed but not populated. Next session: populate §3 with the actual questions and their framings (intentionally deferred to keep AI-assisted framing from fossilizing before the human reasons through it).

Three meta-questions to revisit when §3 is being filled in:

- Should Question D (workspace split timing) be part of this doc at all, or does it belong as a comment on #128 once A/B/C resolve? Lean: keep it here as the *integration point* with the existing record, but make it explicit that the *resolution* updates #128 rather than living in this doc.
- The (a)/(b) integration-direction framing surfaced in conversation may not be the right axis once we write out the actual options. It came from a single back-and-forth; we should be willing to throw it out if a better decomposition emerges.
- ACP-server vs ACP-client are described together in §1.2 but they are independent decisions with different cost profiles. §3 should treat them as separate options, not bundled.
