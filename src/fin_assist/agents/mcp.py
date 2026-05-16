"""MCP (Model Context Protocol) tool provider integration.

MCPToolProvider connects to external MCP servers and exposes their tools
through the platform's ToolRegistry, with namespaced identifiers and
annotation-aware approval policies.

Architecture
~~~~~~~~~~~~
- One MCPToolProvider per configured MCP server
- Provider name: ``mcp-<server>`` (e.g. ``mcp-memory``)
- Tool names: ``mc p.<server>.<<tool>`` (e.g. ``mc p.memory.add_note``)
- Eager connect at startup via ``discover()``
- Session stays alive for the lifetime of the provider
- Tool callables delegate to ``session.call_tool()``

Approval policy mapping (#141)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
MCP ``ToolAnnotations`` are mapped to ``ApprovalPolicy`` during discovery::

    readOnlyHint=true        → ApprovalPolicy(mode="never")
    destructiveHint=true     → ApprovalPolicy(mode="always")
    no annotations           → ApprovalPolicy(mode="always")  # conservative

Agent-level ``tool_policies`` in config still override everything.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from mcp.client.session import ClientSession
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as MCPTool

from fin_assist.agents.tools import ApprovalPolicy, ToolDefinition

if TYPE_CHECKING:
    from fin_assist.config.schema import MCPServerConfig


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from sync code, handling nested event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


def _annotations_to_policy(annotations: Any | None) -> ApprovalPolicy:
    """Map MCP ToolAnnotations to platform ApprovalPolicy.

    Defaults are conservative: no annotations → always require approval.
    """
    if annotations is None:
        return ApprovalPolicy(
            mode="always",
            description="MCP: no annotations — conservative default",
        )

    # ToolAnnotations is a pydantic model with optional boolean fields.
    # Some SDKs may return a dict instead, so handle both shapes.
    if isinstance(annotations, dict):
        read_only = annotations.get("readOnlyHint", False)
        destructive = annotations.get("destructiveHint", True)
    else:
        read_only = getattr(annotations, "readOnlyHint", False)
        destructive = getattr(annotations, "destructiveHint", True)

    if read_only:
        return ApprovalPolicy(
            mode="never",
            description="MCP: read-only hint",
        )
    if destructive:
        return ApprovalPolicy(
            mode="always",
            description="MCP: destructive hint",
        )

    # Non-destructive write (additive only)
    return ApprovalPolicy(
        mode="always",
        description="MCP: non-destructive write hint",
    )


def _extract_tool_result_text(result: CallToolResult) -> str:
    """Extract plain text from an MCP CallToolResult."""
    texts: list[str] = []
    for item in result.content:
        if isinstance(item, TextContent):
            texts.append(item.text)
    if texts:
        return "\n".join(texts)
    # Fallback: string representation of structured or non-text content
    return str(result.content)


class MCPToolProvider:
    """Connects to a single MCP server and registers its tools."""

    def __init__(self, server_name: str, server_config: MCPServerConfig) -> None:
        self._server_name = server_name
        self._config = server_config
        self._cm: Any | None = None
        self._session: ClientSession | None = None
        self._tools: list[ToolDefinition] = []

    @property
    def name(self) -> str:
        return f"mcp-{self._server_name}"

    def discover(self) -> list[ToolDefinition]:
        if self._tools:
            return self._tools
        _run_async(self._connect_and_discover())
        return self._tools

    async def _connect_and_discover(self) -> None:
        await self._connect()
        assert self._session is not None
        result = await self._session.list_tools()
        self._tools = self._map_tools(result.tools)

    async def _connect(self) -> None:
        if self._session is not None:
            return

        if self._config.transport == "stdio":
            from mcp.client.stdio import StdioServerParameters, stdio_client

            assert self._config.command is not None, "stdio transport requires command"
            params = StdioServerParameters(
                command=self._config.command,
                args=self._config.args,
                env=self._config.env or None,
            )
            self._cm = stdio_client(params)
            read, write = await self._cm.__aenter__()
        else:  # sse
            from mcp.client.sse import sse_client

            assert self._config.url is not None, "sse transport requires url"
            self._cm = sse_client(
                self._config.url,
                headers=self._config.headers or None,
            )
            read, write = await self._cm.__aenter__()

        self._session = ClientSession(read, write)
        await self._session.initialize()

    def _map_tools(self, mcp_tools: list[MCPTool]) -> list[ToolDefinition]:
        prefix = f"mcp.{self._server_name}."
        return [
            ToolDefinition(
                name=f"{prefix}{tool.name}",
                description=tool.description or "",
                callable=self._make_callable(tool.name),
                parameters_schema=tool.inputSchema,
                approval_policy=_annotations_to_policy(tool.annotations),
            )
            for tool in mcp_tools
        ]

    def _make_callable(self, tool_name: str):
        async def _invoke(**kwargs: Any) -> str:
            if self._session is None:
                raise RuntimeError("MCP session not connected")
            async with asyncio.timeout(self._config.timeout):
                result = await self._session.call_tool(tool_name, kwargs)
            return _extract_tool_result_text(result)

        return _invoke

    async def close(self) -> None:
        """Clean up the MCP session."""
        if self._cm is not None:
            await self._cm.__aexit__(None, None, None)
            self._cm = None
            self._session = None
