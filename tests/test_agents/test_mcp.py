"""Tests for MCP (Model Context Protocol) tool provider integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fin_assist.agents.mcp import (
    MCPToolProvider,
    _annotations_to_policy,
    _extract_tool_result_text,
)
from fin_assist.agents.tools import ApprovalPolicy, ToolDefinition, ToolRegistry
from fin_assist.config.schema import MCPServerConfig


class TestAnnotationsToPolicy:
    """Tests for the annotation-to-approval-policy mapper (#141)."""

    def test_none_annotations_returns_always(self):
        result = _annotations_to_policy(None)
        assert result.mode == "always"

    def test_read_only_hint_returns_never(self):
        annotations = MagicMock(readOnlyHint=True, destructiveHint=True)
        result = _annotations_to_policy(annotations)
        assert result.mode == "never"
        assert "read-only" in (result.description or "")

    def test_destructive_hint_returns_always(self):
        annotations = MagicMock(readOnlyHint=False, destructiveHint=True)
        result = _annotations_to_policy(annotations)
        assert result.mode == "always"
        assert "destructive" in (result.description or "")

    def test_non_destructive_hint_returns_always(self):
        annotations = MagicMock(readOnlyHint=False, destructiveHint=False)
        result = _annotations_to_policy(annotations)
        assert result.mode == "always"
        assert "non-destructive" in (result.description or "")

    def test_dict_annotations_work(self):
        annotations = {"readOnlyHint": True, "destructiveHint": True}
        result = _annotations_to_policy(annotations)
        assert result.mode == "never"

    def test_missing_keys_use_defaults(self):
        annotations = MagicMock()
        # getattr fallback: readOnlyHint=False, destructiveHint=True
        del annotations.readOnlyHint
        del annotations.destructiveHint
        result = _annotations_to_policy(annotations)
        assert result.mode == "always"


class TestExtractToolResultText:
    """Tests for MCP tool result text extraction."""

    def test_text_content_extracted(self):
        from mcp.types import TextContent

        result = MagicMock(content=[TextContent(type="text", text="hello")])
        assert _extract_tool_result_text(result) == "hello"

    def test_multiple_text_content_joined(self):
        from mcp.types import TextContent

        result = MagicMock(
            content=[TextContent(type="text", text="a"), TextContent(type="text", text="b")]
        )
        assert _extract_tool_result_text(result) == "a\nb"

    def test_non_text_content_fallback(self):
        result = MagicMock(content=[MagicMock()])
        text = _extract_tool_result_text(result)
        # MagicMock string representation contains "MagicMock"
        assert "MagicMock" in text


class TestMCPToolProviderDiscovery:
    """Tests for MCPToolProvider.discover() with mocked MCP session."""

    @pytest.fixture
    def mock_stdio_client(self):
        """Return a context manager mock for stdio_client."""
        read_stream = MagicMock()
        write_stream = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=(read_stream, write_stream))
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm, read_stream, write_stream

    @pytest.fixture
    def mock_tool(self):
        """Return a mocked MCP Tool."""
        tool = MagicMock()
        tool.name = "get_weather"
        tool.description = "Get weather"
        tool.inputSchema = {"type": "object", "properties": {"city": {"type": "string"}}}
        tool.annotations = None
        return tool

    def test_stdio_provider_connects_and_discovers(self, mock_stdio_client, mock_tool):
        cm, read_stream, write_stream = mock_stdio_client
        config = MCPServerConfig(
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-memory"],
        )
        provider = MCPToolProvider("memory", config)

        with patch("fin_assist.agents.mcp.stdio_client", return_value=cm):
            with patch("fin_assist.agents.mcp.ClientSession") as MockSession:
                session = MagicMock()
                session.initialize = AsyncMock()
                list_result = MagicMock()
                list_result.tools = [mock_tool]
                session.list_tools = AsyncMock(return_value=list_result)
                MockSession.return_value = session

                tools = provider.discover()

        assert len(tools) == 1
        assert tools[0].name == "mcp.memory.get_weather"
        assert tools[0].description == "Get weather"

    def test_sse_provider_connects_and_discovers(self, mock_stdio_client, mock_tool):
        cm, read_stream, write_stream = mock_stdio_client
        config = MCPServerConfig(
            transport="sse",
            url="http://localhost:3001/sse",
        )
        provider = MCPToolProvider("github", config)

        with patch("fin_assist.agents.mcp.sse_client", return_value=cm):
            with patch("fin_assist.agents.mcp.ClientSession") as MockSession:
                session = MagicMock()
                session.initialize = AsyncMock()
                list_result = MagicMock()
                list_result.tools = [mock_tool]
                session.list_tools = AsyncMock(return_value=list_result)
                MockSession.return_value = session

                tools = provider.discover()

        assert len(tools) == 1
        assert tools[0].name == "mcp.github.get_weather"

    def test_annotations_mapped_to_approval_policy(self, mock_stdio_client):
        cm, read_stream, write_stream = mock_stdio_client
        config = MCPServerConfig(
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-memory"],
        )
        provider = MCPToolProvider("memory", config)

        tool = MagicMock()
        tool.name = "read_only_tool"
        tool.description = "Read something"
        tool.inputSchema = {"type": "object"}
        tool.annotations = MagicMock(readOnlyHint=True, destructiveHint=False)

        with patch("fin_assist.agents.mcp.stdio_client", return_value=cm):
            with patch("fin_assist.agents.mcp.ClientSession") as MockSession:
                session = MagicMock()
                session.initialize = AsyncMock()
                list_result = MagicMock()
                list_result.tools = [tool]
                session.list_tools = AsyncMock(return_value=list_result)
                MockSession.return_value = session

                tools = provider.discover()

        assert tools[0].approval_policy is not None
        assert tools[0].approval_policy.mode == "never"

    def test_provider_name(self):
        config = MCPServerConfig(
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-memory"],
        )
        provider = MCPToolProvider("memory", config)
        assert provider.name == "mcp-memory"

    def test_discover_is_idempotent(self, mock_stdio_client, mock_tool):
        cm, read_stream, write_stream = mock_stdio_client
        config = MCPServerConfig(
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-memory"],
        )
        provider = MCPToolProvider("memory", config)

        with patch("fin_assist.agents.mcp.stdio_client", return_value=cm):
            with patch("fin_assist.agents.mcp.ClientSession") as MockSession:
                session = MagicMock()
                session.initialize = AsyncMock()
                list_result = MagicMock()
                list_result.tools = [mock_tool]
                session.list_tools = AsyncMock(return_value=list_result)
                MockSession.return_value = session

                tools1 = provider.discover()
                tools2 = provider.discover()

        assert tools1 is tools2

    def test_initialize_failure_unwinds_transport(self, mock_stdio_client):
        """If session.initialize() fails, the transport context manager is
        closed and provider state is reset so a retry starts clean."""
        cm, _, _ = mock_stdio_client
        config = MCPServerConfig(
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-memory"],
        )
        provider = MCPToolProvider("memory", config)

        with patch("fin_assist.agents.mcp.stdio_client", return_value=cm):
            with patch("fin_assist.agents.mcp.ClientSession") as MockSession:
                session = MagicMock()
                session.initialize = AsyncMock(side_effect=RuntimeError("init boom"))
                MockSession.return_value = session

                with pytest.raises(RuntimeError, match="init boom"):
                    provider.discover()

        # Transport CM should have been exited so we don't leak the connection.
        cm.__aexit__.assert_awaited_once()
        # Provider state should be reset so a subsequent retry can re-enter
        # `_connect()` from the top instead of short-circuiting on a stale CM.
        assert provider._session is None
        assert provider._cm is None


class TestCreateDefaultRegistryWithMCP:
    """Tests for create_default_registry with MCP servers."""

    @pytest.fixture(autouse=True)
    def _patch_mcp_discover(self):
        """Prevent MCPToolProvider from attempting real connections."""
        with patch.object(MCPToolProvider, "discover", return_value=[]):
            yield

    def test_registry_includes_mcp_providers_when_configured(self):
        from fin_assist.agents.tools import create_default_registry

        servers = {
            "memory": MCPServerConfig(
                transport="stdio",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-memory"],
            )
        }
        registry = create_default_registry(mcp_servers=servers)

        # Builtin provider should be present
        assert registry.get_provider("builtin") is not None
        # MCP provider should be present
        assert registry.get_provider("mcp-memory") is not None

    def test_disabled_servers_are_skipped(self):
        from fin_assist.agents.tools import create_default_registry

        servers = {
            "memory": MCPServerConfig(
                transport="stdio",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-memory"],
                enabled=False,
            )
        }
        registry = create_default_registry(mcp_servers=servers)

        assert registry.get_provider("mcp-memory") is None

    def test_empty_mcp_servers_is_noop(self):
        from fin_assist.agents.tools import create_default_registry

        registry = create_default_registry(mcp_servers={})
        assert registry.get_provider("builtin") is not None
        assert len(registry.list_tools()) >= 5  # built-in tools

    def test_no_mcp_servers_is_noop(self):
        from fin_assist.agents.tools import create_default_registry

        registry = create_default_registry()
        assert registry.get_provider("builtin") is not None


class TestMCPServerConfigValidation:
    """Tests for MCPServerConfig pydantic validation."""

    def test_stdio_requires_command(self):
        with pytest.raises(ValueError, match="command"):
            MCPServerConfig(transport="stdio")

    def test_sse_requires_url(self):
        with pytest.raises(ValueError, match="url"):
            MCPServerConfig(transport="sse")

    def test_valid_stdio_config(self):
        cfg = MCPServerConfig(
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-memory"],
        )
        assert cfg.command == "npx"
        assert cfg.timeout == 30

    def test_valid_sse_config(self):
        cfg = MCPServerConfig(
            transport="sse",
            url="http://localhost:3001/sse",
        )
        assert cfg.url == "http://localhost:3001/sse"
        assert cfg.timeout == 30
