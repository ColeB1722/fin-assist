# Configuration

fin-assist is config-driven: agent behavior, providers, skills, and tool approval policies are all declared in TOML. New agents are config entries, not new Python classes.

## File discovery

Config is loaded from the first available location:

1. Explicit path (API parameter)
2. `FIN_CONFIG_PATH` environment variable
3. `./config.toml` (project-local override in current working directory)
4. `~/.config/fin/config.toml` (user default)

Source precedence (highest first): init args → env (`FIN_*`) → TOML → defaults.

## Env var naming

See [`AGENTS.md`](../AGENTS.md#env-var-naming-convention) for the full convention. Summary:

- `FIN_<NAME>` (single underscore) — bootstrap vars read with `os.environ.get()` before pydantic loads (e.g. `FIN_DATA_DIR`).
- `FIN_<SECTION>__<FIELD>` (double underscore) — pydantic-settings nested config (e.g. `FIN_GENERAL__DEFAULT_MODEL`, `FIN_SERVER__PORT`).

## Example config

```toml
[general]
default_provider = "anthropic"
default_model = "claude-sonnet-4-6"
default_agent = "test"

[server]
host = "127.0.0.1"
port = 4096
db_path = "hub.db"              # relative to FIN_DATA_DIR

[providers.anthropic]
# API key stored separately in credentials

[providers.openrouter]
# API key stored separately in credentials

[providers.ollama]
base_url = "http://localhost:11434"

[agents.test]
description = "Development test agent with file, shell, and git tools."
system_prompt = "test"
output_type = "text"
thinking = "medium"
serving_modes = ["do", "talk"]

[agents.test.skills.files]
description = "Read files from the workspace."
tools = ["read_file"]

[agents.test.skills.git]
description = "Git commands with per-subcommand approval."
tools = ["git"]

[agents.test.tool_policies.git]
default = "always"
rules = [
  { pattern = "git diff*", mode = "never" },
  { pattern = "git status*", mode = "never" },
  { pattern = "git log*", mode = "never" },
]

[agents.test.skills.shell]
description = "Execute arbitrary shell commands (requires approval)."
tools = ["run_shell"]
```

## Agent config schema

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `description` | str | `""` | Human-readable description, surfaced in the agent card |
| `system_prompt` | str | `"chain-of-thought"` | Key into `SYSTEM_PROMPTS` registry |
| `output_type` | str | `"text"` | Key into `OUTPUT_TYPES` registry (`"text"` → `str`, `"command"` → `CommandResult`) |
| `thinking` | `"off"`/`"low"`/`"medium"`/`"high"` or null | `"medium"` | Pydantic-AI thinking effort; `"off"` disables, `null` inherits from `[general]` |
| `serving_modes` | list[`"do"`/`"talk"`] | `["do", "talk"]` | Which CLI modes this agent supports |
| `enabled` | bool | true | Whether to mount this agent in the hub |
| `base_tools` | list[str] | `[]` | Always-available tools (opt in via config or skills) |
| `skills` | dict[str, SkillConfig] | `{}` | Per-skill config (see [`docs/skills.md`](skills.md)) |
| `tool_policies` | dict[str, ToolPolicyConfig] | `{}` | Per-tool approval policy (agent-level, not per-skill) |

## Tool approval policies

Policies are defined at the **agent level**, keyed by tool name. Each tool has exactly one policy — no merge conflicts when multiple skills reference the same tool.

```toml
[agents.git.tool_policies.git]
default = "always"        # require approval for any git invocation by default
rules = [
  { pattern = "git diff*",   mode = "never" },   # but auto-approve diff/status/log
  { pattern = "git status*", mode = "never" },
  { pattern = "git log*",    mode = "never" },
]
```

`ApprovalPolicy.evaluate(args)` checks `rules` in first-match order; if no rule matches, `default` applies. See [`docs/skills.md`](skills.md#approval-rules) for the full evaluation flow and v0.1 limitations.

## Provider config

```toml
[providers.<name>]
base_url = "..."           # optional; defaults vary per provider
# API keys live in credentials, not config
```

The `[providers.*]` section is read by `AgentSpec` (which exposes `get_api_key(provider)` and `get_base_url(provider)` to the backend). `ProviderRegistry` (in `llm/model_registry.py`) is a stateless factory: `create_model(provider, model, api_key=..., base_url=...)` — the spec resolves credentials and passes them through per call.

## Credential storage

Credentials are stored separately from config (so config can be checked into a dotfiles repo without leaking secrets). Default path: `$FIN_DATA_DIR/credentials.json` with `0600` permissions.

Lookup chain (highest precedence first):

1. Environment variable (e.g. `ANTHROPIC_API_KEY`)
2. Credentials file (`credentials.json`)
3. OS keyring (if `keyring` is installed and a key is stored)

Today, set credentials by either exporting the env var (`export ANTHROPIC_API_KEY=...`) or hand-editing `$FIN_DATA_DIR/credentials.json` (a flat `{"anthropic": "sk-..."}` JSON object). An interactive `/connect` setup command is planned — see [#124](https://github.com/ColeB1722/fin-assist/issues/124).

## Runtime paths

All runtime state derives from `FIN_DATA_DIR`. Platform defaults (from [`paths.py`](../src/fin_assist/paths.py)):

- **Linux/macOS:** `~/.local/share/fin/` (XDG convention)
- **Windows:** `%LOCALAPPDATA%\fin` (falls back to `~` if `LOCALAPPDATA` is unset)

For local development, set `FIN_DATA_DIR=./.fin` to keep state colocated with the repo. See [`AGENTS.md`](../AGENTS.md#local-development-paths) for the full table of paths.
