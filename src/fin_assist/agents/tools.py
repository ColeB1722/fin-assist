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

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fin_assist.config.schema import ContextSettings


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

    Only two modes exist today: ``"always"`` (every call is gated) and
    ``"never"`` (no gate — equivalent to ``approval_policy=None``).  A
    predicate-based ``"conditional"`` mode was considered but cut because
    (a) nothing used it, (b) per-call predicates would require wrapping
    the tool callable with framework-specific exceptions, breaking the
    "platform types have zero framework imports" invariant, and (c) the
    UX problem it was meant to solve (remember approval for a session) is
    better handled client-side as session state.  Revisit if a real
    server-side use case appears.
    """

    mode: Literal["never", "always"]
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


def create_default_registry(
    context_settings: ContextSettings | None = None,
) -> ToolRegistry:
    """Create a ``ToolRegistry`` pre-loaded with built-in context tools.

    The built-in tools wrap existing ``ContextProvider`` classes as
    model-driven tool callables.  They are read-only and require no
    approval.  The ``run_shell`` tool requires approval for every call.

    ``context_settings`` is forwarded to provider constructors so tool
    callables respect the same limits as the user-driven context path.
    """
    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            name="read_file",
            description=(
                "Read a file and return its contents. "
                "Use this to inspect source code, config files, or any text file."
            ),
            callable=_make_read_file(context_settings),
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
            callable=_make_git_diff(context_settings),
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
            callable=_make_git_log(context_settings),
            parameters_schema={
                "type": "object",
                "properties": {},
            },
        )
    )

    registry.register(
        ToolDefinition(
            name="shell_history",
            description="Show recent shell command history.",
            callable=_make_shell_history(context_settings),
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


def _make_read_file(settings: ContextSettings | None):
    async def _read_file(path: str) -> str:
        from fin_assist.context.files import FileFinder

        finder = FileFinder(settings=settings)
        item = await asyncio.to_thread(finder.get_item, path)
        if item.status != "available":
            return f"Error reading file '{path}': {item.error_reason}"
        return item.content

    return _read_file


def _make_git_diff(settings: ContextSettings | None):
    async def _git_diff() -> str:
        from fin_assist.context.git import GitContext

        ctx = GitContext(settings=settings)
        item = await asyncio.to_thread(ctx.get_item, "git_diff:diff")
        if item.status != "available":
            return f"Error getting git diff: {item.error_reason}"
        return item.content

    return _git_diff


def _make_git_log(settings: ContextSettings | None):
    async def _git_log() -> str:
        from fin_assist.context.git import GitContext

        ctx = GitContext(settings=settings)
        item = await asyncio.to_thread(ctx.get_item, "git_log:log")
        if item.status != "available":
            return f"Error getting git log: {item.error_reason}"
        return item.content

    return _git_log


def _make_shell_history(settings: ContextSettings | None):
    async def _shell_history(query: str = "") -> str:
        from fin_assist.context.history import ShellHistory

        history = ShellHistory(settings=settings)
        if query:
            items = await asyncio.to_thread(history.search, query)
        else:
            items = await asyncio.to_thread(history.get_all)
        if not items:
            return "No shell history available."
        return "\n".join(item.content for item in items)

    return _shell_history


_RUN_SHELL_TIMEOUT_SECONDS = 30


async def _run_shell(command: str) -> str:
    """Execute a shell command via asyncio-native subprocess.

    Uses ``asyncio.create_subprocess_shell`` (not ``subprocess.run`` in a
    thread) so that cancelling the parent task terminates the child
    process instead of leaking a running subprocess into the thread pool.

    On ``CancelledError`` (e.g., A2A task cancel plumbed through to the
    backend coroutine) we ``terminate()`` the child and re-raise so the
    cancellation isn't swallowed.  On timeout we also terminate and
    return a user-visible message.
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:  # noqa: BLE001 — surface any spawn failure as tool output
        return f"Error executing command: {e}"

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=_RUN_SHELL_TIMEOUT_SECONDS
        )
    except TimeoutError:
        await _terminate_and_wait(proc)
        return f"Command timed out after {_RUN_SHELL_TIMEOUT_SECONDS} seconds: {command}"
    except asyncio.CancelledError:
        await _terminate_and_wait(proc)
        raise
    except Exception as e:  # noqa: BLE001 — surface unexpected I/O errors as tool output
        await _terminate_and_wait(proc)
        return f"Error executing command: {e}"

    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")
    output = stdout
    if stderr:
        output += f"\nSTDERR: {stderr}"
    if proc.returncode != 0:
        output += f"\nExit code: {proc.returncode}"
    return output or "(no output)"


async def _terminate_and_wait(proc: asyncio.subprocess.Process) -> None:
    """Best-effort terminate + reap of an asyncio subprocess."""
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=2)
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=1)
        except TimeoutError:
            return
