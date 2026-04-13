# fin-assist Architecture

## Overview

fin-assist is an **expandable personal AI agent platform** for terminal workflows. It provides an **Agent Hub** — a server that hosts N specialized agents over the A2A protocol — and multiple client interfaces (CLI, TUI, future web) that dynamically adapt their UI based on each agent's declared capabilities.

### Core Vision

**Agent Hub** — A "turnstile" of specialized agents exposed via A2A protocol (fasta2a). Each agent is independently discoverable, has its own agent card, and can be swapped in/out of the server. The hub handles routing, conversation persistence, and agent lifecycle.

**Dynamic UI via Agent Metadata** — Clients adapt their interface based on agent capabilities. Static metadata (multi-turn, thinking support, model selection) is declared in the A2A agent card. Dynamic metadata (accept actions, rendering hints) is returned per-response in task artifacts. Clients don't need to know about specific agents — they read metadata and adapt.

**Protocol-Native** — Built on A2A (Agent-to-Agent) protocol via fasta2a. Any A2A-compatible client can communicate with the hub. This enables future agent-to-agent workflows (e.g., SDD agent handing off to TDD agent).

**CLI-First, TUI-Later** — Start with a simple CLI client for fast iteration and testing, then layer on a TUI and other clients. The server is the stable core; clients are interchangeable.

## Design Principles

1. **Config-driven agents** — Agent behavior (system prompt, output type, thinking, serving modes, approval) is defined in TOML config, not Python subclasses. New agents are config entries, not new classes.
2. **Protocol-native** — Built on A2A via fasta2a for standardized agent communication. Multi-path routing: N agents, N agent cards, one server.
3. **pydantic-ai foundation** — Unified interface for all LLM providers with structured output validation.
4. **Local-first** — Server binds to `127.0.0.1` only; no network exposure by default.
5. **Hub-first development** — Build the agent hub (server) as the stable core, then iterate on clients.
6. **Metadata-driven clients** — Clients read agent capabilities from agent cards and adapt dynamically. No client-side agent-specific code.

## Non-Goals

- Network-accessible deployment (personal use only, local-first)
- Real-time command suggestions (on-demand only)
- IDE/editor integration (beyond future MCP)
- TOML-based agent *creation* (agents defined via TOML config, but the `Agent` class is the only implementation — no `fin ingest` to create new agent classes from TOML)

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
│                    Agent Hub (Starlette / ASGI)                               │
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
│  │  (ConfigAgent, [agents.default])    (ConfigAgent, [agents.shell])    │    │
│  │  ├── /.well-known/agent-card.json    ├── /.well-known/agent-card.json│    │
│  │  └── / (JSON-RPC endpoint)           └── / (JSON-RPC endpoint)      │    │
│  │                                                                       │    │
│  │  /agents/sdd/ (future)               /agents/{name}/ (future)       │    │
│  │  ├── /.well-known/agent-card.json    ├── /.well-known/agent-card.json│    │
│  │  └── / (JSON-RPC endpoint)           └── / (JSON-RPC endpoint)      │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Shared Storage (SQLite, fasta2a Storage ABC)                        │    │
│  │  • Task storage — A2A tasks, status, artifacts, messages             │    │
│  │  • Context storage — conversation history per context_id             │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Shared Services                                                      │    │
│  │  • CredentialStore (API keys)                                         │    │
│  │  • ConfigLoader (TOML, 4-level priority)                               │    │
│  │  • ContextProviders (files, git, history, env)                      │    │
│  │  • ProviderRegistry (LLM providers)                                    │    │
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
│  │  A2A Client (httpx)                                                   │   │
│  │  • Discovers agent cards, sends message/send, parses artifacts       │   │
│  │  • Reads AgentCardMeta to adapt display (one-shot vs multi-turn)    │   │
│  │  • Rich-based output formatting                                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │  A2A Protocol (HTTP + JSON-RPC)
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Agent Hub (Starlette parent ASGI app)                      │
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
│  │  • ConfigAgent → pydantic-ai Agent → FastA2A() direct construction     │   │
│  │  • Maps AgentCardMeta → fasta2a Skill + agent card extensions       │   │
│  │  • Injects shared storage + broker                                   │   │
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
│  │  SQLite Storage (hub/storage.py — fasta2a Storage ABC)               │   │
│  │  • Task storage: A2A tasks, status, artifacts, messages              │   │
│  │  • Context storage: conversation history per context_id              │   │
│  │  • Shared across all agents (context_id scoped per agent path)      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Agent System                                                         │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │  ConfigAgent + AgentConfig (config-driven, single class)     │  │   │
│  │  │  • name, system_prompt (from registry), output_type (from registry)│  │   │
│  │  │  • agent_card_metadata → AgentCardMeta (from config fields)    │  │   │
│  │  │  • serving_modes, thinking, requires_approval — all from TOML  │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  │  ConfigAgent instances created from config.agents (TOML sections)    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Shared Services                                                      │   │
│  │  • CredentialStore — env var → file → keyring fallback              │   │
│  │  • ConfigLoader — TOML config (explicit > env > cwd > default)     │   │
│  │  • ContextProviders — files, git, history, environment              │   │
│  │  • ProviderRegistry — LLM provider/model creation                   │   │
│  │  • PromptBuilder — system/user prompt construction                  │   │
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
│       │   ├── app.py               # Parent Starlette app, mounts agent sub-apps
│       │   ├── factory.py           # Agent → FastA2A() with direct Worker (no to_a2a())
│       │   ├── storage.py           # SQLite-backed fasta2a Storage implementation
│       │   ├── worker.py            # FinAssistWorker(Worker[list[ModelMessage]]) — public API only
│       │   ├── pidfile.py           # PID file management with fcntl locking
│       │   └── logging.py           # Hub logging configuration (RotatingFileHandler)
│       │
│       ├── cli/                     # CLI client (primary client)
│       │   ├── __init__.py
│       │   ├── main.py              # Command dispatch (serve, agents, do, talk, stop)
│       │   ├── client.py            # A2A client wrapper (httpx + fasta2a TypeAdapters)
│       │   ├── display.py           # Rich-based output formatting
│       │   ├── server.py            # Auto-start hub, health polling, PID management
│       │   └── interaction/         # Interactive CLI components
│       │       ├── __init__.py
│       │       ├── approve.py       # Approval widget (execute/cancel/add context)
│       │       ├── chat.py          # Multi-turn chat loop (talk command)
│       │       └── prompt.py        # FinPrompt — prompt-toolkit with @-completion
│       │
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── agent.py             # ConfigAgent (config-driven, single class, no ABC)
│       │   ├── results.py           # CommandResult and other result models
│       │   ├── registries.py        # OUTPUT_TYPE_REGISTRY, PROMPT_REGISTRY
│       │   ├── metadata.py          # AgentCardMeta, ServingMode, AgentResult
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
    tags: list[str] = field(default_factory=list)  # Categorization tags
```

> **Note:** `serving_modes` replaces the former `multi_turn: bool` field. An agent with `serving_modes = ["do"]` is one-shot only (like the former ShellAgent). An agent with `serving_modes = ["talk"]` is multi-turn only. `["do", "talk", "do_talk"]` covers all modes.

> **Phase 11 (TUI client):** Add `supported_context_types: list[str] | None = None` to `AgentCardMeta` so the TUI can show/hide context panels (git diff, shell history, etc.) based on the active agent without a round-trip call. `ConfigAgent.supports_context()` already encodes this logic at runtime — the metadata field makes it statically discoverable from the agent card. Not added earlier because no client currently reads context-type hints from the card.

### Agent Protocol

```python
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar('T')

@dataclass
class AgentResult:
    """Base result type for all agents."""
    success: bool
    output: str
    warnings: list[str]
    metadata: dict[str, Any]  # Dynamic per-response hints (e.g. accept_action)

class ConfigAgent(Generic[T]):
    """Config-driven agent. Behavior is defined by AgentConfig from TOML.

    No ABC, no subclasses — different agents are different configs.
    If a type bound is needed for DI/mocking, use typing.Protocol.
    """

    def __init__(self, name: str, config: AgentConfig, app_config: Config, credentials: CredentialStore):
        self._name = name
        self._config = config
        self._app_config = app_config
        self._credentials = credentials

    @property
    def name(self) -> str:
        """Agent identifier (used for routing path: /agents/{name}/)."""
        return self._name

    @property
    def description(self) -> str:
        """Human-readable description from config."""
        return self._config.description

    @property
    def system_prompt(self) -> str:
        """System prompt resolved from registry by config name."""
        return PROMPT_REGISTRY[self._config.system_prompt]

    @property
    def output_type(self) -> type[T]:
        """Output type resolved from registry by config name."""
        return OUTPUT_TYPE_REGISTRY[self._config.output_type]

    @property
    def agent_card_metadata(self) -> AgentCardMeta:
        """Static UI/capability metadata derived from config."""
        return AgentCardMeta(
            serving_modes=self._config.serving_modes,
            supports_thinking=self._config.thinking is not None,
            requires_approval=self._config.requires_approval,
            tags=self._config.tags,
        )

    def supports_context(self, context_type: str) -> bool:
        """Check if agent can use a given context type."""
        return context_type in self._config.supported_context_types

    async def run(
        self,
        prompt: str,
        context: list[ContextItem],
    ) -> AgentResult:
        """Execute the agent."""
        ...
```

> **Why no ABC?** The config-driven design means there's only one implementation — `ConfigAgent`. An ABC with a single impl is ceremony. If we ever need a type bound for DI/mocking, `typing.Protocol` supports structural subtyping (duck typing) without requiring inheritance. A Rust/Gleam agent wouldn't subclass a Python ABC — it would serve its own A2A endpoint over HTTP. The interop boundary is the A2A protocol, not Python inheritance.
```

### Agent Variants (Config-Driven)

Agents are defined in TOML config, not as separate Python classes. A single `Agent` class reads its behavior from `AgentConfig`.

#### Default Agent (`[agents.default]`)

- **Purpose**: General-purpose natural language interaction with chain-of-thought reasoning
- **Config**: `system_prompt = "chain-of-thought"`, `output_type = "text"`, `serving_modes = ["do", "talk"]`, `thinking = true`
- **Context**: Files, git, history, environment (all context types)
- **Output**: `str` (free-form text response)
- **Card Metadata**: `serving_modes=["do", "talk"], supports_thinking=True, requires_approval=False`

#### Shell Agent (`[agents.shell]`)

- **Purpose**: Shell command generation from natural language
- **Config**: `system_prompt = "shell"`, `output_type = "command"`, `serving_modes = ["do"]`, `thinking = false`, `requires_approval = true`
- **Context**: Files, git, history, environment
- **Output**: `CommandResult(command: str, warnings: list[str])`
- **Card Metadata**: `serving_modes=["do"], supports_thinking=False, requires_approval=True`
- **Dynamic Metadata**: `{"accept_action": "insert_command"}` in AgentResult.metadata

#### SDD Agent (`[agents.sdd]`) — future

- **Purpose**: Architectural brainstorming and design
- **Config**: `enabled = false`, `system_prompt = "sdd"`, `output_type = "text"`, `serving_modes = ["talk"]`
- **Context**: Docs only (`docs/`)
- **Output**: Free-form text (SketchResult structured output in future)

#### TDD Agent (`[agents.tdd]`) — future

- **Purpose**: Directed implementation with test generation
- **Config**: `enabled = false`, `system_prompt = "tdd"`, `output_type = "text"`, `serving_modes = ["talk"]`
- **Context**: Code files, test files, project structure
- **Output**: Free-form text (TDDResult structured output in future)

### Agent Config (TOML)

```toml
[agents.default]
enabled = true
system_prompt = "chain-of-thought"    # Resolved via PROMPT_REGISTRY
output_type = "text"                   # Resolved via OUTPUT_TYPE_REGISTRY
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
OUTPUT_TYPE_REGISTRY: dict[str, type] = {
    "text": str,
    "command": CommandResult,
}
```

### Prompt Registry

Maps config names to prompt constants:

```python
PROMPT_REGISTRY: dict[str, str] = {
    "chain-of-thought": CHAIN_OF_THOUGHT_INSTRUCTIONS,
    "shell": SHELL_INSTRUCTIONS,
}
```

### Agent Hub

```python
from starlette.applications import Starlette
from starlette.routing import Mount, Route

class AgentHub:
    """The 'turnstile' — hosts N agents as A2A sub-apps on one server."""

    def __init__(self, config: Config, credentials: CredentialStore):
        self.config = config
        self.credentials = credentials
        self.storage = SQLiteStorage(...)  # shared across all agents

    def build_app(self) -> Starlette:
        """Build the parent ASGI app with all agent sub-apps mounted."""
        routes = [
            Route("/agents", self._discovery_endpoint),
            Route("/health", self._health_endpoint),
        ]
        for agent in self._create_agents():
            a2a_app = self._agent_to_a2a(agent)
            routes.append(Mount(f"/agents/{agent.name}", app=a2a_app))
        return Starlette(routes=routes)

    def _create_agents(self) -> list[ConfigAgent]:
        """Create agents from TOML config, not hardcoded list."""
        agents = []
        for name, agent_config in self.config.agents.items():
            if agent_config.enabled:
                agents.append(ConfigAgent(name, agent_config, self.config, self.credentials))
        return agents

    def _agent_to_a2a(self, agent: ConfigAgent) -> FastA2A:
        """Convert an Agent to a fasta2a ASGI sub-app.

        Uses direct FastA2A() construction with FinAssistWorker,
        not pydantic_agent.to_a2a(). Maps AgentCardMeta to
        fasta2a Skills + agent card extensions.
        """
        ...
```

### Agent Factory

```python
class AgentFactory:
    """Translates Agent into a fasta2a ASGI sub-app with custom Worker."""

    def create_a2a_app(
        self,
        agent: ConfigAgent,
        storage: Storage,
        broker: Broker,
    ) -> FastA2A:
        """Build a fasta2a sub-app for a single agent.

        1. Create pydantic-ai Agent with config-driven system_prompt,
           output_type, and thinking settings
        2. Construct FastA2A() directly with custom lifespan that
           creates FinAssistWorker(Worker[list[ModelMessage]])
        3. Inject AgentCardMeta as agent card skills/extensions
        4. No pydantic_agent.to_a2a() — eliminates wasted default AgentWorker
        """
        ...
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
│ • extensions: {      │                    │     accept_action: ...,  │
│     fin_assist: {    │                    │     suggested_next: ..., │
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

**A2A (Agent-to-Agent)** is an open protocol (originated by Google, adopted by pydantic) for standardized agent communication. **fasta2a** is pydantic's Python implementation, built on Starlette/ASGI.

Key benefits for fin-assist:
- **Standardized interface** — any A2A-compatible client can talk to the server
- **Agent discovery** — Agent Cards at `/.well-known/agent-card.json` per agent
- **Task lifecycle** — built-in task state management (pending, working, completed, failed, auth-required)
- **Conversation context** — `context_id` links multi-turn conversations across tasks
- **Structured artifacts** — pydantic models become `DataPart` artifacts with JSON schema metadata

### Multi-Path Routing

The A2A protocol maps 1:1 between a server and an agent card. To host N agents on one server, we use **multi-path routing**: a parent Starlette app mounts each agent's A2A sub-app at a unique path.

```
Parent Starlette App (127.0.0.1:4096)
├── GET  /agents                                    → discovery (list all agents)
├── GET  /health                                    → health check
├── Mount /agents/default/                    → ConfigAgent([agents.default]) A2A sub-app
│   ├── GET  /.well-known/agent-card.json           → agent card
│   └── POST /                                      → JSON-RPC (message/send, tasks/get)
├── Mount /agents/shell/                      → ConfigAgent([agents.shell]) A2A sub-app
│   ├── GET  /.well-known/agent-card.json           → agent card
│   └── POST /                                      → JSON-RPC
└── Mount /agents/{future}/                         → future agents
```

Each agent maintains its own context and conversation state. Context IDs are naturally scoped per-agent because tasks are sent to different A2A endpoints.

### fasta2a Components

- **Storage** — persists tasks and conversation context. We implement the `Storage` ABC with SQLite, shared across all agents.
- **Broker** — schedules async task execution. `InMemoryBroker` for local use (single-process).
- **Worker** — executes agent logic. pydantic-ai provides a default via `Agent.to_a2a()`. fin-assist overrides with `FinAssistWorker` (`hub/worker.py`) which maps `MissingCredentialsError` to `auth-required` task state instead of `failed`.

### Transport Layer

The A2A protocol defines transport as pluggable. The official `a2a-python` SDK
(Google) ships `JsonRpcTransport`, `GrpcTransport`, and `RestTransport` all
behind a common `ClientTransport` ABC. fasta2a currently implements JSON-RPC
only.

**Current:** JSON-RPC over HTTP (blocking `message/send`).

**Modality roadmap:**

| Modality | Transport | Status | Notes |
|---|---|---|---|
| Blocking `message/send` | JSON-RPC | ✅ Implemented | Hub responds inline when agent finishes |
| Streaming `message/stream` | JSON-RPC SSE | Phase 9 | Progressive output; fasta2a has `stream_message_response_ta` ready |
| Non-blocking + polling | JSON-RPC | Later phase | `message/send` with `blocking: false`; `_poll_task` fallback exists |
| gRPC | gRPC | Issue | Protocol-native; wait for fasta2a support or evaluate `a2a-python` |

The non-blocking polling path is implemented in `cli/client.py` (`_poll_task`)
as a correct protocol fallback, but is not exercised by the current fasta2a hub
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
system_prompt = "chain-of-thought"     # Resolved via PROMPT_REGISTRY
output_type = "text"                    # Resolved via OUTPUT_TYPE_REGISTRY
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
- [x] Implement `cli/client.py` — A2A client using httpx + fasta2a TypeAdapters
- [x] Implement `cli/display.py` — Rich-based output formatting
- [x] Implement `cli/server.py` — auto-start server with health polling + backoff
- [x] Implement `cli/interaction/approve.py` — approval widget (`ApprovalAction`)
- [x] Implement `cli/interaction/chat.py` — multi-turn chat loop
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
- [x] Step 4: Collapse to single `ConfigAgent` class (remove `BaseAgent` ABC, `DefaultAgent`, `ShellAgent`)
- [x] Step 5: Direct `Worker[Context]` implementation (close #68)
- [x] Step 6: Default agent shortcut (`fin do "prompt"` → `[agents.default]`)
- [ ] Step 7: Context injection for `do` (`--file`, `--git-diff`, `--git-log` flags)
- [ ] Step 8: Context injection for `talk` (`@`-completion in FinPrompt)
- [ ] Step 9: Approval "add context" option for structured output in talk mode

### Phase 9: Streaming + Integration Tests ⬜ **NEXT**
- [ ] Implement `stream_agent()` in `cli/client.py` using `message/stream` + SSE
- [ ] Update `cli/interaction/chat.py` to render streaming output progressively
- [ ] Handle `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent` frames
- [ ] Wire to `talk` command — streaming as default if agent card supports it
- [ ] Tests — streaming output, partial artifact rendering
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
- [ ] Create eval suite for ConfigAgent (default and shell configs)
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

| Question | Phase | Status | Resolution |
|----------|-------|--------|------------|
| Conversation storage | Phase 7 | **Resolved** | SQLite via fasta2a `Storage` ABC, `context_id` for threading |
| Server lifecycle | Phase 8 | **Resolved** | `fin-assist serve` standalone; auto-start via `ensure_server_running` |
| Multi-agent routing | Phase 7 | **Resolved** | Multi-path: one Starlette parent, N A2A sub-apps at `/agents/{name}/` |
| UI metadata transport | Phase 7 | **Resolved** | Split: static in agent card, dynamic in task artifact metadata |
| Parent ASGI framework | Phase 7 | **Resolved** | Starlette (stays in pydantic/fasta2a ecosystem) |
| Agent card extensions format | Phase 7 | **Resolved** | `AgentCardMeta` encoded as `fin_assist:meta` Skill until fasta2a extensions land |
| `to_a2a()` customization | Phase 7 | **Resolved** | Direct `FastA2A()` construction with custom lifespan — no `pydantic_agent.to_a2a()` |
| SQLite file location | Phase 7 | **Resolved** | Configurable via `[server] db_path`, defaults to `~/.local/share/fin/hub.db` |
| Agent architecture | Redesign | **Resolved** | Config-driven: single `Agent` class, behavior from `AgentConfig` in TOML |
| ShellAgent vs DefaultAgent | Redesign | **Resolved** | Merged into single `ConfigAgent` class; `ShellAgent` behavior is `[agents.shell]` config |
| `multi_turn: bool` vs `ServingMode` | Redesign | **Resolved** | `ServingMode = Literal["do", "talk", "do_talk"]` — more expressive |
| Private `AgentWorker` import (#68) | Redesign | **Resolved** | Direct `Worker[list[ModelMessage]]` implementation using public APIs |
| Thinking configuration | Redesign | **Resolved** | Per-agent `thinking` field in `AgentConfig`, not `DefaultAgent` override |
| Default agent shortcut | Redesign | **Resolved** | `fin do "prompt"` / `fin talk` → `[agents.default]`; agent arg optional |
| Context injection for `do` | Redesign | **Resolved** | CLI flags (`--file`, `--git-diff`, `--git-log`) |
| Context injection for `talk` | Redesign | **Resolved** | `@`-completion in FinPrompt via `ContextProvider.search()` |
| gRPC transport | Future | Open | A2A protocol supports gRPC; wait for fasta2a support or evaluate `a2a-python` |
| Non-blocking agents | Phase 10 | Open | `message/send` with `blocking: false`; `_poll_task` fallback already implemented |
| Deep evals criteria | Phase 14 | Open | Must/must-not/should per agent, LLM-as-judge default |
| Hub server logging | Phase 9 | **Resolved** | Configurable via `[server] log_path` (default `~/.local/share/fin/hub.log`). Startup errors captured via subprocess stderr redirect. `configure_logging()` called before `create_hub_app()` to catch early import/initialization errors. Full structured logging (per-module loggers, log levels in config) deferred to Phase 9 when streaming makes observability matter. |

---

## Future Considerations

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
- #61: hub/factory.py: add type hints to _worker_lifespan parameters

---

## Appendix: Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| A2A over custom REST | fasta2a | Protocol-native multi-client, agent discovery, task lifecycle built-in |
| Multi-path routing | N agents, N agent cards, one server | True A2A compliance, enables agent-to-agent workflows |
| Parent ASGI framework | Starlette | Lighter than FastAPI, stays in pydantic/fasta2a ecosystem |
| Config-driven agents | TOML config defines agent behavior | Enables adding new agents without writing Python classes; `ConfigAgent` is the only implementation |
| No ABC for agents | Single `ConfigAgent` class, no `BaseAgent` ABC | Only one implementation exists; `Protocol` for DI/mocking if needed later; multi-language agents use A2A protocol, not Python inheritance |
| Direct Worker implementation | `Worker[list[ModelMessage]]` | Eliminates private `pydantic_ai._a2a` import (#68), removes wasted default AgentWorker, enables streaming |
| `serving_modes` over `multi_turn` | `ServingMode = Literal["do", "talk", "do_talk"]` | More expressive than boolean; declares which CLI modes an agent supports |
| Default agent shortcut | `fin do "prompt"` → `[agents.default]` | Reduces friction for common case; agent arg optional |
| Context for `do` | CLI flags (`--file`, `--git-diff`) | No TUI required for one-shot mode |
| Context for `talk` | `@`-completion in FinPrompt | Uses existing `ContextProvider.search()`, no TUI required |
| Local-only server | Bind 127.0.0.1 | Personal tool, no network exposure; future opt-in |
| CLI-first development | CLI before TUI | Faster iteration on hub + agent behavior; TUI becomes a client later |
| Conversation storage | SQLite via fasta2a Storage ABC | A2A-native `context_id` for threading, shared across all agents |
| UI metadata transport | Static in agent card, dynamic in artifacts | Agent card declares capabilities; per-response hints in artifact metadata |
| Agent creation | TOML config entries, not Python classes | `ShellAgent` behavior is a config variant; adding agents is editing TOML |
| Testing approach | Deep evals + CI | LLM-as-judge by default, pytest-compatible, post-merge regression checks |
