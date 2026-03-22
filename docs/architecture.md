# fin-assist Architecture

## Overview

fin-assist is a terminal inline assistant for fish shell, inspired by Zed's inline assistant. It provides a TUI for natural language command generation with context injection, multi-provider LLM support, and a seamless accept/run workflow.

## Goals

- Natural language → shell command translation
- Floating panel UI (tmux/zellij) with alternate screen fallback
- `@` mention system for full project context
- Multi-provider LLM support via pydantic-ai
- Accept (edit) or Run directly workflow
- `/connect` command pattern for provider setup (like opencode)

## Non-Goals

- Shell-agnostic implementation (fish-first, generalize later)
- Real-time command suggestions (on-demand only)
- IDE/editor integration
- Ghostty multiplexer support (pending upstream feature)

---

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          fish shell                                  │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  fin-assist plugin (conf.d/functions)                         │  │
│  │  - Keybinding: ctrl-enter (configurable)                       │  │
│  │  - Captures: commandline buffer, pwd, env context              │  │
│  │  - Launches TUI, receives output                               │  │
│  │  - Inserts result into commandline                             │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    fin-assist (Python 3.12 / Textual)               │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  UI Layer (Textual widgets)                                    │ │
│  │  ┌────────────────────────────────────────────────────────────┐ │ │
│  │  │  PromptInput      - textarea with @ mention trigger        │ │ │
│  │  │  ModelSelector     - dropdown for provider/model           │ │ │
│  │  │  ContextPreview    - shows added context items             │ │ │
│  │  │  ActionButtons     - [Accept] [Run]                         │ │ │
│  │  │  ConnectDialog     - /connect provider setup UI             │ │ │
│  │  └────────────────────────────────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Context Module                                                │ │
│  │  - FileFinder: fd + fzf for file fuzzy search                  │ │
│  │  - GitContext: git diff/log/status for recent changes          │ │
│  │  - ShellHistory: parse fish history for context                │ │
│  │  - Environment: cwd, relevant env vars                        │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  LLM Module (pydantic-ai)                                      │ │
│  │  - Agent: Unified interface for all providers                  │ │
│  │  - FallbackModel: Automatic failover between models            │ │
│  │  - ProviderRegistry: Anthropic, OpenRouter, Ollama, etc.      │ │
│  │  - PromptBuilder: Constructs system/user prompts              │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Credential Module                                             │ │
│  │  - CredentialStore: Secure storage in ~/.local/share/fin/      │ │
│  │  - KeyringBackend: Optional OS keyring integration             │ │
│  │  - ConnectCommand: TUI flow for adding providers               │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  Multiplexer Integration                            │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  tmux                                                           ││
│  │  - Detection: check $TMUX env var                              ││
│  │  - FloatingPane: display-popup command                         ││
│  │  - ContextCapture: capture-pane for terminal content           ││
│  └─────────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  zellij                                                         ││
│  │  - Detection: check $ZELLIJ_SESSION_NAME env var               ││
│  │  - FloatingPane: plugin --floating command                     ││
│  │  - Context: Limited (no capture-pane equivalent)              ││
│  └─────────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  ghostty (future)                                              ││
│  │  - Detection: check $GHOSTTY_SESSION env var                   ││
│  │  - Status: Pending upstream popup support (issue #3197)       ││
│  │  - Fallback: Alternate screen buffer                           ││
│  └─────────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  Fallback (no multiplexer)                                     ││
│  │  - Alternate screen buffer (like fzf, lazygit)                 ││
│  │  - No context capture available                                ││
│  └─────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User presses ctrl-enter
         │
         ▼
┌─────────────────────┐
│ Fish plugin         │
│ - Get commandline   │
│ - Get pwd, env      │
│ - Launch fin-assist │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ Detect multiplexer  │
│ tmux → floating     │
│ zellij → floating    │
│ none → alt screen    │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ Textual TUI runs    │
│ - User types prompt │
│ - Adds @ context    │
│ - Selects model     │
│ - Clicks Accept/Run │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ pydantic-ai Agent   │
│ generates command   │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ Output to stdout    │
│ Format: JSON        │
│ {command, action}   │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ Fish plugin         │
│ - Parse output      │
│ - Insert command    │
│ - If Run: execute   │
│ - If Accept: edit   │
└─────────────────────┘
```

---

## Directory Structure

```
fin-assist/
├── src/
│   └── fin_assist/
│       ├── __init__.py
│       ├── __main__.py              # Entry point
│       ├── app.py                   # Textual App class
│       ├── ui/
│       │   ├── __init__.py
│       │   ├── prompt_input.py      # PromptInput widget
│       │   ├── model_selector.py
│       │   ├── context_preview.py
│       │   ├── actions.py
│       │   └── connect.py           # /connect dialog
│       ├── context/
│       │   ├── __init__.py
│       │   ├── base.py              # ContextProvider ABC
│       │   ├── files.py             # FileFinder
│       │   ├── git.py               # GitContext
│       │   ├── history.py           # ShellHistory
│       │   └── environment.py
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── agent.py             # pydantic-ai Agent wrapper
│       │   ├── providers.py         # Provider registry
│       │   └── prompts.py           # System prompts
│       ├── credentials/
│       │   ├── __init__.py
│       │   ├── store.py             # Credential storage
│       │   └── keyring.py           # OS keyring backend
│       ├── multiplexer/
│       │   ├── __init__.py
│       │   ├── base.py              # Multiplexer ABC
│       │   ├── tmux.py
│       │   ├── zellij.py
│       │   └── fallback.py
│       └── config/
│           ├── __init__.py
│           ├── loader.py            # Load config.toml
│           └── schema.py            # Config dataclasses
├── fish/
│   ├── conf.d/
│   │   └── fin_assist.fish         # Auto-load config
│   └── functions/
│       └── fin_assist.fish         # Main function
├── tests/
│   ├── unit/
│   └── integration/
├── pyproject.toml
├── justfile
├── devenv.nix
├── devenv.yaml
├── flake.nix
├── treefmt.toml
├── .envrc
├── .gitignore
├── secretspec.toml
└── docs/
    └── architecture.md
```

---

## Configuration

### Config File (~/.config/fin/config.toml)

```toml
[general]
default_provider = "anthropic"
default_model = "claude-sonnet-4-5"
keybinding = "ctrl-enter"

[context]
max_file_size = 100000
max_history_items = 50
include_git_status = true
include_env_vars = ["PATH", "HOME", "USER", "PWD"]

[providers.anthropic]
# API key stored separately via /connect command

[providers.openrouter]
# API key stored separately via /connect command

[providers.ollama]
base_url = "http://localhost:11434"
# No API key needed for local Ollama
```

### Credential Storage (~/.local/share/fin/credentials.json)

Credentials are stored separately from config, allowing config to be shared/committed without exposing secrets.

```json
{
  "anthropic": {
    "api_key": "encrypted:...",
    "created_at": "2026-03-22T10:00:00Z"
  },
  "openrouter": {
    "api_key": "encrypted:...",
    "created_at": "2026-03-22T10:05:00Z"
  }
}
```

**Security options:**
1. **Default**: Encrypted file storage in `~/.local/share/fin/`
2. **Optional**: OS keyring via `keyring` library (macOS Keychain, Linux Secret Service, Windows Credential Manager)
3. **Environment variables**: Also supported for CI/headless environments

---

## /connect Command Pattern

Inspired by opencode's `/connect` command:

```
/connect
         │
         ▼
┌─────────────────────────────────────────┐
│  Provider Selector (fuzzy searchable)   │
│  ┌─────────────────────────────────────┐│
│  │  ○ Anthropic                        ││
│  │  ○ OpenRouter                       ││
│  │  ○ OpenAI                           ││
│  │  ○ Ollama (local)                   ││
│  │  ○ Groq                             ││
│  │  ○ Other...                         ││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Auth Method (if applicable)           │
│  ┌─────────────────────────────────────┐│
│  │  ● Enter API Key                    ││
│  │  ○ OAuth (if supported)             ││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  API Key Input (masked)                 │
│  ┌─────────────────────────────────────┐│
│  │  API key: **************            ││
│  │                                     ││
│  │  [Cancel]              [Save]       ││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Model Selection                        │
│  /models to select default model        │
└─────────────────────────────────────────┘
```

---

## Key Interfaces

### LLM Module (pydantic-ai)

```python
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

# Simple usage - provider auto-detected from model name
agent = Agent('anthropic:claude-sonnet-4-5')

# With fallback
primary = AnthropicModel('claude-sonnet-4-5')
fallback = OpenAIChatModel('gpt-4o', provider=OpenRouterProvider())
agent = Agent(FallbackModel(primary, fallback))

# Generate command
result = agent.run_sync(prompt, context=context_items)
command = result.output
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
```

### Multiplexer Interface

```python
from abc import ABC, abstractmethod

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

## System Prompt

```
You are a shell command assistant. Given a user's natural language request and context, generate a single shell command.

Rules:
1. Output ONLY the command, no explanation
2. Use fish shell syntax
3. Consider the provided context (files, git state, history)
4. If uncertain, prefer safer commands
5. Use pipes and redirects appropriately
6. For dangerous operations (rm, dd, mkfs), warn the user

Context:
{context}

User request:
{prompt}

Command:
```

---

## Repo Setup

### Dependencies

| Category | Tool/Library | Purpose |
|----------|--------------|---------|
| **Language** | Python 3.12+ | Runtime (3.13 in nixos-unstable) |
| **Package Mgmt** | uv | Fast Python package installer |
| **TUI Framework** | Textual | Terminal UI widgets |
| **LLM Abstraction** | pydantic-ai | Multi-provider LLM interface |
| **Config Parsing** | tomli | TOML parsing |
| **Data Validation** | pydantic | Settings/models |
| **HTTP Client** | httpx | Async HTTP (via pydantic-ai) |
| **Shell Integration** | fish 3.2+ | Primary target shell |
| **Secrets (dev)** | secretspec | Local development secrets |

### Dev Environment (devenv.nix)

```nix
{ pkgs, ... }:
{
  packages = with pkgs; [
    # Nix
    nixfmt
    nil

    # Python
    python312
    uv
    ruff

    # General
    just
    jq
    treefmt
    secretspec

    # Optional runtimes for testing
    fd
    fzf
    git
  ];

  git-hooks.hooks = {
    treefmt.enable = true;

    ruff-check = {
      enable = true;
      name = "ruff-check";
      description = "Lint Python code with ruff";
      entry = "${pkgs.ruff}/bin/ruff check src/";
      language = "system";
      types = [ "python" ];
      pass_filenames = false;
    };

    ruff-format = {
      enable = true;
      name = "ruff-format";
      description = "Format Python code with ruff";
      entry = "${pkgs.ruff}/bin/ruff format --check src/";
      language = "system";
      types = [ "python" ];
      pass_filenames = false;
    };

    ty-check = {
      enable = true;
      name = "ty-typecheck";
      description = "Type-check with ty";
      entry = "${pkgs.uv}/bin/uv run ty check src/";
      language = "system";
      types = [ "python" ];
      pass_filenames = false;
    };
  };

  enterShell = ''
    echo "fin-assist dev shell"
  '';
}
```

### pyproject.toml

```toml
[project]
name = "fin-assist"
version = "0.1.0"
description = "Terminal inline assistant for fish shell"
requires-python = ">=3.12"
dependencies = [
    "textual>=3.0",
    "pydantic-ai>=0.1",
    "pydantic-settings>=2.0",
    "tomli>=2.0",
    "httpx>=0.27",
    "keyring>=25.0",  # Optional OS keyring support
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.25",
    "ruff>=0.9",
    "ty>=0.0.0a1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/fin_assist"]

[tool.ruff]
target-version = "py312"
line-length = 100
src = ["src"]

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "UP",  # pyupgrade
    "B",   # flake8-bugbear
    "SIM", # flake8-simplify
    "TCH", # flake8-type-checking
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"
```

### justfile

```just
# fin-assist task runner

set dotenv-load := false
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# ── Dev shell ────────────────────────────────────────────────────────────────

dev:
    nix develop

# ── Code quality ─────────────────────────────────────────────────────────────

fmt:
    treefmt

check:
    treefmt --ci
    nix flake check

lint:
    uv run ruff check src/

typecheck:
    uv run ty check src/

test:
    uv run pytest tests/

ci: lint typecheck test

# ── Local dev ────────────────────────────────────────────────────────────────

# Run the TUI directly (for testing)
run:
    uv run python -m fin_assist

# Install fish plugin locally
install-fish:
    mkdir -p ~/.config/fish/conf.d
    mkdir -p ~/.config/fish/functions
    cp fish/conf.d/fin_assist.fish ~/.config/fish/conf.d/
    cp fish/functions/fin_assist.fish ~/.config/fish/functions/

# ── Secrets ──────────────────────────────────────────────────────────────────

secrets-check:
    secretspec check

secrets-run *args:
    secretspec run -- {{ args }}
```

### .gitignore

```gitignore
# Nix
result
result-*
.direnv/
.devenv/

# Generated by devenv git-hooks
.pre-commit-config.yaml

# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
.venv/
.eggs/

# Editor
*.swp
*.swo
*~
.idea/
.vscode/

# OS
.DS_Store
Thumbs.db

# Secrets
.env.local
*.age
!secrets/*.age

# Local config overrides
config.local.toml
```

### secretspec.toml

```toml
[project]
name = "fin-assist"
revision = "1.0"

[profiles.dev]
ANTHROPIC_API_KEY = { description = "Anthropic API key for development" }
OPENROUTER_API_KEY = { description = "OpenRouter API key for development", required = false }
```

### GitHub Actions CI

```yaml
# .github/workflows/ci.yml
name: CI

on:
  pull_request:
    branches: [main]
    paths-ignore:
      - "docs/**"
      - "*.md"

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  format:
    name: Check formatting
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: DeterminateSystems/nix-installer-action@main
      - uses: DeterminateSystems/magic-nix-cache-action@main
      - run: nix fmt -- --ci

  lint:
    name: Lint & typecheck
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: DeterminateSystems/nix-installer-action@main
      - uses: DeterminateSystems/magic-nix-cache-action@main
      - run: |
          nix shell nixpkgs#uv nixpkgs#ruff --command bash -c "
            uv sync --all-extras
            ruff check src/
            uv run ty check src/
          "

  test:
    name: Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: DeterminateSystems/nix-installer-action@main
      - uses: DeterminateSystems/magic-nix-cache-action@main
      - run: |
          nix shell nixpkgs#uv --command bash -c "
            uv sync --all-extras
            uv run pytest tests/ -x --tb=short
          "
```

### Branch Protections

Configure in GitHub repo settings:

- **Require PR before merge**: Yes
- **Require CI checks to pass**: format, lint, test
- **No force push to main**: Enabled
- **Require linear history**: Optional (prefer squash merge)

---

## Implementation Phases

### Phase 1: Repo Setup
- [ ] Initialize devenv (flake.nix, devenv.nix, devenv.yaml)
- [ ] Create pyproject.toml with dependencies
- [ ] Set up justfile with common tasks
- [ ] Configure treefmt.toml for formatting
- [ ] Add .gitignore, .envrc
- [ ] Create secretspec.toml for dev secrets
- [ ] Add GitHub Actions CI workflow
- [ ] Enable branch protections

### Phase 2: Core Package Structure
- [ ] Create src/fin_assist/ package layout
- [ ] Implement config loading (config/schema.py, config/loader.py)
- [ ] Set up pydantic settings

### Phase 3: LLM Module
- [ ] Integrate pydantic-ai for provider abstraction
- [ ] Implement Agent wrapper (llm/agent.py)
- [ ] Create provider registry (llm/providers.py)
- [ ] Write system prompts (llm/prompts.py)

### Phase 4: Credential Management
- [ ] Implement /connect command UI (ui/connect.py)
- [ ] Create credential store (credentials/store.py)
- [ ] Add optional OS keyring backend (credentials/keyring.py)

### Phase 5: Context Module
- [ ] Implement ContextProvider ABC (context/base.py)
- [ ] File finder with fd/fzf (context/files.py)
- [ ] Git context gatherer (context/git.py)
- [ ] Fish history parser (context/history.py)
- [ ] Environment context (context/environment.py)

### Phase 6: UI Layer
- [ ] Create Textual App (app.py)
- [ ] Prompt input with @ mentions (ui/prompt_input.py)
- [ ] Model selector dropdown (ui/model_selector.py)
- [ ] Context preview panel (ui/context_preview.py)
- [ ] Action buttons (ui/actions.py)

### Phase 7: Multiplexer Integration
- [ ] Multiplexer ABC (multiplexer/base.py)
- [ ] tmux implementation (multiplexer/tmux.py)
- [ ] zellij implementation (multiplexer/zellij.py)
- [ ] Fallback (alternate screen) (multiplexer/fallback.py)

### Phase 8: Fish Plugin
- [ ] Create fish/conf.d/fin_assist.fish
- [ ] Create fish/functions/fin_assist.fish
- [ ] Wire up keybinding
- [ ] Handle command insertion

### Phase 9: Testing & Documentation
- [ ] Unit tests for each module
- [ ] Integration tests for full flow
- [ ] User documentation
- [ ] Installation guide

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| LLM generates dangerous commands | System prompt warns; UI shows confirmation for rm/dd/mkfs |
| Context too large for API | Truncate/summarize; configurable limits |
| tmux/zellij not available | Fallback to alternate screen buffer |
| Fish version incompatibility | Target fish 3.2+ (current stable) |
| API key exposure | Separate credential storage; optional keyring; never log |
| pydantic-ai API changes | Pin version; abstract in llm/agent.py |

---

## Future Considerations

- **Shell expansion**: bash, zsh support after fish is stable
- **Ghostty support**: When popup feature lands (issue #3197)
- **Command history learning**: Learn from accepted commands
- **Custom prompts**: User-defined prompt templates
- **Team sharing**: Share provider configs (not keys) via dotfiles
