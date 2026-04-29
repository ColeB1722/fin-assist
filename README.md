# fin-assist

Expandable personal AI agent platform for terminal workflows. An **Agent Hub** hosts N specialized agents over the [A2A protocol](https://google.github.io/A2A/) — clients dynamically adapt their UI based on each agent's declared capabilities. Shared agentic capabilities (tools, approval, context, tracing) are framework-agnostic platform abstractions; LLM frameworks plug in via backend implementations.

## Architecture

Diagrams progress from external view → hub internals → backend wiring → per-request sequence. The Mermaid blocks below are canonical; `just diagrams` renders them to `docs/diagrams/*.svg` (+ `*.png`) for offline viewing.

### 1. System Context

Who talks to what.

<!-- diagram:01-system-context -->
```mermaid
graph LR
    User(("User"))

    subgraph Clients
        CLI["CLI Client<br/>Rich · a2a-sdk ClientFactory"]
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
    DISC["GET /agents · GET /health<br/>(hub-level discovery)"]

    subgraph HUB_PROC["Agent Hub (FastAPI, 127.0.0.1:4096)"]
        HUB["Hub Router<br/>mount table:<br/>· /agents/test/<br/>· /agents/{name}/ (from config)"]

        subgraph SUBAPP["Per-Agent A2A Sub-App · one instance per enabled agent"]
            direction TB
            DRH["DefaultRequestHandler<br/>(a2a-sdk)<br/>JSON-RPC dispatch for this agent"]
            EXEC["Executor<br/>AgentExecutor + TaskUpdater<br/>wraps this agent's PydanticAIBackend"]
            TS["InMemoryTaskStore<br/>ephemeral · this sub-app only"]
        end

        CS["ContextStore<br/>SQLite · opaque bytes<br/>single instance, shared across sub-apps"]

        FACTORY["AgentFactory<br/>AgentSpec → sub-app<br/>+ AgentCard (w/ fin_assist:meta ext)"]
    end

    BACKEND["Backend Layer<br/>(see §3)"]

    IN --> HUB
    HUB -->|"dispatches to matching sub-app"| DRH
    DRH --> EXEC
    DRH <--> TS
    EXEC -->|"shared store · keyed by context_id"| CS
    EXEC -->|"delegates LLM work"| BACKEND

    FACTORY -.->|"builds at startup<br/>(N instances)"| SUBAPP
    FACTORY -.->|"publishes cards"| DISC

    classDef external fill:#f5f5f5,stroke:#999,stroke-dasharray: 3 3
    class IN,BACKEND,DISC external
    classDef startup fill:#fafafa,stroke:#bbb,stroke-dasharray: 4 3
    class FACTORY startup
    classDef shared fill:#f0f7ff,stroke:#4a7fb0,stroke-width:2px
    class CS shared
```

### 3. Backend Layer & Shared Services

How the Executor reaches the LLM and what cross-cutting services it leans on.

<!-- diagram:03-backend-services -->
```mermaid
graph TD
    EXEC["Executor<br/>(from hub)"]

    subgraph BACKEND_GRP["Backend Layer"]
        BEH["«protocol» AgentBackend"]
        PAI["PydanticAIBackend<br/>pydantic-ai Agent · FallbackModel"]
        SH["StreamHandle<br/>async iter (deltas) + result()"]
        MCE["MissingCredentialsError<br/>raised when API key absent"]
    end

    subgraph SPEC_GRP["Agent Specification"]
        SPEC["AgentSpec<br/>pure config · zero framework deps"]
    end

    subgraph SHARED["Shared Services"]
        CREDS["CredentialStore<br/>env → file → keyring"]
        CONFIG["ConfigLoader<br/>TOML + env (FIN_*)<br/>pydantic-settings"]
        REG["ProviderRegistry<br/>LLM providers · api_key injected"]
    end

    LLM["LLM Providers<br/>Anthropic · OpenAI · OpenRouter · Google"]

    EXEC --> BEH
    BEH -.->|"implemented by"| PAI
    PAI --> SH
    PAI -->|"create_model(provider, api_key)"| REG
    REG --> LLM
    PAI --> SPEC
    PAI -.->|"raises on missing key"| MCE
    SPEC -->|"get_api_key(provider)"| CREDS
    SPEC --> CONFIG

    classDef external fill:#f5f5f5,stroke:#999,stroke-dasharray: 3 3
    class EXEC,LLM external
    classDef error fill:#fff3f3,stroke:#c66
    class MCE error
```

### 4. Request Flow

End-to-end sequence of a single `SendStreamingMessage` call.

<!-- diagram:04-request-flow -->
```mermaid
sequenceDiagram
    participant C as CLI Client
    participant H as Agent Hub<br/>(sub-app + DefaultRequestHandler)
    participant E as Executor
    participant B as AgentBackend<br/>(PydanticAIBackend)
    participant SH as StreamHandle
    participant CS as ContextStore
    participant LLM as LLM Provider

    C->>H: SendStreamingMessage (JSON-RPC + SSE)
    H->>E: execute(context, event_queue)
    E->>E: Task enqueued (SUBMITTED)
    E->>E: updater.start_work() → WORKING

    E->>B: check_credentials()
    B-->>E: [] or [missing providers]

    alt Credentials missing
        Note over E,B: raises MissingCredentialsError
        E->>E: updater.requires_auth() → AUTH_REQUIRED
        H-->>C: SSE: TaskStatusUpdateEvent (auth_required)
    else Credentials present
        E->>CS: load(context_id)
        CS-->>E: bytes or None
        E->>B: deserialize_history(bytes)
        B-->>E: message_history (prior turns)

        E->>B: convert_history([current_message])
        B-->>E: framework messages (this turn)

        E->>B: run_stream(messages=history)
        B-->>E: StreamHandle
        Note over B,LLM: backend holds LLM connection

        loop Token-by-token
            SH-->>E: text delta (async iter)
            E->>H: updater.add_artifact(append=true, last_chunk=false)
            H-->>C: SSE: TaskArtifactUpdateEvent
        end

        E->>H: updater.add_artifact("", last_chunk=true)
        H-->>C: SSE: TaskArtifactUpdateEvent (last_chunk=true)

        alt Exception during stream
            E->>E: updater.failed() → FAILED
            H-->>C: SSE: TaskStatusUpdateEvent (failed)
        end

        E->>SH: await result()
        SH-->>E: RunResult (output, serialized_history, new_message_parts)

        E->>CS: save(context_id, serialized_history)

        loop new_message_parts (thinking blocks, etc.)
            E->>H: updater.update_status(WORKING, message=part)
            H-->>C: SSE: TaskStatusUpdateEvent (WORKING + message)
        end

        alt Structured output (non-str)
            E->>B: convert_result_to_part(output)
            B-->>E: Part (data + json_schema metadata)
            E->>H: updater.add_artifact(structured, new artifact_id)
            H-->>C: SSE: TaskArtifactUpdateEvent (structured)
        end

        E->>E: updater.complete() → COMPLETED
        H-->>C: SSE: TaskStatusUpdateEvent (completed)
    end
```

## Key Concepts

| Concept | Implementation |
|---------|---------------|
| **Config-driven agents** | Agent behavior (prompt, output type, thinking, approval, tools) defined in TOML — new agents are config entries, not new classes |
| **Platform owns abstractions** | Tools, approval, context, step events, and tracing are framework-agnostic platform types; backends adapt them to their LLM framework |
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
fin-assist do --agent test "prompt"     One-shot query (named agent)
fin-assist do                           Open input panel (default agent)
fin-assist do --edit "prompt"           Open input panel pre-filled with prompt
fin-assist talk                         Multi-turn session (default agent)
fin-assist talk --agent test            Multi-turn session (named agent)
fin-assist list tools                   List registered tools
fin-assist list prompts                 List registered system prompts
fin-assist list output-types            List registered output types
```

Context injection via `@`-completion in the input panel: `@file:path.py`, `@git:diff`, `@git:log`, `@history:query`.

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1–8b | Repo setup → CLI REPL | Done |
| 9 | Streaming + integration tests | Done |
| Config redesign | Config-driven agents, `AgentSpec` pure config | Done |
| a2a-sdk migration | fasta2a → a2a-sdk v1.0, FastAPI, streaming | Done |
| Executor + Tools + HITL | Multi-step executor, tool calling, approval (PR #87) | Done |
| Remove built-in agents | Pure infrastructure; all agents from config.toml | Done |
| Input panel + `--edit` | Interactive `fin do`, `--edit` flag, `--agent` flag | Done |
| `@`-completion | Inline context injection (`@file:`, `@git:`, `@history:`) | Done |
| `fin list` | CLI capabilities listing (tools, prompts, output-types) | Done |
| Observability | OTel tracing (hub + CLI), OpenInference/Phoenix bridge, JSONL span sink, HITL trace continuity | Done |
| 11 | Multiplexer (tmux/zellij) | Planned |
| 13 | TUI client (Textual) | Planned |
| 15 | Skills + MCP Integration | Planned |
| 16 | Additional agents (SDD, TDD) | Planned |
| 17 | Multi-agent workflows | Planned |

See [docs/architecture.md](docs/architecture.md) for full architecture, design decisions, and implementation details.
