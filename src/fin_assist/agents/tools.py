"""Platform-level tool registry and definition types.

These types are framework-agnostic — they live in the ``agents/`` package
alongside ``AgentSpec`` and have **zero** imports from any LLM framework.
Backends adapt platform tool definitions to their framework's registration
mechanism (e.g., pydantic-ai's ``Tool`` dataclass or ``@agent.tool``
decorator).

Tools are **shareable between agents** — agents opt in via config
(``tools = ["read_file", "git_diff"]``).  The registry is global; each
agent's ``AgentSpec`` references tool names, and the backend registers
only the tools the agent needs.

MCP integration (#84): A future ``MCPToolset`` would wrap an MCP client
and register discovered tools into the ``ToolRegistry`` with appropriate
schemas and approval policies.  The platform abstraction doesn't need to
know about MCP — it's just another tool source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass
class ToolDefinition:
    """A platform-level tool definition.  Framework-agnostic.

    The ``callable`` is the function the backend will invoke when the model
    calls this tool.  It may be sync or async and must return a string.

    ``parameters_schema`` is a JSON Schema object describing the tool's
    parameters.  Backends use this to register the tool with their
    framework (e.g., pydantic-ai derives ``Tool`` from it).

    ``approval_policy`` is reserved for Phase C (HITL).  ``None`` means
    no gate required — the tool is safe to execute without human approval.
    """

    name: str
    description: str
    callable: Callable[..., Awaitable[str] | str]
    parameters_schema: dict[str, Any]
    approval_policy: Any | None = None


class ToolRegistry:
    """Global registry of tool definitions.  Shared across all agents.

    Tools are registered once (at startup or on first import) and looked
    up by name.  The registry is a singleton-by-convention — create one
    instance and pass it where needed.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool '{definition.name}' is already registered")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get_for_agent(self, tool_names: list[str]) -> list[ToolDefinition]:
        """Resolve a list of tool names to ``ToolDefinition`` instances.

        Unknown names are silently skipped so that config can reference
        tools that aren't available in the current environment.
        """
        return [self._tools[n] for n in tool_names if n in self._tools]


def create_default_registry() -> ToolRegistry:
    """Create a ``ToolRegistry`` pre-loaded with built-in context tools.

    The built-in tools wrap existing ``ContextProvider`` classes as
    model-driven tool callables.  They are read-only and require no
    approval.
    """
    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            name="read_file",
            description=(
                "Read a file and return its contents. "
                "Use this to inspect source code, config files, or any text file."
            ),
            callable=_read_file,
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Path to the file to read. "
                            "Can be absolute or relative to the current working directory."
                        ),
                    },
                },
                "required": ["path"],
            },
        )
    )

    registry.register(
        ToolDefinition(
            name="git_diff",
            description="Show unstaged and staged changes in the current git repository.",
            callable=_git_diff,
            parameters_schema={
                "type": "object",
                "properties": {},
            },
        )
    )

    registry.register(
        ToolDefinition(
            name="git_log",
            description="Show recent git commit history (last 10 commits).",
            callable=_git_log,
            parameters_schema={
                "type": "object",
                "properties": {},
            },
        )
    )

    registry.register(
        ToolDefinition(
            name="shell_history",
            description="Show recent shell command history from the user's fish shell.",
            callable=_shell_history,
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional filter to search for specific commands.",
                    },
                },
            },
        )
    )

    return registry


async def _read_file(path: str) -> str:
    from fin_assist.context.files import FileFinder

    finder = FileFinder()
    item = finder.get_item(path)
    if item.status != "available":
        return f"Error reading file '{path}': {item.error_reason}"
    return item.content


async def _git_diff() -> str:
    from fin_assist.context.git import GitContext

    ctx = GitContext()
    item = ctx.get_item("git_diff:diff")
    if item.status != "available":
        return f"Error getting git diff: {item.error_reason}"
    return item.content


async def _git_log() -> str:
    from fin_assist.context.git import GitContext

    ctx = GitContext()
    item = ctx.get_item("git_log:log")
    if item.status != "available":
        return f"Error getting git log: {item.error_reason}"
    return item.content


async def _shell_history(query: str = "") -> str:
    from fin_assist.context.history import ShellHistory

    history = ShellHistory()
    items = history.search(query) if query else history.get_all()
    if not items:
        return "No shell history available."
    return "\n".join(item.content for item in items)
