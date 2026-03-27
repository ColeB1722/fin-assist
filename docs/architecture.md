# fin-assist Architecture

## Overview

fin-assist is a **personal AI agent platform** for terminal workflows, inspired by Zed's inline assistant and OpenCode's server/client architecture. It provides a TUI for natural language interaction with specialized agents, multi-provider LLM support, and a seamless accept/run workflow — all built on a **fasta2a (A2A protocol)** backend that enables multiple frontend clients.

### Core Vision

**Agent = Chain-of-Thought** — Like OpenCode's "thinking" before responding, agents take natural language input and produce thoughtful output through reasoning. The DefaultAgent is the base agent (multi-turn capable), while specialized agents (shell completion, SDD, TDD) slot into the framework naturally.

**Skills + MCP** — Agents can be extended with configurable skills (behaviors) and MCP tools, exposed as natural language interfaces.

**Per-Agent UI** — The TUI adapts to each agent's capabilities, hiding irrelevant selectors (e.g., model selector when agent only works with one model).

## Design Principles

1. **Agents as code** — Custom specialized agents, not declarative configurations. The fun is in the implementation.
2. **Protocol-native** — Built on the A2A (Agent-to-Agent) protocol via fasta2a for standardized agent communication and multi-client support.
3. **pydantic-ai foundation** — Unified interface for all LLM providers with structured output validation.
4. **Local-first** — Server binds to `127.0.0.1` only; no network exposure by default.
5. **Fish-shell native** — Primary integration target, but the backend is shell-agnostic.

## Non-Goals

- Shell-agnostic implementation (fish-first, generalize later)
- Real-time command suggestions (on-demand only)
- IDE/editor integration (beyond future MCP)
- Network-accessible deployment (personal use only)

---

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Client Layer (Frontends)                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  TUI Client     │  │  Web Client     │  │  Future Clients │             │
│  │  (Textual)      │  │  (HTML/JS)      │  │  (GUI, CLI...)  │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
└───────────┼────────────────────┼────────────────────┼───────────────────────┘
            │                    │                    │
            │  A2A Protocol (HTTP + SSE + JSON-RPC)  │
            └────────────────────┴────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    fin-assist Server (fasta2a / ASGI)                        │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Agent Router — dispatches incoming requests to the appropriate agent │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                    Specialized Agents (pydantic-ai)                    │    │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐      │    │
│  │  │ Default    │  │ Shell      │  │ SDD        │  │ TDD        │      │    │
│  │  │ Agent      │  │ Agent      │  │ Agent      │  │ Agent      │      │    │
│  │  │ (chain-of- │  │ (special-  │  │ (future)   │  │ (future)   │      │    │
│  │  │  thought)  │  │  ized)     │  │            │  │            │      │    │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘      │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Storage — Conversation/task persistence                           │    │
│  │  (see Open Questions: JSON vs SQLite)                               │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Shared Services                                                      │    │
│  │  • CredentialStore (API keys)                                         │    │
│  │  • ConfigLoader (TOML)                                                │    │
│  │  • ContextProviders (files, git, history, env)                      │    │
│  │  • ProviderRegistry (LLM providers)                                    │    │
│  │  • Skills (configurable behaviors)                                     │    │
│  │  • MCP Client (tool integration)                                       │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Shell Integration (Fish)                             │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  fin_assist.fish — keybinding launches TUI, receives output           │    │
│  │  fin_assist serve — starts background server (optional)               │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          fish shell                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  fin-assist plugin (conf.d/functions)                                 │   │
│  │  - Keybinding: ctrl-enter (configurable)                              │   │
│  │  - Captures: commandline buffer, pwd, env context                     │   │
│  │  - Launches fin-assist server (if not running) + TUI client           │   │
│  │  - Receives output, inserts into commandline                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    fin-assist (Python 3.12 / Textual + fasta2a)              │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Client Layer (Textual TUI — the primary, default client)             │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │  PromptInput      - textarea with @ mention trigger              │  │   │
│  │  │  ModelSelector    - dropdown for provider/model                 │  │   │
│  │  │  AgentSelector    - tabs/dropdown for agent selection          │  │   │
│  │  │  ContextPreview   - shows added context items                  │  │   │
│  │  │  ActionButtons    - [Accept] [Run]                             │  │   │
│  │  │  ConnectDialog    - /connect provider setup UI                  │  │   │
│  │  │  ChatHistory      - conversation history for multi-turn agents │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Server Layer (fasta2a / ASGI)                                        │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │  FastA2A App — wraps agents as A2A server                       │  │   │
│  │  │  • TaskManager — coordinates task lifecycle                     │  │   │
│  │  │  • Storage — persists tasks and conversation context            │  │   │
│  │  │  • Broker — schedules async task execution                     │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Agent System                                                         │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │  Agent Protocol (BaseAgent ABC)                                 │  │   │
│  │  │  • name, description, system_prompt, output_type               │  │   │
│  │  │  • supports_context(context_type) -> bool                      │  │   │
│  │  │  • run(prompt, context) -> AgentResult[T]                       │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │  AgentRegistry — registers and dispatches agents                │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐       │   │
│  │  │ Default    │ │ SDD        │ │ TDD        │ │ Future     │       │   │
│  │  │ Agent     │ │ Agent      │ │ Agent      │ │ Agents     │       │   │
│  │  │ (shell)   │ │ (design)   │ │ (impl)     │ │            │       │   │
│  │  └────────────┘ └────────────┘ └────────────┘ └────────────┘       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Context Module                                                       │   │
│  │  - FileFinder: find for file discovery (fd optional)                  │   │
│  │  - GitContext: git diff/log/status for recent changes               │   │
│  │  - ShellHistory: parse fish history for context                      │   │
│  │  - Environment: cwd, relevant env vars                               │   │
│  │  - Agent-specific filtering (SDD→docs only, TDD→code only)          │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  LLM Module (pydantic-ai)                                            │   │
│  │  - Agent: Unified interface for all providers                         │   │
│  │  - FallbackModel: Automatic failover between models                   │   │
│  │  - ProviderRegistry: Anthropic, OpenRouter, Ollama, etc.            │   │
│  │  - PromptBuilder: Constructs system/user prompts                     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Credential Module                                                    │   │
│  │  - CredentialStore: Secure storage in ~/.local/share/fin/            │   │
│  │  - KeyringBackend: Optional OS keyring integration                    │   │
│  │  - ConnectCommand: TUI flow for adding providers                     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  Multiplexer Integration                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  tmux — FloatingPane via display-popup                                │  │
│  │  zellij — FloatingPane via plugin --floating                         │  │
│  │  ghostty (future) — Pending upstream popup support                   │  │
│  │  Fallback — Alternate screen buffer                                   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
fin-assist/
├── src/
│   └── fin_assist/
│       ├── __init__.py
│       ├── __main__.py              # CLI entry: `fin-assist [serve|tui|...]`
│       ├── server/                  # Future: fasta2a server
│       │   ├── __init__.py
│       │   ├── app.py               # FastA2A ASGI app setup
│       │   ├── router.py           # Agent routing logic
│       │   └── lifespan.py         # Server lifespan (start/stop hooks)
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py             # BaseAgent ABC, AgentResult model
│       │   ├── registry.py         # AgentRegistry (decorator-based registration)
│       │   ├── default.py          # DefaultAgent (chain-of-thought base)
│       │   ├── shell.py            # Future: ShellAgent (shell command generation)
│       │   ├── sdd.py              # Future: SDDAgent (design)
│       │   └── tdd.py              # Future: TDDAgent (test-driven)
│       ├── skills/                  # Future: Skills framework
│       │   └── __init__.py
│       ├── mcp/                    # Future: MCP client integration
│       │   └── __init__.py
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── agent.py            # pydantic-ai Agent wrapper (per agent)
│       │   ├── model_registry.py   # Provider registry
│       │   └── prompts.py          # System prompts (per agent)
│       ├── context/
│       │   ├── __init__.py
│       │   ├── base.py             # ContextProvider ABC, ContextItem
│       │   ├── files.py            # FileFinder
│       │   ├── git.py             # GitContext
│       │   ├── history.py          # ShellHistory
│       │   └── environment.py
│       ├── credentials/
│       │   ├── __init__.py
│       │   └── store.py            # Credential storage + keyring
│       ├── multiplexer/            # Future: tmux/zellij integration
│       │   ├── __init__.py
│       │   ├── base.py             # Multiplexer ABC
│       │   ├── tmux.py
│       │   ├── zellij.py
│       │   └── fallback.py
│       ├── config/
│       │   ├── __init__.py
│       │   ├── loader.py           # Load config.toml
│       │   └── schema.py           # Config dataclasses
│       └── ui/                     # TUI Client (Textual)
│           ├── __init__.py
│           ├── app.py              # Textual App (Phase 7)
│           ├── prompt_input.py     # Text area for input (Phase 7)
│           ├── agent_output.py     # Output display (Phase 7)
│           ├── agent_selector.py   # Agent switcher (Phase 7)
│           ├── model_selector.py   # Provider/model dropdown (Phase 7)
│           ├── context_preview.py  # Future: context items display
│           ├── chat_history.py    # Future: multi-turn history
│           └── connect.py          # /connect dialog (done)
├── fish/                           # Fish shell plugin
│   ├── conf.d/
│   │   └── fin_assist.fish        # Keybinding, TUI launch
│   └── functions/
│       └── fin_assist.fish
├── tests/
│   ├── unit/
│   └── integration/
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

### Agent Protocol

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar('T')

@dataclass
class AgentResult:
    """Base result type for all agents."""
    success: bool
    output: str
    warnings: list[str]
    metadata: dict[str, Any]

class BaseAgent(ABC, Generic[T]):
    """Protocol that all specialized agents must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent identifier (used for routing, e.g. 'shell', 'sdd', 'tdd')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for agent selection UI."""
        ...

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Agent-specific system instructions."""
        ...

    @property
    @abstractmethod
    def output_type(self) -> type[T]:
        """Pydantic model for structured output."""
        ...

    @abstractmethod
    def supports_context(self, context_type: str) -> bool:
        """Check if agent can use a given context type."""
        ...

    @abstractmethod
    async def run(
        self,
        prompt: str,
        context: list[ContextItem],
    ) -> AgentResult[T]:
        """Execute the agent."""
        ...
```

### Agent Registry

```python
class AgentRegistry:
    _agents: dict[str, BaseAgent]

    @classmethod
    def register(cls, agent_cls: type[BaseAgent]) -> type[BaseAgent]:
        """Decorator to register an agent class."""
        ...

    @classmethod
    def get(cls, name: str) -> BaseAgent | None:
        """Get agent by name."""
        ...

    @classmethod
    def list_agents(cls) -> list[tuple[str, str]]:
        """List all registered agents (name, description)."""
        ...
```

### Specialized Agents

#### DefaultAgent (chain-of-thought base)

- **Purpose**: General-purpose natural language interaction with chain-of-thought reasoning
- **Mode**: Multi-turn capable (uses message history via pydantic-ai)
- **Context**: Files, git, history, environment (configurable per agent)
- **Output**: Text response (structured output for specialized agents)
- **Tools**: None by default; extensible via skills/MCP
- **Note**: This is the base agent that specialized agents extend

#### ShellAgent (specialized)

- **Purpose**: Shell command generation from natural language
- **Mode**: One-shot (inherits multi-turn capability but typically single-turn)
- **Context**: Files, git, history, environment
- **Output**: `CommandResult(command: str, warnings: list[str])`
- **Tools**: None (stateless prompt → command)
- **Prefix**: `/shell` or implicit when shell agent selected

#### SDDAgent (sketch-driven design)

- **Purpose**: Architectural brainstorming and design
- **Mode**: Multi-turn conversation
- **Context**: Docs only (`docs/`)
- **Output**: `SketchResult(diagram: str, decisions: list[Decision], next_steps: list[str])`
- **Tools**:
  - `read_file(path: str)` — read docs
  - `write_file(path: str, content: str)` — update sketches
  - `list_docs()` — enumerate available documentation
- **Prefix**: `/sdd`

#### TDDAgent (test-driven development)

- **Purpose**: Directed implementation with test generation
- **Mode**: Multi-turn (test → impl → verify)
- **Context**: Code files, test files, project structure
- **Output**: `TDDResult(impl_code: str, test_code: str, verified: bool)`
- **Tools**:
  - `read_file(path: str)` — read code
  - `write_file(path: str, content: str)` — write code/tests
  - `run_command(cmd: str)` — run tests with verification
  - `list_files(pattern: str)` — find relevant files
- **Prefix**: `/tdd`

### A2A Server (fasta2a)

```python
from fasta2a import FastA2A
from fasta2a.broker import InMemoryBroker
from fasta2a.storage import InMemoryStorage

from fin_assist.agents import AgentRegistry

app = FastA2A(
    storage=InMemoryStorage(),
    broker=InMemoryBroker(),
)

# Agent exposure via pydantic-ai's to_a2a()
# Each agent wraps a pydantic-ai Agent and exposes as A2A service
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

### Multiplexer Interface

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
- **Agent discovery** — Agent Cards at `/.well-known/agent.json`
- **Task lifecycle** — built-in task state management (pending, working, completed, failed)
- **Conversation context** — `context_id` links multi-turn conversations across tasks
- **Streaming** — SSE support for real-time token streaming

### fasta2a Components

- **Storage** — persists tasks and conversation context (default: `InMemoryStorage`; file-backed for production)
- **Broker** — schedules async task execution (default: `InMemoryBroker`)
- **Worker** — executes agent logic (pydantic-ai provides this via `Agent.to_a2a()`)

### OpenCode-Inspired Server Pattern

Following OpenCode's architecture:

```
fin-assist          → starts server (if not running) + TUI client
fin-assist serve    → starts standalone server on 127.0.0.1:4096
fin-assist tui      → starts TUI client only (connects to existing server)
```

Server lifecycle:
- **On-demand**: TUI starts server as subprocess if not already running
- **Background**: `fin-assist serve` starts server that persists after TUI closes
- **Auth**: Optional HTTP Basic Auth via `FIN_SERVER_PASSWORD` env var

### Local-Only Security

The server binds to `127.0.0.1` by default, ensuring only local processes can communicate with agents. This is intentional — fin-assist is designed for personal use on a trusted machine.

---

## Configuration

### Config File (~/.config/fin/config.toml)

```toml
[general]
default_provider = "anthropic"
default_model = "claude-sonnet-4-6"
keybinding = "ctrl-enter"

[server]
host = "127.0.0.1"
port = 4096

[context]
max_file_size = 100000
max_history_items = 50
include_git_status = true
include_env_vars = ["PATH", "HOME", "USER", "PWD"]

[agents.shell]
enabled = true

[agents.sdd]
enabled = true
docs_only = true

[agents.tdd]
enabled = true
code_only = true

[providers.anthropic]
# API key stored separately via /connect

[providers.openrouter]
# API key stored separately via /connect

[providers.ollama]
base_url = "http://localhost:11434"
```

### Credential Storage (~/.local/share/fin/credentials.json)

Credentials stored separately from config (same as before).

---

## /connect Command Pattern

Unchanged from original design — still the provider setup flow within the TUI.

---

## Implementation Phases

### Phase 1: Repo Setup
- [x] Initialize devenv (devenv.nix, devenv.yaml)
- [x] Create pyproject.toml with dependencies
- [x] Set up justfile with common tasks
- [x] Configure treefmt.toml for formatting
- [x] Add .gitignore, .envrc
- [x] Create secretspec.toml for dev secrets
- [x] Enable branch protections (PR requirement + no force push)

### Phase 2: Core Package Structure
- [x] Create src/fin_assist/ package layout
- [x] Add GitHub Actions CI workflow (using nix shell approach)
- [x] Re-enable required status checks in branch protections
- [x] Implement config loading (config/schema.py, config/loader.py)
- [x] Set up pydantic settings

### Phase 3: LLM Module
- [x] Integrate pydantic-ai for provider abstraction
- [x] Implement Agent wrapper (llm/agent.py)
- [x] Create provider registry (llm/providers.py)
- [x] Write system prompts (llm/prompts.py)

### Phase 4: Credential Management
- [x] Implement /connect command UI (ui/connect.py)
- [x] Create credential store (credentials/store.py)
- [x] Add optional OS keyring backend (credentials/keyring.py)

### Phase 5: Context Module
- [x] Implement ContextProvider ABC (context/base.py)
- [x] File finder with find (context/files.py)
- [x] Git context gatherer (context/git.py)
- [x] Fish history parser (context/history.py)
- [x] Environment context (context/environment.py)

### Phase 6: Agent Protocol & Registry
- [x] Define `BaseAgent` ABC with `AgentResult`
- [x] Create `AgentRegistry` with decorator-based registration
- [x] Migrate current `LLMAgent` → `DefaultAgent` (chain-of-thought base)
- [x] Add explicit routing via `/shell`, `/sdd`, `/tdd` prefixes

### Phase 7: TUI Implementation
- [ ] Refactor DefaultAgent to chain-of-thought base (multi-turn via message history)
- [ ] Create Textual App (ui/app.py) with run loop
- [ ] Implement PromptInput component
- [ ] Implement AgentOutput display
- [ ] Implement AgentSelector (tabs/dropdown)
- [ ] Implement ModelSelector (provider/model dropdown)
- [ ] Wire ConnectDialog into TUI
- [ ] Add per-agent UI constraints (hide/show selectors based on capabilities)
- [ ] Config-driven agent selection (global + per-project TOML)

### Phase 8: Multiplexer Integration
- [ ] Multiplexer ABC (multiplexer/base.py)
- [ ] tmux implementation (multiplexer/tmux.py)
- [ ] zellij implementation (multiplexer/zellij.py)
- [ ] Fallback (alternate screen) (multiplexer/fallback.py)
- [ ] Launch TUI in floating pane

### Phase 9: Fish Plugin
- [ ] Create fish plugin (fish/conf.d/fin_assist.fish)
- [ ] Keybinding for TUI launch
- [ ] Command insertion (receive output, insert into command line)
- [ ] Server auto-start (launch server if not running)
- [ ] Handle `/shell`, `/sdd`, `/tdd` command prefixes

### Phase 10: Testing Infrastructure (Deep Evals)
- [ ] Set up deep evals framework (pytest-compatible)
- [ ] Define must/must-not/should criteria per agent
- [ ] Implement LLM-as-judge evaluator (default, configurable per agent)
- [ ] Create eval suite for DefaultAgent (chain-of-thought quality)
- [ ] Create eval suite for ShellAgent (command safety, correctness)
- [ ] Per-agent eval configuration

### Phase 11: CI for Evals
- [ ] GitHub Action workflow
- [ ] Trigger: post-merge to main
- [ ] Run eval suite against main branch
- [ ] Detect regressions vs previous run
- [ ] Post regression issues to GitHub

### Phase 12: SDD/TDD Agents
- [ ] Create `agents/sdd.py` (design brainstorming)
- [ ] Define `SketchResult` model
- [ ] Implement tools: `read_file`, `write_file`, `list_docs`
- [ ] Create `agents/tdd.py` (test-driven development)
- [ ] Define `TDDResult` model
- [ ] Implement tools: `read_file`, `write_file`, `run_command`, `list_files`
- [ ] Multi-turn conversation storage

### Phase 13: Skills + MCP Integration
- [ ] Skills framework (configurable behaviors per agent)
- [ ] MCP client integration
- [ ] TUI components for skill/MCP configuration
- [ ] Per-project skill/MCP configuration

### Phase 14: Documentation
- [ ] User documentation
- [ ] Installation guide
- [ ] Update architecture.md if needed

---

## Open Questions

These are decisions deferred until the relevant phase. They are noted here to avoid premature commitment.

| Question | Phase | Options | Recommendation |
|----------|-------|---------|----------------|
| Conversation storage | Phase 9 | JSON files vs SQLite | SQLite preferred for multi-turn query capability |
| Server lifecycle | Phase 9 | On-demand subprocess vs background daemon | Both supported; `fin-assist serve` for daemon mode |
| ShellAgent vs DefaultAgent | Phase 7 | Separate classes or same with config | Separate ShellAgent (specialized) |
| Deep evals criteria | Phase 10 | Must/must-not/should per agent | LLM-as-judge default, configurable |
| Per-agent UI constraints | Phase 7 | Config-driven vs runtime detection | Config-driven (agent declares capabilities) |

---

## Future Considerations

### Near-term (Phases 12-13)
- **Skills framework** — Configurable behaviors (e.g., brainstorming mode, terse mode)
- **MCP integration** — Natural language interface to configurable MCP tools/servers
- **Per-project config** — Agent/skill/MCP configuration per project via TOML

### Long-term (AI-Directed-Dev-Pipeline)
- **Web client** — HTML/JS frontend as A2A client
- **Agent-to-agent** — SDDAgent outputs decisions that TDDAgent consumes
- **Agent-to-agent handoff** — SDD→TDD workflow automation
- **Shell expansion** — bash, zsh support after fish is stable
- **Ghostty support** — when popup feature lands (upstream issue #3197)
- **Command history learning** — learn from accepted commands
- **Custom prompts** — user-defined prompt templates

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

---

## Appendix: Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| A2A over custom REST | fasta2a | Protocol-native multi-client, agent discovery, streaming built-in |
| Agents as code | Custom classes | Learning vehicle; declarative loses the interesting parts |
| Local-only server | Bind 127.0.0.1 | Personal tool, no network exposure; future opt-in |
| Server pattern | OpenCode-inspired | TUI as client, server persists; multiple clients possible |
| Conversation storage | TBD (Phase 9) | JSON for simplicity; SQLite if query/browse needed for multi-turn agents |
| Agent registry | Decorator-based | Clean, type-safe, self-registering |
| Explicit routing | Prefix commands | `/shell`, `/sdd`, `/tdd` — clear intent, no auto-detection complexity |
| DefaultAgent | Chain-of-thought base | Multi-turn capable general-purpose agent; specialized agents slot in |
| ShellAgent | Specialized | Shell command generation as one of many possible specialized agents |
| Per-agent UI | Config-driven | Agent declares capabilities; TUI adapts (hide/show selectors) |
| Testing approach | Deep evals + CI | LLM-as-judge by default, pytest-compatible, post-merge regression checks |
