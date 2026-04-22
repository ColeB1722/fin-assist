# fin-assist

Expandable personal AI agent platform for terminal workflows. An **Agent Hub** hosts N specialized agents over the [A2A protocol](https://google.github.io/A2A/) — clients dynamically adapt their UI based on each agent's declared capabilities.

## Architecture

Diagrams progress from external view → hub internals → backend wiring → per-request sequence. The Mermaid blocks below are canonical; `just diagrams` renders them to `docs/diagrams/*.svg` (+ `*.png`) for offline viewing.

### 1. System Context

Who talks to what.

<!-- diagram:01-system-context -->
```mermaid
graph LR
    User(("User"))

    subgraph Clients
        CLI["CLI Client<br/>Rich + httpx"]
        TUI["TUI Client<br/>(planned)"]
    end

    HUB["Agent Hub<br/>FastAPI · 127.0.0.1:4096<br/>A2A protocol"]

    LLM["LLM Providers<br/>Anthropic · OpenAI<br/>OpenRouter · Google"]

    User --> CLI
    User --> TUI
    CLI -->|"JSON-RPC + SSE"| HUB
    TUI -->|"JSON-RPC + SSE"| HUB
    HUB -->|"HTTPS"| LLM

    classDef planned stroke-dasharray: 5 5
    class TUI planned
```

### 2. Hub Internals

Routing, per-agent sub-apps, and the Executor/stores inside the hub process.

<!-- diagram:02-hub-internals -->
```mermaid
graph TD
    IN["A2A request<br/>(from client)"]

    subgraph HUB_PROC["Agent Hub (FastAPI, 127.0.0.1:4096)"]
        HUB["Hub Router<br/>GET /agents · GET /health"]
        FACTORY["AgentFactory<br/>AgentSpec → FastAPI sub-app"]

        subgraph "Per-Agent A2A Sub-Apps"
            D["/default/<br/>do + talk · chain-of-thought"]
            S["/shell/<br/>do only · approval gate"]
            F["/{name}/<br/>future agents"]
        end

        EXEC["Executor<br/>AgentExecutor + TaskUpdater"]
        TS["InMemoryTaskStore<br/>ephemeral (a2a-sdk)"]
        CS["ContextStore<br/>SQLite — opaque bytes"]
    end

    BACKEND["Backend Layer<br/>(see §3)"]

    IN --> HUB
    HUB --> FACTORY
    FACTORY --> D & S & F
    D & S & F --> EXEC
    EXEC --> TS
    EXEC --> CS
    EXEC -->|"delegates LLM work"| BACKEND

    classDef external fill:#f5f5f5,stroke:#999,stroke-dasharray: 3 3
    class IN,BACKEND external
```

### 3. Backend Layer & Shared Services

How the Executor reaches the LLM and what cross-cutting services it leans on.

<!-- diagram:03-backend-services -->
```mermaid
graph TD
    EXEC["Executor<br/>(from hub)"]

    subgraph "Backend Layer"
        BEH["«protocol» AgentBackend"]
        PAI["PydanticAIBackend<br/>pydantic-ai Agent · FallbackModel"]
        SH["StreamHandle<br/>async iter (deltas) + result()"]
    end

    subgraph "Agent Specification"
        SPEC["AgentSpec<br/>pure config · zero framework deps"]
    end

    subgraph "Shared Services"
        CREDS["CredentialStore<br/>env → file → keyring"]
        CONFIG["ConfigLoader<br/>TOML · 4-level priority"]
        CTXP["ContextProviders<br/>files · git · history · env"]
        REG["ProviderRegistry<br/>LLM providers"]
    end

    LLM["LLM Providers<br/>Anthropic · OpenAI · OpenRouter · Google"]

    EXEC --> BEH
    BEH -.->|"implemented by"| PAI
    PAI --> SH
    PAI --> REG
    PAI --> LLM
    PAI --> SPEC
    EXEC --> CTXP
    SPEC --> CREDS
    SPEC --> CONFIG
    REG --> CREDS

    classDef external fill:#f5f5f5,stroke:#999,stroke-dasharray: 3 3
    class EXEC,LLM external
```

### 4. Request Flow

End-to-end sequence of a single `SendStreamingMessage` call.

<!-- diagram:04-request-flow -->
```mermaid
sequenceDiagram
    participant C as CLI Client
    participant H as Agent Hub
    participant E as Executor
    participant B as AgentBackend
    participant SH as StreamHandle
    participant CS as ContextStore
    participant LLM as LLM Provider

    C->>H: SendStreamingMessage (JSON-RPC + SSE)
    H->>E: execute(context, event_queue)
    E->>E: Task enqueued (SUBMITTED)
    E->>E: updater.start_work() → WORKING

    E->>B: check_credentials()
    B-->>E: [] (all present) or missing providers

    alt Credentials missing
        E->>E: updater.requires_auth() → AUTH_REQUIRED
        H-->>C: SSE: TaskStatusUpdateEvent (auth_required)
    else Credentials present
        E->>CS: load(context_id)
        CS-->>E: bytes or None
        E->>B: deserialize_history(bytes)
        B-->>E: message_history

        E->>B: convert_history(a2a_messages)
        B-->>E: framework messages

        E->>B: run_stream(messages, model)
        B-->>E: StreamHandle

        loop Token-by-token
            E->>SH: async for delta
            SH-->>E: text delta
            E->>H: updater.add_artifact(append=true)
            H-->>C: SSE: TaskArtifactUpdateEvent
        end

        E->>SH: await result()
        SH-->>E: RunResult (output, serialized_history, new_message_parts)

        E->>CS: save(context_id, serialized_history)

        alt Structured output (non-str)
            E->>B: convert_result_to_part(output)
            B-->>E: Part (data + json_schema)
            E->>H: updater.add_artifact(structured)
            H-->>C: SSE: TaskArtifactUpdateEvent (structured)
        end

        E->>E: updater.complete() → COMPLETED
        H-->>C: SSE: TaskStatusUpdateEvent (last_chunk=true)
    end
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
