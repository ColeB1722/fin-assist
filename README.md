# fin-assist

Expandable personal AI agent platform for terminal workflows. An **Agent Hub** hosts N specialized agents over the [A2A protocol](https://google.github.io/A2A/) — clients dynamically adapt their UI based on each agent's declared capabilities.

## System Architecture

```mermaid
graph TD
    subgraph Clients
        CLI["CLI Client<br/><small>Rich + httpx + prompt-toolkit</small>"]
        TUI["TUI Client <em>(planned)</em><br/><small>Textual</small>"]
    end

    subgraph "A2A Protocol — HTTP + JSON-RPC"
        RPC["SendMessage · SendStreamingMessage (SSE)<br/><small>Agent discovery via Agent Cards</small>"]
    end

    subgraph "Agent Hub — FastAPI on 127.0.0.1:4096"
        HUB["Hub Router<br/><small>GET /agents · GET /health</small>"]

        subgraph "Per-Agent A2A Sub-Apps"
            D["/default/<br/><small>do + talk · chain-of-thought</small>"]
            S["/shell/<br/><small>do only · approval gate</small>"]
            F["/{name}/<br/><small>future agents</small>"]
        end

        EXEC["FinAssistExecutor<br/><small>AgentExecutor + TaskUpdater</small>"]
        TS["InMemoryTaskStore<br/><small>ephemeral (a2a-sdk)</small>"]
        CS["ContextStore<br/><small>SQLite — conversation history</small>"]
    end

    subgraph "Shared Services"
        CREDS["CredentialStore<br/><small>env → file → keyring</small>"]
        CONFIG["ConfigLoader<br/><small>TOML · 4-level priority</small>"]
        CTXP["ContextProviders<br/><small>files · git · history · env</small>"]
        REG["ProviderRegistry<br/><small>LLM providers</small>"]
    end

    LLM["pydantic-ai → LLM Providers"]

    CLI --> RPC
    TUI --> RPC
    RPC --> HUB
    HUB --> D & S & F
    D & S & F --> EXEC
    EXEC --> LLM
    EXEC --> TS & CS
    LLM --> CREDS & REG
    EXEC --> CTXP
    HUB -.-> CONFIG
```

## Request Flow

```mermaid
sequenceDiagram
    participant C as CLI Client
    participant H as Agent Hub
    participant E as FinAssistExecutor
    participant L as pydantic-ai / LLM

    C->>H: SendStreamingMessage (JSON-RPC + SSE)
    H->>E: execute(context, task_updater)
    E->>E: Task enqueued (SUBMITTED)
    E->>E: updater.start_work() → WORKING
    E->>L: agent.run_stream(prompt, context)
    loop Token-by-token
        L-->>E: text delta
        E-->>H: updater.add_artifact(append=true)
        H-->>C: SSE: TaskArtifactUpdateEvent
    end
    E->>E: updater.complete() → COMPLETED
    H-->>C: SSE: TaskStatusUpdateEvent (last_chunk=true)
```

## Key Concepts

| Concept | Implementation |
|---------|---------------|
| **Config-driven agents** | Agent behavior (prompt, output type, thinking, approval) defined in TOML — new agents are config entries, not new classes |
| **Protocol-native** | A2A via a2a-sdk v1.0; any A2A client can connect; enables future agent-to-agent workflows |
| **Multi-path routing** | N agents → N A2A sub-apps at `/agents/{name}/`, each with its own agent card |
| **Token-by-token streaming** | `SendStreamingMessage` SSE → `TaskUpdater.add_artifact(append=True)` → Rich `Live` rendering |
| **Metadata-driven UI** | Static capabilities in `AgentExtension` on agent card; dynamic hints per-response in artifact metadata |
| **Local-first** | Binds `127.0.0.1` only; no network exposure by default |

## CLI Usage

```
fin-assist serve                        Start agent hub
fin-assist agents                       List available agents
fin-assist do "prompt"                  One-shot query (default agent)
fin-assist do shell "list large files"  One-shot query (shell agent)
fin-assist talk                         Multi-turn session (default agent)
fin-assist talk shell                   Multi-turn session (shell agent)
```

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1–7 | Repo setup → Hub server | Done |
| 8 | CLI client + REPL | Done |
| 9 | Streaming + integration tests | In progress |
| Config redesign | Config-driven agents, single `ConfigAgent` class | Done |
| a2a-sdk migration | fasta2a → a2a-sdk v1.0, FastAPI, streaming | Done |
| 11 | Multiplexer (tmux/zellij) | Planned |
| 13 | TUI client (Textual) | Planned |
| 16 | Additional agents (SDD, TDD) | Planned |
| 17 | Multi-agent workflows | Planned |

See [docs/architecture.md](docs/architecture.md) for full architecture, design decisions, and implementation details.
