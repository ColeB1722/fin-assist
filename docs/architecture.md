# fin-assist Architecture

## Overview

fin-assist is an **expandable personal AI agent platform** for terminal workflows. It provides an **Agent Hub** — a server that hosts N specialized agents over the A2A protocol — and multiple client interfaces (CLI, TUI, future web) that dynamically adapt their UI based on each agent's declared capabilities.

### Core Vision

**Agent Hub** — A "turnstile" of specialized agents exposed via A2A protocol (a2a-sdk v1.0). Each agent is independently discoverable, has its own agent card, and can be swapped in/out of the server. The hub handles routing, conversation persistence, and agent lifecycle.

**Dynamic UI via Agent Metadata** — Clients adapt their interface based on agent capabilities. Static metadata (multi-turn, thinking support, model selection) is declared in the A2A agent card via `AgentExtension`. Dynamic metadata (accept actions, rendering hints) is returned per-response in task artifacts. Clients don't need to know about specific agents — they read metadata and adapt.

**Protocol-Native** — Built on A2A (Agent-to-Agent) protocol via a2a-sdk v1.0 (Google's official Python SDK). Any A2A-compatible client can communicate with the hub. This enables future agent-to-agent workflows (e.g., SDD agent handing off to TDD agent).

**CLI-First, TUI-Later** — Start with a simple CLI client for fast iteration and testing, then layer on a TUI and other clients. The server is the stable core; clients are interchangeable.

## Design Principles

1. **Config-driven agents** — Agent behavior (system prompt, output type, thinking, serving modes, approval) is defined in TOML config, not Python subclasses. New agents are config entries, not new classes.
2. **Protocol-native** — Built on A2A via a2a-sdk v1.0 for standardized agent communication. Multi-path routing: N agents, N agent cards, one server.
3. **pydantic-ai foundation** — Unified interface for all LLM providers with structured output validation.
4. **Local-first** — Server binds to `127.0.0.1` only; no network exposure by default.
5. **Hub-first development** — Build the agent hub (server) as the stable core, then iterate on clients.
6. **Metadata-driven clients** — Clients read agent capabilities from agent cards and adapt dynamically. No client-side agent-specific code.

## Non-Goals

- Network-accessible deployment (personal use only, local-first)
- Real-time command suggestions (on-demand only)
- IDE/editor integration (beyond future MCP)
- TOML-based agent *creation* (agents defined via TOML config, but the `AgentSpec` class is the only spec implementation — no `fin ingest` to create new agent classes from TOML)

---

## Documentation Layout

- **[README.md](../README.md)** — canonical architecture **diagrams** (4 inline Mermaid blocks: System Context, Hub Internals, Backend + Shared Services, Request Flow). Regenerate rendered images with `just diagrams`. GitHub renders the Mermaid natively.
- **`docs/architecture.md`** (this file) — architecture **prose**: design principles, component contracts, per-subsystem deep dives, phase history, design-decision rationale. The ASCII overview diagrams below are redundant with the Mermaid diagrams in README and are retained as prose references only — treat the README Mermaid as authoritative if they disagree.
- **`handoff.md`** — rolling multi-session development log: current phase status, design sketches in flight, next-session pointers.
- **`AGENTS.md`** / **`CLAUDE.md`** — development patterns (SDD → TDD workflow, test quality standards, commit rules).

When a structural change to the system lands, update **both** the README Mermaid blocks **and** the relevant architecture.md prose in the same commit. To prevent reoccurrence of the ContextProviders-style drift the audit uncovered, any claim in this document that a subsystem is "integrated" or a design decision is "Resolved" must have a citation to a real call site (file:line) somewhere in `src/` — not just to a test or a TOML field.

---

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Client Layer (Frontends)                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  CLI Client     │  │  TUI Client     │  │  Future Clients │             │
│  │  (primary)      │  │  (Textual)      │  │  (web, GUI...)  │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
└───────────┼────────────────────┼────────────────────┼───────────────────────┘
            │                    │                    │
            │  A2A Protocol (HTTP + JSON-RPC)         │
            │  Agent discovery via agent cards        │
            │  Dynamic UI via agent card metadata     │
            └────────────────────┴────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Agent Hub (FastAPI / ASGI)                                │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  GET /agents — discovery endpoint (lists all agent card URLs)        │    │
│  │  GET /health — health check                                          │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Multi-Path Agent Routing (each agent = separate A2A sub-app)        │    │
│  │                                                                       │    │
│  │  /agents/default/                    /agents/shell/                   │    │
│  │  (AgentSpec, [agents.default])       (AgentSpec, [agents.shell])       │    │
│  │  ├── /.well-known/agent-card.json    ├── /.well-known/agent-card.json│    │
│  │  └── / (JSON-RPC endpoint)           └── / (JSON-RPC endpoint)      │    │
│  │                                                                       │    │
│  │  /agents/sdd/ (future)               /agents/{name}/ (future)       │    │
│  │  ├── /.well-known/agent-card.json    ├── /.well-known/agent-card.json│    │
│  │  └── / (JSON-RPC endpoint)           └── / (JSON-RPC endpoint)      │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Shared Storage                                                       │    │
│  │  • Task storage — InMemoryTaskStore (a2a-sdk, ephemeral per process) │    │
│  │  • Context storage — SQLite ContextStore (conversation history)      │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Shared Services                                                      │    │
│  │  • CredentialStore (API keys: env → file → keyring)                  │    │
│  │  • ConfigLoader (TOML + env (FIN_*), pydantic-settings)              │    │
│  │  • ProviderRegistry (LLM providers; api_key injected per call)       │    │
│  │  • ContextProviders — built, not yet wired (Steps 7–8, see below)    │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Shell Integration (Fish) — future                        │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  fin_assist.fish — keybinding launches CLI/TUI, receives output       │    │
│  │  Command insertion — accept shell agent output into commandline       │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CLI Client (primary, built first)                          │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Simple Commands                                                      │   │
│  │  • fin-assist serve          — start agent hub server                 │   │
│  │  • fin-assist agents         — list available agents                  │   │
│  │  • fin-assist ask <agent> .. — one-shot query                         │   │
│  │  • fin-assist chat <agent>   — multi-turn session (uses context_id)  │   │
│  ├──────────────────────────────────────────────────────────────────────┤   │
│  │  REPL Mode (second layer)                                             │   │
│  │  • fin-assist (no args)      — enter interactive REPL                 │   │
│  │  • /switch <agent>           — switch active agent                   │   │
│  │  • Dynamic prompts from agent card metadata                          │   │
│  ├──────────────────────────────────────────────────────────────────────┤   │
│  │  A2A Client (httpx + a2a-sdk ClientFactory)                           │   │
│  │  • Discovers agent cards, sends SendMessage / SendStreamingMessage    │   │
│  │  • Reads AgentCardMeta to adapt display (one-shot vs multi-turn)     │   │
│  │  • Token-by-token streaming via SSE with Rich Live rendering          │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │  A2A Protocol (HTTP + JSON-RPC)
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Agent Hub (FastAPI parent ASGI app)                       │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Hub App (hub/app.py)                                                 │   │
│  │  • Mounts N agent sub-apps at /agents/{name}/                        │   │
│  │  • GET /agents — discovery (lists all agent card URLs + metadata)    │   │
│  │  • GET /health — health check                                        │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Agent Factory (hub/factory.py)                                       │   │
│  │  • AgentSpec → PydanticAIBackend → Executor + DefaultRequestHandler   │   │
│  │  • Maps AgentCardMeta → AgentExtension(uri="fin_assist:meta")        │   │
│  │  • Creates InMemoryTaskStore per agent sub-app                       │   │
│  │  • Shares ContextStore across all sub-apps                           │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Mounted A2A Sub-Apps (one per agent)                                 │   │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐       │   │
│  │  │ /default/  │ │ /shell/    │ │ /sdd/      │ │ /future/   │       │   │
│  │  │ multi-turn │ │ one-shot   │ │ multi-turn │ │ ...        │       │   │
│  │  │ chain-of-  │ │ cmd gen    │ │ design     │ │            │       │   │
│  │  │ thought    │ │            │ │ (future)   │ │            │       │   │
│  │  └────────────┘ └────────────┘ └────────────┘ └────────────┘       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Storage                                                               │   │
│  │  • Task storage: InMemoryTaskStore (a2a-sdk, per sub-app, ephemeral)  │   │
│  │  • Context storage: SQLite ContextStore (hub/context_store.py)        │   │
│  │    — single instance, shared across sub-apps; context_id scoped       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Agent System                                                         │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │  AgentSpec (pure config) + AgentBackend protocol               │  │   │
│  │  │  • AgentSpec: name, system_prompt (registry), output_type        │  │   │
│  │  │    (registry), agent_card_metadata, credentials — all from TOML │  │   │
│  │  │  • PydanticAIBackend (only backend impl): pydantic-ai Agent +    │  │   │
│  │  │    FallbackModel; framework isolation for testability            │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  │  AgentSpec instances created from config.agents (TOML sections)      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Shared Services                                                      │   │
│  │  • CredentialStore — env var → file → keyring fallback              │   │
│  │  • ConfigLoader — file discovery: explicit > FIN_CONFIG_PATH >      │   │
│  │    ./config.toml > ~/.config/fin/config.toml;                        │   │
│  │    source precedence: init args > env (FIN_*) > TOML > defaults     │   │
│  │  • ProviderRegistry — pydantic-ai provider/model creation,          │   │
│  │    api_key passed per create_model() call                           │   │
│  │                                                                       │   │
│  │  Parked (Steps 7–8 of Config-Driven Redesign):                       │   │
│  │  • ContextProviders — files, git, history, environment              │   │
│  │    — classes implemented, not yet wired into the Executor            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  Future Clients                                               │
│  ┌──────────────┐  ┌──────────────────┐  ┌────────────────────────────┐   │
│  │ TUI Client   │  │ Multiplexer      │  │ Fish Plugin                │   │
│  │ (Textual)    │  │ (tmux/zellij)    │  │ (keybinding + insertion)   │   │
│  └──────────────┘  └──────────────────┘  └────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
fin-assist/
├── src/
│   └── fin_assist/
│       ├── __init__.py
│       ├── __main__.py              # CLI entry: `fin-assist [serve|agents|ask|chat]`
│       ├── providers.py             # ProviderMeta definitions
│       │
│       ├── hub/                     # Agent Hub server
│       │   ├── __init__.py
│       │   ├── app.py               # Parent FastAPI app, mounts agent sub-apps
│       │   ├── factory.py           # AgentSpec → a2a-sdk route factories + DefaultRequestHandler
│       │   ├── executor.py          # Executor (AgentExecutor) — streaming, auth-required, history
│       │   ├── context_store.py     # SQLite-backed conversation history persistence
│       │   ├── pidfile.py           # PID file management with fcntl locking
│       │   └── logging.py           # Hub logging configuration (RotatingFileHandler)
│       │
│       ├── cli/                     # CLI client (primary client)
│       │   ├── __init__.py
│       │   ├── main.py              # Command dispatch (serve, agents, do, talk, stop)
│       │   ├── client.py            # A2A client (a2a-sdk ClientFactory over httpx + streaming)
│       │   ├── display.py           # Rich-based output formatting
│       │   ├── server.py            # Auto-start hub, health polling, PID management
│       │   └── interaction/         # Interactive CLI components
│       │       ├── __init__.py
│       │       ├── approve.py       # Approval widget (execute/cancel/add context)
│       │       ├── chat.py          # Multi-turn chat loop (talk command)
│       │       ├── prompt.py        # FinPrompt — prompt-toolkit (`@`-completion planned)
│       │       └── response.py      # Response rendering helpers
│       │
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── spec.py              # AgentSpec — pure config, zero framework deps
│       │   ├── backend.py           # AgentBackend protocol + PydanticAIBackend + StreamHandle
│       │   ├── results.py           # CommandResult and other result models
│       │   ├── registry.py          # OUTPUT_TYPES, SYSTEM_PROMPTS
│       │   ├── metadata.py          # AgentCardMeta, ServingMode, MissingCredentialsError
│       │
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── model_registry.py   # Provider registry
│       │   └── prompts.py          # System prompts (per agent)
│       │
│       ├── context/
│       │   ├── __init__.py
│       │   ├── base.py             # ContextProvider ABC, ContextItem
│       │   ├── files.py            # FileFinder
│       │   ├── git.py              # GitContext
│       │   ├── history.py          # ShellHistory
│       │   └── environment.py      # Environment context
│       │
│       ├── credentials/
│       │   ├── __init__.py
│       │   └── store.py            # Credential storage + keyring
│       │
│       ├── config/
│       │   ├── __init__.py
│       │   ├── loader.py           # Load config.toml
│       │   └── schema.py           # Config dataclasses
│       │
│       ├── ui/                     # TUI Client (Textual) — future
│       │   ├── __init__.py
│       │   ├── app.py              # Textual App
│       │   ├── prompt_input.py     # Text area for input
│       │   ├── agent_output.py     # Output display
│       │   ├── agent_selector.py   # Agent switcher
│       │   ├── model_selector.py   # Provider/model dropdown
│       │   ├── thinking_selector.py # Thinking effort selector
│       │   ├── settings_screen.py  # Settings modal
│       │   └── connect.py          # /connect dialog
│       │
│       ├── multiplexer/            # Future: tmux/zellij integration
│       │   └── ...
│       │
│       ├── skills/                  # Future: Skills framework
│       │   └── ...
│       │
│       └── mcp/                    # Future: MCP client integration
│           └── ...
│
├── tests/
│   ├── conftest.py
│   ├── test_package.py
│   ├── test_config.py
│   ├── test_agents/
│   ├── test_context/
│   ├── test_credentials/
│   ├── test_llm/
│   ├── test_ui/
│   ├── test_hub/                   # Agent Hub tests
│   └── test_cli/                   # CLI client tests
│
├── fish/                           # Fish shell plugin (future)
│   ├── conf.d/
│   │   └── fin_assist.fish
│   └── functions/
│       └── fin_assist.fish
│
├── pyproject.toml
├── justfile
├── devenv.nix
├── devenv.yaml
├── treefmt.toml
├── .envrc
├── .gitignore
├── secretspec.toml
└── docs/
    └── architecture.md
```

---

## Key Interfaces

### Agent Card Metadata (UI Hints)

Static metadata declared by each agent and published in the A2A agent card as an extension. Clients read this to adapt their UI without knowing about specific agent types.

```python
from typing import Literal
from pydantic import BaseModel

ServingMode = Literal["do", "talk", "do_talk"]

class AgentCardMeta(BaseModel):
    """Static UI/capability metadata published in the agent card.

    Clients read these fields to determine which UI elements to show/hide.
    """
    serving_modes: list[ServingMode] = ["do", "talk"]  # Which CLI modes this agent supports
    supports_thinking: bool = True       # Show thinking effort selector?
    supports_model_selection: bool = True # Show model/provider selector?
    supported_providers: list[str] | None = None  # None = all providers
    requires_approval: bool = False      # Does this agent require user approval before action?
    color_scheme: str | None = None      # Optional theming hint for client
    tags: list[str] = Field(default_factory=list)  # Categorization tags
```

> **Note:** `serving_modes` replaces the former `multi_turn: bool` field. An agent with `serving_modes = ["do"]` is one-shot only (like the former ShellAgent). An agent with `serving_modes = ["talk"]` is multi-turn only. `["do", "talk", "do_talk"]` covers all modes.

> **Phase 11 (TUI client):** Add `supported_context_types: list[str] | None = None` to `AgentCardMeta` so the TUI can show/hide context panels (git diff, shell history, etc.) based on the active agent without a round-trip call. `AgentSpec.supports_context()` already encodes this logic at runtime — the metadata field makes it statically discoverable from the agent card. Not added earlier because no client currently reads context-type hints from the card.

### Agent Architecture

fin-assist splits "what the agent is" from "how it runs" across two cooperating pieces:

- **`AgentSpec`** (`src/fin_assist/agents/spec.py`) — a pure configuration object. Zero framework imports (no pydantic-ai, no a2a-sdk). Answers questions like "what is this agent's system prompt?", "what's its output type?", "which providers does it need?", "what metadata goes on its agent card?". Constructed from an `AgentConfig` (TOML section), the global `Config`, and a `CredentialStore`.
- **`AgentBackend`** (`src/fin_assist/agents/backend.py`) — a `Protocol` that says how to actually run a spec: stream output, convert A2A messages to framework messages, serialize conversation history, check credentials. The only production implementation is `PydanticAIBackend`, which wraps `pydantic_ai.Agent` + `FallbackModel`.

The `Executor` (`src/fin_assist/hub/executor.py`) depends on the `AgentBackend` protocol. `AgentSpec` is never imported by the executor — it flows through the backend. This lets us swap in different LLM frameworks (or stub backends for testing) without touching the hub.

#### AgentSpec

```python
class AgentSpec:
    """Pure config; zero framework deps."""

    def __init__(
        self,
        *,
        name: str,
        agent_config: AgentConfig,
        config: Config,
        credentials: CredentialStore,
    ) -> None: ...

    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def system_prompt(self) -> str:        # resolved via SYSTEM_PROMPTS registry
        ...
    @property
    def output_type(self) -> type[Any]:    # resolved via OUTPUT_TYPES registry
        ...
    @property
    def thinking(self) -> ThinkingEffort | None: ...
    @property
    def default_model(self) -> str: ...
    @property
    def agent_card_metadata(self) -> AgentCardMeta: ...

    def check_credentials(self) -> list[str]:
        """Names of enabled providers with missing API keys (empty = all present)."""
    def get_api_key(self, provider: str) -> str | None: ...
    def get_model_name(self, provider: str, default: str) -> str: ...
    def get_enabled_providers(self) -> list[str]: ...
```

#### AgentBackend protocol

```python
@runtime_checkable
class AgentBackend(Protocol):
    def check_credentials(self) -> list[str]: ...
    def run_stream(
        self,
        *,
        messages: list[Any],
        model: Any = None,
    ) -> StreamHandle: ...
    def convert_history(self, messages: list[Message]) -> list[Any]: ...
    def deserialize_history(self, raw: bytes) -> list[Any]: ...
    def convert_result_to_part(self, output: Any) -> Part: ...
```

`StreamHandle` yields text deltas via async iteration and returns a `RunResult(output, serialized_history, new_message_parts)` from `result()`.

#### PydanticAIBackend

```python
class PydanticAIBackend:
    """AgentBackend implementation for pydantic-ai."""

    def __init__(self, *, agent_spec: AgentSpec) -> None:
        self._spec = agent_spec

    # Raises MissingCredentialsError if any required API key is absent.
    def run_stream(self, *, messages: list[Any], model: Any = None) -> StreamHandle: ...
```

> **Why the split?** `AgentSpec` stays trivially testable and stays a candidate for serialization or cross-process transport. The backend layer isolates every pydantic-ai dependency to one file, so replacing the framework — or mocking it for tests — touches only `backend.py`.

> **Why no ABC on `AgentSpec`?** There is only one implementation. An ABC with a single impl is ceremony. If we ever need a type bound for DI/mocking, `typing.Protocol` supports structural subtyping without requiring inheritance. A Rust/Gleam agent would not subclass a Python ABC — it would serve its own A2A endpoint over HTTP. The interop boundary is the A2A protocol, not Python inheritance.

### Agent Variants (Config-Driven)

Agents are defined in TOML config, not as separate Python classes. A single `AgentSpec` class reads its behavior from `AgentConfig`.

> **Context:** context gathering (files, git, history, env) is **not currently wired** into the request path. See "Steps 7–8 (parked)" below. The `ContextProvider` classes exist and are tested in isolation; Executor integration lands with the upcoming CLI flags and `@`-completion work.

#### Default Agent (`[agents.default]`)

- **Purpose**: General-purpose natural language interaction with chain-of-thought reasoning
- **Config**: `system_prompt = "chain-of-thought"`, `output_type = "text"`, `serving_modes = ["do", "talk"]`, `thinking = "medium"`
- **Output**: `str` (free-form text response)
- **Card Metadata**: `serving_modes=["do", "talk"], supports_thinking=True, requires_approval=False`

#### Shell Agent (`[agents.shell]`)

- **Purpose**: Shell command generation from natural language
- **Config**: `system_prompt = "shell"`, `output_type = "command"`, `serving_modes = ["do"]`, `thinking = null`, `requires_approval = true`
- **Output**: `CommandResult(command: str, warnings: list[str])`
- **Card Metadata**: `serving_modes=["do"], supports_thinking=False, requires_approval=True`
- **Dynamic Metadata**: `{"accept_action": "insert_command"}` in artifact metadata

#### SDD Agent (`[agents.sdd]`) — future

- **Purpose**: Architectural brainstorming and design
- **Config**: `enabled = false`, `system_prompt = "sdd"`, `output_type = "text"`, `serving_modes = ["talk"]`
- **Output**: Free-form text (SketchResult structured output in future)

#### TDD Agent (`[agents.tdd]`) — future

- **Purpose**: Directed implementation with test generation
- **Config**: `enabled = false`, `system_prompt = "tdd"`, `output_type = "text"`, `serving_modes = ["talk"]`
- **Output**: Free-form text (TDDResult structured output in future)

### Agent Config (TOML)

```toml
[agents.default]
enabled = true
system_prompt = "chain-of-thought"    # Resolved via SYSTEM_PROMPTS
output_type = "text"                   # Resolved via OUTPUT_TYPES
thinking = "medium"                    # ThinkingEffort: "low", "medium", "high", or null
serving_modes = ["do", "talk"]         # Which CLI modes this agent supports
requires_approval = false
tags = ["general", "chain-of-thought"]

[agents.shell]
enabled = true
system_prompt = "shell"
output_type = "command"                # Maps to CommandResult
thinking = null                        # No thinking for shell agent
serving_modes = ["do"]                 # One-shot only
requires_approval = true
tags = ["shell", "one-shot"]
```

### Output Type Registry

Maps config names to Python types, enabling TOML to reference types by name:

```python
OUTPUT_TYPES: dict[str, type] = {
    "text": str,
    "command": CommandResult,
}
```

### Prompt Registry

Maps config names to prompt constants:

```python
SYSTEM_PROMPTS: dict[str, str] = {
    "chain-of-thought": CHAIN_OF_THOUGHT_INSTRUCTIONS,
    "shell": SHELL_INSTRUCTIONS,
}
```

### Agent Hub

The hub is a module-level factory function, not a class. `create_hub_app()` builds the parent FastAPI app, constructs a single shared `ContextStore`, and mounts one sub-app per enabled agent via `AgentFactory`.

```python
# src/fin_assist/hub/app.py
from fastapi import FastAPI

from fin_assist.agents.spec import AgentSpec
from fin_assist.hub.context_store import ContextStore
from fin_assist.hub.factory import AgentFactory

def create_hub_app(
    config: Config,
    credentials: CredentialStore,
    *,
    db_path: Path,
) -> FastAPI:
    """Build the parent FastAPI app with all enabled agent sub-apps mounted."""
    app = FastAPI(title="fin-assist Agent Hub")
    context_store = ContextStore(db_path=db_path)          # shared across sub-apps
    factory = AgentFactory(context_store=context_store)

    for name, agent_config in config.agents.items():
        if not agent_config.enabled:
            continue
        spec = AgentSpec(
            name=name,
            agent_config=agent_config,
            config=config,
            credentials=credentials,
        )
        sub_app = factory.create_a2a_app(spec)
        app.mount(f"/agents/{name}", sub_app)

    @app.get("/agents")
    async def discovery(): ...     # returns each sub-app's agent card URL + metadata

    @app.get("/health")
    async def health(): ...

    return app
```

### Agent Factory

```python
# src/fin_assist/hub/factory.py
class AgentFactory:
    """Translates AgentSpec into a FastAPI sub-app with a2a-sdk route factories."""

    def __init__(self, context_store: ContextStore) -> None:
        self._context_store = context_store               # shared, not per-agent

    def create_a2a_app(
        self,
        agent: AgentSpec,
        *,
        base_url: str = "http://127.0.0.1:4096",
    ) -> FastAPI:
        """Build a FastAPI sub-app for a single agent.

        1. Build AgentCard with AgentExtension (fin_assist:meta) for metadata.
        2. Construct PydanticAIBackend wrapping the spec.
        3. Construct Executor (AgentBackend consumer) + per-sub-app InMemoryTaskStore.
        4. Wire through DefaultRequestHandler.
        5. Mount a2a-sdk route factories (JSON-RPC + agent card).
        """
        backend = PydanticAIBackend(agent_spec=agent)
        executor = Executor(backend=backend, context_store=self._context_store)
        task_store = InMemoryTaskStore()                  # per sub-app, ephemeral
        request_handler = DefaultRequestHandler(
            agent_executor=executor,
            task_store=task_store,
            agent_card=agent_card,
        )

        app = FastAPI(title=f"fin-assist: {agent.name}")
        app.routes.extend(create_agent_card_routes(agent_card))
        app.routes.extend(create_jsonrpc_routes(request_handler, rpc_url="/"))
        return app
```

### UI Metadata Flow

```
Static (discovery time):                    Dynamic (per-response):
┌──────────────────────┐                    ┌──────────────────────────┐
│ Agent Card            │                    │ Task Artifact             │
│ (/.well-known/        │                    │ (returned with each      │
│  agent-card.json)     │                    │  task completion)        │
│                       │                    │                          │
│ • name, description  │                    │ • result data            │
│ • skills[]           │                    │ • metadata: {            │
│ • extensions: [      │                    │     accept_action: ...,  │
│   {uri: "fin_assist:│                    │     suggested_next: ..., │
│    meta", params: {  │                    │   }                      │
│       serving_modes, │                    │   }                      │
│       thinking,      │                    │                          │
│       model_select,  │                    └──────────────────────────┘
│       color_scheme,  │
│       requires_approval │
│     }                │
│   }                  │
└──────────────────────┘
```

### Context Provider Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Any

@dataclass
class ContextItem:
    id: str
    type: Literal["file", "git_diff", "history", "env"]
    content: str
    metadata: dict[str, Any]

class ContextProvider(ABC):
    @abstractmethod
    def search(self, query: str) -> list[ContextItem]: ...

    @abstractmethod
    def get_item(self, id: str) -> ContextItem | None: ...

    @abstractmethod
    def get_all(self) -> list[ContextItem]: ...
```

### Multiplexer Interface (future)

```python
class Multiplexer(ABC):
    @classmethod
    @abstractmethod
    def is_available(cls) -> bool: ...

    @abstractmethod
    def launch_floating(self, command: list[str]) -> None: ...

    @abstractmethod
    def capture_context(self) -> str | None: ...
```

---

## A2A Protocol Integration

### Background

**A2A (Agent-to-Agent)** is an open protocol (originated by Google) for standardized agent communication. **a2a-sdk v1.0** is Google's official Python SDK, supporting JSON-RPC, REST, and gRPC transports from a single protobuf schema.

Key benefits for fin-assist:
- **Standardized interface** — any A2A-compatible client can talk to the server
- **Agent discovery** — Agent Cards at `/.well-known/agent-card.json` per agent
- **Task lifecycle** — built-in task state management (submitted, working, completed, failed, auth-required, canceled)
- **Conversation context** — `context_id` links multi-turn conversations across tasks
- **Structured artifacts** — pydantic models become protobuf `Part(data=...)` artifacts with JSON schema metadata
- **Streaming** — `SendStreamingMessage` method delivers token-by-token SSE output
- **Auth-required state** — first-class `TaskState.TASK_STATE_AUTH_REQUIRED` for credential-gated agents

### Multi-Path Routing

The A2A protocol maps 1:1 between a server and an agent card. To host N agents on one server, we use **multi-path routing**: a parent FastAPI app mounts each agent's A2A sub-app at a unique path.

```
Parent FastAPI App (127.0.0.1:4096)
├── GET  /agents                                    → discovery (list all agents)
├── GET  /health                                    → health check
├── Mount /agents/default/                    → AgentSpec([agents.default]) A2A sub-app
│   ├── GET  /.well-known/agent-card.json           → agent card
│   └── POST /                                      → JSON-RPC (SendMessage, GetTask, SendStreamingMessage)
├── Mount /agents/shell/                      → AgentSpec([agents.shell]) A2A sub-app
│   ├── GET  /.well-known/agent-card.json           → agent card
│   └── POST /                                      → JSON-RPC
└── Mount /agents/{future}/                         → future agents
```

Each agent maintains its own context and conversation state. Context IDs are naturally scoped per-agent because tasks are sent to different A2A endpoints.

### a2a-sdk v1.0 Components

- **DefaultRequestHandler** — routes JSON-RPC methods to the executor. Replaces the former `InMemoryBroker`.
- **Executor** — implements `AgentExecutor` with `execute()` and `cancel()`. Framework-agnostic: it depends on an `AgentBackend` protocol (currently `PydanticAIBackend`) that handles model building, streaming, message conversion, and history serialization. The Executor owns streaming loop, auth-required detection, and context persistence. Replaces the former `FinAssistWorker`.
- **TaskUpdater** — SDK helper for state transitions (`start_work`, `complete`, `failed`, `requires_auth`, `add_artifact`).
- **InMemoryTaskStore** — ephemeral task storage managed by the SDK (tasks are lost on server restart).
- **ContextStore** — our own SQLite-backed store for pydantic-ai conversation history, persisted across tasks within a conversation.
- **AgentExtension** — publishes `AgentCardMeta` as a proper extension (`uri="fin_assist:meta"`) in the agent card's capabilities, replacing the former `Skill(id="fin_assist:meta")` hack.

### Transport Layer

The A2A protocol defines transport as pluggable. a2a-sdk v1.0 supports JSON-RPC, REST, and gRPC transports from the same protobuf schema. The v1.0 JSON-RPC method names are PascalCase (`SendMessage`, `GetTask`, `CancelTask`, `SendStreamingMessage`) and require the `A2A-Version: 1.0` header.

**Current:** JSON-RPC over HTTP (blocking `SendMessage`) + SSE streaming (`SendStreamingMessage`).

**Modality roadmap:**

| Modality | Transport | Status | Notes |
|---|---|---|---|
| Blocking `SendMessage` | JSON-RPC | ✅ Implemented | Hub responds inline when agent finishes |
| Streaming `SendStreamingMessage` | JSON-RPC SSE | ✅ Implemented | Token-by-token via `TaskUpdater.add_artifact(append=True)` |
| Non-blocking + polling | JSON-RPC | Later phase | `SendMessage` with `blocking: false`; `_poll_task` fallback exists |
| gRPC | gRPC | Future | Protocol-native; a2a-sdk v1.0 supports it |

The non-blocking polling path is implemented in `cli/client.py` (`_poll_task`)
as a correct protocol fallback, but is not exercised by the current hub
which defaults to blocking mode.

### CLI Entry Points

```
fin-assist serve                        → start agent hub on 127.0.0.1:4096
fin-assist agents                       → list available agents (GET /agents)
fin-assist do "prompt"                  → one-shot query to [agents.default]
fin-assist do <agent> "prompt"          → one-shot query to named agent
fin-assist do <agent> "prompt" --file path --git-diff --git-log  → with context
fin-assist talk                          → multi-turn session with [agents.default]
fin-assist talk <agent>                 → multi-turn session with named agent
fin-assist talk <agent> --resume <id>   → resume a saved session
fin-assist talk <agent> --list          → list saved sessions for agent
fin-assist                              → enter interactive REPL (future)
```

Server lifecycle:
- **Standalone**: `fin-assist serve` starts the hub server
- **Auto-start**: `fin-assist do/talk/agents` auto-start the server if not running

### Local-Only Security

The server binds to `127.0.0.1` by default, ensuring only local processes can communicate with agents. This is intentional — fin-assist is designed for personal use on a trusted machine.

---

## Configuration

### Config File

Config is loaded from the first available location:
1. Explicit path (API parameter)
2. `FIN_CONFIG_PATH` environment variable
3. `./config.toml` (project-local override in current working directory)
4. `~/.config/fin/config.toml` (user default)

```toml
[general]
default_provider = "anthropic"
default_model = "claude-sonnet-4-6"

[server]
host = "127.0.0.1"
port = 4096
db_path = "~/.local/share/fin/hub.db"  # SQLite storage

[context]
max_file_size = 100000
max_history_items = 50
include_git_status = true
include_env_vars = ["PATH", "HOME", "USER", "PWD"]

[agents.default]
enabled = true
system_prompt = "chain-of-thought"     # Resolved via SYSTEM_PROMPTS
output_type = "text"                    # Resolved via OUTPUT_TYPES
thinking = "medium"                     # ThinkingEffort: "low", "medium", "high", or null
serving_modes = ["do", "talk"]          # Which CLI modes this agent supports
requires_approval = false
tags = ["general", "chain-of-thought"]

[agents.shell]
enabled = true
system_prompt = "shell"
output_type = "command"                  # Maps to CommandResult
thinking = null                          # No thinking for shell agent
serving_modes = ["do"]                   # One-shot only
requires_approval = true
tags = ["shell", "one-shot"]

[providers.anthropic]
# API key stored separately in credentials

[providers.openrouter]
# API key stored separately in credentials

[providers.ollama]
base_url = "http://localhost:11434"
```

### Credential Storage (~/.local/share/fin/credentials.json)

Credentials stored separately from config (0600 permissions). Supports env var -> file -> keyring fallback chain.

---

## Implementation Phases

### Phase 1: Repo Setup ✅
- [x] Initialize devenv (devenv.nix, devenv.yaml)
- [x] Create pyproject.toml with dependencies
- [x] Set up justfile with common tasks
- [x] Configure treefmt.toml for formatting
- [x] Add .gitignore, .envrc
- [x] Create secretspec.toml for dev secrets
- [x] Enable branch protections (PR requirement + no force push)

### Phase 2: Core Package Structure ✅
- [x] Create src/fin_assist/ package layout
- [x] Add GitHub Actions CI workflow (using nix shell approach)
- [x] Re-enable required status checks in branch protections
- [x] Implement config loading (config/schema.py, config/loader.py)
- [x] Set up pydantic settings

### Phase 3: LLM Module ✅
- [x] Integrate pydantic-ai for provider abstraction
- [x] Implement Agent wrapper (llm/agent.py)
- [x] Create provider registry (llm/providers.py)
- [x] Write system prompts (llm/prompts.py)

### Phase 4: Credential Management ✅
- [x] Implement /connect command UI (ui/connect.py)
- [x] Create credential store (credentials/store.py)
- [x] Add optional OS keyring backend (credentials/keyring.py)

### Phase 5: Context Module ✅
- [x] Implement ContextProvider ABC (context/base.py)
- [x] File finder with find (context/files.py)
- [x] Git context gatherer (context/git.py)
- [x] Fish history parser (context/history.py)
- [x] Environment context (context/environment.py)

### Phase 6: Agent Protocol & Registry ✅
- [x] Define `BaseAgent` ABC with `AgentResult`
- [x] ~~Create `AgentRegistry`~~ (removed — superseded by hub's explicit agent list)
- [x] Implement `DefaultAgent` (chain-of-thought base)
- [x] TUI foundation (Textual widgets — set aside, usable as future client)

### Phase 7: Agent Hub Server ✅
- [x] Extend `BaseAgent` with `AgentCardMeta` dataclass
- [x] Create `ShellAgent` — one-shot command generation, `multi_turn=False`
- [x] Implement `hub/storage.py` — SQLite-backed fasta2a `Storage` ABC
- [x] Implement `hub/factory.py` — BaseAgent → pydantic-ai Agent → `.to_a2a()` with shared storage
- [x] Implement `hub/app.py` — parent Starlette app, mount agents at `/agents/{name}/`, `GET /agents` discovery endpoint
- [x] Implement `hub/worker.py` — FinAssistWorker with `auth-required` state for missing credentials
- [x] Implement `hub/logging.py` — RotatingFileHandler for background hub
- [x] Wire entry point — `fin-assist serve` starts the hub via uvicorn
- [x] Tests — hub creation, agent mounting, discovery endpoint, storage CRUD, worker auth-required

### Phase 8: CLI Client ✅
- [x] Implement `cli/client.py` — A2A client using httpx + a2a-sdk ClientFactory
- [x] Implement `cli/display.py` — Rich-based output formatting
- [x] Implement `cli/server.py` — auto-start server with health polling + backoff
- [x] Implement `cli/interaction/approve.py` — approval widget (`ApprovalAction`)
- [x] Implement `cli/interaction/chat.py` — multi-turn chat loop with streaming
- [x] Implement `cli/main.py` — `serve`, `agents`, `do`, `talk` commands with `_hub_client` context manager
- [x] Session persistence — `~/.local/share/fin/sessions/{agent}/{slug}.json` with coolname slugs
- [x] Tests — CLI client, display, server, interaction modules

### Phase 8b: CLI REPL Mode ✅
- [x] Implement `cli/interaction/prompt.py` — `FinPrompt` with prompt-toolkit fuzzy completion
- [x] Wire `FinPrompt` into `chat.py` and `approve.py` (replaces `rich.prompt.Prompt`)
- [x] Agent name tab completion via `agents` parameter
- [x] Persistent input history (`~/.local/share/fin/history`)
- [x] Slash-command fuzzy completion (`/exit`, `/quit`, `/q`, `/switch`, `/help`)
- [x] `prompt-toolkit>=3.0` added as explicit dependency
- [x] Tests — 8 new tests for `FinPrompt`

### Config-Driven Redesign 📐
- [x] Step 1: `ServingMode` enum + `serving_modes` field on `AgentCardMeta`
- [x] Step 2: Output type + prompt registries (`OUTPUT_TYPE_REGISTRY`, `PROMPT_REGISTRY`)
- [x] Step 3: Per-agent TOML config sections (`AgentConfig` in `config/schema.py`)
- [x] Step 4: Collapse to single `ConfigAgent` class (remove `BaseAgent` ABC, `DefaultAgent`, `ShellAgent`). Later split into `AgentSpec` (pure config) + `PydanticAIBackend` (framework glue) — see commit `a16ba70`.
- [x] Step 5: Direct `Worker[Context]` implementation (close #68)
- [x] Step 6: Default agent shortcut (`fin do "prompt"` → `[agents.default]`)
- [ ] Step 7: Context injection for `do` (`--file`, `--git-diff`, `--git-log` flags)
- [ ] Step 8: Context injection for `talk` (`@`-completion in FinPrompt)
- [ ] Step 9: Approval "add context" option for structured output in talk mode

### a2a-sdk Migration ✅
- [x] Replace fasta2a with a2a-sdk v1.0 (Google's official A2A Python SDK)
- [x] Replace Starlette with FastAPI (sub-apps from a2a-sdk route factories)
- [x] Replace `InMemoryBroker` + `FinAssistWorker` with `DefaultRequestHandler` + `Executor`
- [x] Replace `Skill(id="fin_assist:meta")` with `AgentExtension(uri="fin_assist:meta")`
- [x] Split `SQLiteStorage` into `InMemoryTaskStore` (SDK) + `ContextStore` (SQLite)
- [x] Implement token-by-token streaming via `TaskUpdater.add_artifact(append=True)`
- [x] Implement `stream_agent()` in `cli/client.py` with SSE + `StreamEvent` model
- [x] Update `cli/interaction/chat.py` with Rich `Live` streaming rendering
- [x] Fix all type errors (protobuf-native types: `Part`, `Struct`, `Sequence[Part]`)
- [x] Fix runtime bugs (Task enqueue requirement, async `get_output()`, v1.0 protocol)
- [x] Update e2e tests for v1.0 protocol (`SendMessage`, `A2A-Version: 1.0`)
- [x] 446 tests passing, lint clean, typecheck clean

### Phase 9: Streaming + Integration Tests 🔄

- [x] Implement `stream_agent()` in `cli/client.py` using `SendStreamingMessage` + SSE
- [x] Update `cli/interaction/chat.py` to render streaming output progressively
- [x] Handle `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent` frames
- [x] Wire to `talk` command — streaming as default if agent card supports it
- [x] Executor unit tests — streaming artifact chunks
- [ ] Streaming e2e test — `SendStreamingMessage` through full SDK dispatcher
- [ ] Integration test harness — real uvicorn server, real HTTP (httpx), subprocess lifecycle
- [ ] Integration tests for CLI commands (`do`, `talk`, `agents`, `stop`) against live hub
- [ ] Integration tests for streaming SSE connection lifecycle and progressive rendering
- [ ] Integration tests for server auto-start/stop and PID management

### Phase 11: Multiplexer Integration ⬜
- [ ] Multiplexer ABC (multiplexer/base.py)
- [ ] tmux implementation (multiplexer/tmux.py)
- [ ] zellij implementation (multiplexer/zellij.py)
- [ ] Fallback (alternate screen) (multiplexer/fallback.py)
- [ ] Launch CLI/TUI in floating pane

### Phase 12: Fish Plugin ⬜
- [ ] Create fish plugin (fish/conf.d/fin_assist.fish)
- [ ] Keybinding for CLI/TUI launch
- [ ] Command insertion (receive shell agent output, insert into command line)
- [ ] Server auto-start (launch server if not running)

### Phase 13: TUI Client ⬜
- [ ] Refactor existing Textual widgets as A2A client (reuse ui/ code)
- [ ] Wire TUI to agent hub via A2A client (not direct agent calls)
- [ ] Per-agent UI adaptation driven by agent card metadata

### Phase 14: Testing Infrastructure (Deep Evals) ⬜
- [ ] Set up deep evals framework (pytest-compatible)
- [ ] Define must/must-not/should criteria per agent
- [ ] Implement LLM-as-judge evaluator (default, configurable per agent)
- [ ] Create eval suite for `AgentSpec` (default and shell configs)
- [ ] Per-agent eval configuration

### Phase 15: Skills + MCP Integration ⬜
- [ ] Skills framework (configurable behaviors per agent)
- [ ] MCP client integration
- [ ] CLI/TUI components for skill/MCP configuration
- [ ] Per-project skill/MCP configuration

### Phase 16: Additional Agents ⬜
- [ ] Create `agents/sdd.py` (design brainstorming)
- [ ] Define `SketchResult` model
- [ ] Implement tools: `read_file`, `write_file`, `list_docs`
- [ ] Create `agents/tdd.py` (test-driven development)
- [ ] Define `TDDResult` model
- [ ] Implement tools: `read_file`, `write_file`, `run_command`, `list_files`
- [ ] Code review agent, computer use agent, journaling agent, etc.

### Phase 17: Multi-Agent Workflows ⬜
- [ ] Agent-to-agent communication via A2A (SDD → TDD handoff)
- [ ] Orchestration patterns (sequential, parallel, DAG-based)
- [ ] Hyper-agent exploration

### Phase 18: Documentation ⬜
- [ ] User documentation
- [ ] Installation guide
- [ ] Update architecture.md if needed

---

## Open Questions

Decisions deferred until the relevant phase. Resolved decisions are noted.

> **Pointer to in-flight work.** Four structural changes are known-needed but not started. Their design + implementation notes live in `handoff.md` (the rolling session log) rather than here, because they are actively being refined. This section records only the architectural commitment; details evolve there.
>
> 1. **Executor loop rework** — The `Executor` is currently one-shot (messages in → stream out → done). Tool calling, context injection triggered by the agent, plan-and-execute, self-critique, and most experimental loop patterns all require a multi-step loop. **Needs design sketch before implementation.** See `handoff.md` → "Executor Loop Rework".
> 2. **ContextProviders integration (Steps 7-8)** — `FileFinder`, `GitContext`, `ShellHistory`, `Environment` exist and are tested but unwired. Integration deliberately deferred until the Executor loop rework lands, because the loop's shape dictates the injection API. The module carries an in-code marker (`src/fin_assist/context/__init__.py` docstring) pointing at `handoff.md`.
> 3. **Human-in-the-loop (HITL) approval model** — Current `requires_approval: bool` is agent-level and binary. Fine-grained gates (per-tool, per-plan, per-effect, approve-with-edit) are needed for meaningful experimentation. **Needs research spike** (survey of existing tools' approval models) before design. See `handoff.md` → "HITL Approval Model".
> 4. **`AgentBackend` protocol simplification** — The current protocol has ~6 methods, several of which leak pydantic-ai shape. Tracked as [#80](https://github.com/ColeB1722/fin-assist/issues/80) (enhancement / tech-debt); revisit when a second backend is actually implemented.

| Question | Phase | Status | Resolution |
|----------|-------|--------|------------|
| Conversation storage | Phase 7 | **Resolved** | SQLite `ContextStore` for conversation history; `InMemoryTaskStore` for A2A tasks |
| Server lifecycle | Phase 8 | **Resolved** | `fin-assist serve` standalone; auto-start via `ensure_server_running` |
| Multi-agent routing | Phase 7 | **Resolved** | Multi-path: one FastAPI parent, N A2A sub-apps at `/agents/{name}/` |
| UI metadata transport | Phase 7 | **Resolved** | Split: static in agent card, dynamic in task artifact metadata |
| Parent ASGI framework | Phase 7 | **Resolved** | FastAPI (a2a-sdk sub-apps are FastAPI; consistent framework) |
| Agent card extensions format | Phase 7 | **Resolved** | `AgentExtension(uri="fin_assist:meta", params=Struct)` — proper a2a-sdk extension |
| Agent execution pattern | Migration | **Resolved** | `Executor(AgentExecutor)` + `DefaultRequestHandler` replaces broker/worker (framework-agnostic via `AgentBackend` protocol) |
| Streaming | Phase 9 | **Resolved** | Token-by-token via `TaskUpdater.add_artifact(append=True)` + `SendStreamingMessage` SSE |
| gRPC transport | Future | Open | A2A protocol supports gRPC; a2a-sdk v1.0 supports it, not yet used by fin-assist |
| Agent architecture | Redesign | **Resolved** | Config-driven: single `Agent` class, behavior from `AgentConfig` in TOML |
| ShellAgent vs DefaultAgent | Redesign | **Resolved** | Merged into a single `AgentSpec` (pure config); `ShellAgent` behavior is `[agents.shell]` config. Framework glue isolated in `PydanticAIBackend`. |
| `multi_turn: bool` vs `ServingMode` | Redesign | **Resolved** | `ServingMode = Literal["do", "talk", "do_talk"]` — more expressive |
| Private `AgentWorker` import (#68) | Redesign | **Resolved** | Direct `Worker[list[ModelMessage]]` implementation using public APIs |
| Thinking configuration | Redesign | **Resolved** | Per-agent `thinking` field in `AgentConfig`, not `DefaultAgent` override |
| Default agent shortcut | Redesign | **Resolved** | `fin do "prompt"` / `fin talk` → `[agents.default]`; agent arg optional |
| Context injection for `do` | Redesign | Open (Step 7) — **blocked on Executor Loop Rework** | Planned: CLI flags (`--file`, `--git-diff`, `--git-log`). ContextProviders built in Phase 5 but not yet wired into Executor or `do` parser. See `handoff.md` → "ContextProviders — Parked State". |
| Context injection for `talk` | Redesign | Open (Step 8) — **blocked on Executor Loop Rework** | Planned: `@`-completion in FinPrompt via `ContextProvider.search()`. ContextProviders built, integration unstarted. |
| Executor loop (one-shot → multi-step) | TBD | Open — **needs design sketch** | Prerequisite for tool calling, context injection, plan-and-execute, self-critique, and most experimental loop patterns. See `handoff.md` → "Executor Loop Rework". |
| HITL approval model | TBD | Open — **needs research spike** | Current `requires_approval: bool` is agent-level and binary. Fine-grained gates (per-tool, per-plan, per-effect) needed for experimentation. See `handoff.md` → "HITL Approval Model". |
| AgentBackend protocol shape | Cleanup | Open — [#80](https://github.com/ColeB1722/fin-assist/issues/80) | Protocol currently reflects pydantic-ai shape in ~5 of 6 methods. Revisit when a second backend is actually needed. |
| External agent federation | Future | Open | Hub can register external A2A servers (any language) in discovery; deferred until real external agent exists to validate config schema |
| Non-blocking agents | Phase 10 | Open | `SendMessage` with `blocking: false`; `_poll_task` fallback already implemented |
| Deep evals criteria | Phase 14 | Open | Must/must-not/should per agent, LLM-as-judge default |
| Hub server logging | Phase 9 | **Resolved** | Configurable via `[server] log_path` (default `~/.local/share/fin/hub.log`). Startup errors captured via subprocess stderr redirect. `configure_logging()` called before `create_hub_app()` to catch early import/initialization errors. Full structured logging (per-module loggers, log levels in config) deferred to Phase 9 when streaming makes observability matter. |

---

## Future Considerations

### External Agent Federation

The hub currently only mounts **internal** agents — Python `AgentSpec` instances running in-process as A2A sub-apps. The A2A protocol is language-agnostic, so the hub can also register **external** agents: any process that serves the two A2A endpoints (`GET /.well-known/agent-card.json` + `POST /` JSON-RPC), regardless of implementation language.

**Two pluggability levels:**

| Level | What | Current support |
|-------|------|-----------------|
| Config plugins | New agent behaviors via TOML (different prompt, output type, serving modes) | Done |
| Process plugins | External A2A servers in any language, registered with the hub via URL | Not yet |

**Federation model — hub as registry, not proxy:**

External agents register their URL in config. The hub lists them in the discovery endpoint (`GET /agents`) alongside internal agents. Clients talk to external agents directly — the hub is a directory service, not a proxy. This aligns with A2A's design: agent cards already have a `url` field, and the discovery endpoint already returns per-agent URLs.

**Config schema (when implemented):**

```toml
[agents.myrust]
mode = "external"                          # new field; internal is default
url = "http://127.0.0.1:5001"             # A2A endpoint of the external agent

[agents.claude-code]
mode = "external"
url = "http://127.0.0.1:5002"
```

**What changes when implemented:**

1. `AgentConfig` gets `mode: Literal["internal", "external"]` and `url: str | None`
2. `create_hub_app()` distinguishes internal (mount sub-app) vs external (register URL in discovery only)
3. Discovery endpoint already returns agent URLs — minimal change needed
4. Client, CLI, streaming all work as-is — they're protocol-native

**What external agents don't get:**

`ContextStore`, `CredentialStore`, `ContextProviders` are in-process Python services. External agents manage their own credentials, context, and conversation history. This is the correct boundary: shared services are an implementation convenience for internal agents, not a protocol requirement.

**Why defer:** No external agents exist yet. The change is small and well-understood (~50 lines), but designing the config schema without a real external process to validate against risks over-fitting. Once a toy Rust/Gleam agent exists, the schema will be obvious. The discovery endpoint is already forward-compatible — agent entries include a `url` field that can point externally.

### Near-term (Phases 13-15)
- **Skills framework** — Configurable behaviors (e.g., brainstorming mode, terse mode)
- **MCP integration** — Natural language interface to configurable MCP tools/servers
- **Additional agents** — SDD, TDD, code review, shell completion, computer use, journaling
- **Multi-agent workflows** — Agent-to-agent via A2A, orchestration patterns

### Long-term
- **Web client** — HTML/JS frontend as A2A client
- **Hyper-agents** — Meta-agents that orchestrate specialized agents
- **Shell expansion** — bash, zsh support after fish is stable
- **Ghostty support** — when popup feature lands (upstream issue #3197)
- **Command history learning** — learn from accepted commands
- **Custom prompts** — user-defined prompt templates
- **Per-project config** — Agent/skill/MCP configuration per project via TOML

### Deferred (No Timeline)
- **RabbitMQ dispatch** — Work queue with N concurrent TDD agents (from AI-Directed-Dev-Pipeline)
- **DAG-based task execution** — Task dependencies mapped to architectural boundaries

---

## Related Documents

- [AI-Directed-Dev-Pipeline](../sebs-vault/Brainstorming/AI-Directed-Dev-Pipeline.md) — Long-term vision for agent swarm-driven development

---

## Related Issues

- #14: LLM evals for shell command generation
- #15: MCP tool integration for extended capabilities
- #16: Validation and test cleanup for LLM/credentials modules
- #45: Test quality: improve assertions and remove private state access
- #58: display.py: derive credentials path from shared constant
- #60: config/loader.py: warn when FIN_CONFIG_PATH points to non-existent file
- #75: ContextStore: async I/O + close() method
- #76: test_client.py: refactor _send_and_wait tests to use public API

---

## Appendix: Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| A2A SDK | a2a-sdk v1.0 (Google) | Official SDK; fasta2a abandoned; v1.0 supports JSON-RPC, REST, gRPC from protobuf schema |
| Multi-path routing | N agents, N agent cards, one server | True A2A compliance, enables agent-to-agent workflows |
| Parent ASGI framework | FastAPI | a2a-sdk route factories produce FastAPI-compatible routes; consistent framework across sub-apps |
| Config-driven agents | TOML config defines agent behavior | Enables adding new agents without writing Python classes; `AgentSpec` is the only spec implementation |
| Spec/backend split | `AgentSpec` (pure config) + `AgentBackend` protocol (framework glue) | Isolates pydantic-ai to one file (`agents/backend.py`); spec is trivially testable and transport-ready; backend swap touches one module |
| No ABC for specs | Single `AgentSpec` class, no `BaseAgent` ABC | Only one implementation exists; `Protocol` for DI/mocking if needed later; multi-language agents use A2A protocol, not Python inheritance |
| Executor over Worker/Broker | `Executor(AgentExecutor)` + `DefaultRequestHandler` | a2a-sdk pattern; no broker needed; `TaskUpdater` for state transitions; Executor depends on `AgentBackend` protocol, not pydantic-ai directly |
| Agent card metadata | `AgentExtension(uri="fin_assist:meta", params=Struct)` | Proper a2a-sdk extension; replaces `Skill(id="fin_assist:meta")` hack |
| Streaming | Token-by-token via `TaskUpdater.add_artifact(append=True)` + SSE | Progressive output via `SendStreamingMessage`; Rich `Live` rendering on client |
| Task storage | `InMemoryTaskStore` (ephemeral) | a2a-sdk managed; tasks lost on server restart; acceptable for personal local-first tool |
| Conversation storage | SQLite `ContextStore` | Persists pydantic-ai message history across tasks; `context_id` for threading |
| `serving_modes` over `multi_turn` | `ServingMode = Literal["do", "talk", "do_talk"]` | More expressive than boolean; declares which CLI modes an agent supports |
| Default agent shortcut | `fin do "prompt"` → `[agents.default]` | Reduces friction for common case; agent arg optional |
| Context for `do` (planned, Step 7) | CLI flags (`--file`, `--git-diff`, `--git-log`) | No TUI required for one-shot mode; not yet implemented |
| Context for `talk` (planned, Step 8) | `@`-completion in FinPrompt | Will use `ContextProvider.search()`; FinPrompt plumbing pending |
| Local-only server | Bind 127.0.0.1 | Personal tool, no network exposure; future opt-in |
| CLI-first development | CLI before TUI | Faster iteration on hub + agent behavior; TUI becomes a client later |
| UI metadata transport | Static in agent card, dynamic in artifacts | Agent card declares capabilities; per-response hints in artifact metadata |
| Agent creation | TOML config entries, not Python classes | `ShellAgent` behavior is a config variant; adding agents is editing TOML |
| Testing approach | Deep evals + CI | LLM-as-judge by default, pytest-compatible, post-merge regression checks |
