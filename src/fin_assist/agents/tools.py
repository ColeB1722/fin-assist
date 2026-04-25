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
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass
class ApprovalPolicy:
    """Platform-level approval specification.  Framework-agnostic.

    Lives on ``ToolDefinition``.  The backend enforces it (emits
    ``deferred`` StepEvents for gated tools).  The Executor verifies
    compliance (defense in depth — logs a warning if a ``tool_result``
    arrives for a tool that should have been deferred).

    Backends adapt this to their framework's approval mechanism:
    pydantic-ai → ``requires_approval=True`` / ``ApprovalRequired`` /
    ``approval_required()`` toolset wrapper.  Future backends map to
    their own mechanism (LangGraph ``interrupt()``, etc.).
    """

    mode: Literal["never", "always", "conditional"]
    condition: Callable[[str, dict[str, Any]], bool] | None = None
    reason: str | None = None


@dataclass
class DeferredToolCall:
    """A tool call that was deferred pending human approval.

    Carried in the ``deferred`` StepEvent's content and in the deferred
    artifact metadata.  Serializable for A2A transport.
    """

    tool_name: str
    tool_call_id: str
    args: dict[str, Any]
    reason: str | None = None


@dataclass
class ApprovalDecision:
    """Client's decision on a deferred tool call.

    Sent back via ``approval_result`` Part metadata when resuming an
    A2A task that was paused for approval.
    """

    tool_call_id: str
    approved: bool
    override_args: dict[str, Any] | None = None
    denial_reason: str | None = None


@dataclass
class ToolDefinition:
    """A platform-level tool definition.  Framework-agnostic.

    The ``callable`` is the function the backend will invoke when the model
    calls this tool.  It may be sync or async and must return a string.

    ``parameters_schema`` is a JSON Schema object describing the tool's
    parameters.  Backends use this to register the tool with their
    framework (e.g., pydantic-ai derives ``Tool`` from it).

    ``approval_policy`` declares whether the tool requires human approval.
    ``None`` means no gate required — the tool is safe to execute without
    human approval (equivalent to ``ApprovalPolicy(mode="never")``).
    """

    name: str
    description: str
    callable: Callable[..., Awaitable[str] | str]
    parameters_schema: dict[str, Any]
    approval_policy: ApprovalPolicy | None = None


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
    approval.  The ``run_shell`` tool requires approval for every call.
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

    registry.register(
        ToolDefinition(
            name="run_shell",
            description=(
                "Execute a shell command and return its output. "
                "Requires user approval before execution."
            ),
            callable=_run_shell,
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute.",
                    },
                },
                "required": ["command"],
            },
            approval_policy=ApprovalPolicy(
                mode="always",
                reason="Shell command execution requires approval",
            ),
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


async def _run_shell(command: str) -> str:
    import subprocess

    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR: {result.stderr}"
        if result.returncode != 0:
            output += f"\nExit code: {result.returncode}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after 30 seconds: {command}"
    except Exception as e:
        return f"Error executing command: {e}"
