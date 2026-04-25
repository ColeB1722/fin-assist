"""Tests for platform-level ToolRegistry and ToolDefinition types."""

from __future__ import annotations

from typing import Any

import pytest

from fin_assist.agents.tools import ToolDefinition, ToolRegistry, create_default_registry


def _make_tool(name: str = "test_tool", **overrides: Any) -> ToolDefinition:
    defaults = {
        "name": name,
        "description": f"A test tool: {name}",
        "callable": lambda: "result",
        "parameters_schema": {"type": "object", "properties": {}},
        "approval_policy": None,
    }
    defaults.update(overrides)
    return ToolDefinition(**defaults)


class TestToolDefinition:
    def test_stores_fields(self) -> None:
        def my_func(x: str) -> str:
            return x

        td = ToolDefinition(
            name="my_tool",
            description="Does a thing",
            callable=my_func,
            parameters_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        )
        assert td.name == "my_tool"
        assert td.description == "Does a thing"
        assert td.callable is my_func
        assert td.parameters_schema["properties"]["x"]["type"] == "string"
        assert td.approval_policy is None

    def test_approval_policy_defaults_none(self) -> None:
        td = _make_tool()
        assert td.approval_policy is None

    def test_approval_policy_can_be_set(self) -> None:
        policy = object()
        td = _make_tool(approval_policy=policy)
        assert td.approval_policy is policy

    def test_callable_can_be_async(self) -> None:
        async def async_func() -> str:
            return "async_result"

        td = _make_tool(callable=async_func)
        assert td.callable is async_func


class TestToolRegistry:
    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        tool = _make_tool("read_file")
        registry.register(tool)
        assert registry.get("read_file") is tool

    def test_get_returns_none_for_unknown(self) -> None:
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_register_duplicate_raises(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_tool("dup"))
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_make_tool("dup"))

    def test_list_tools_empty(self) -> None:
        registry = ToolRegistry()
        assert registry.list_tools() == []

    def test_list_tools_returns_all(self) -> None:
        registry = ToolRegistry()
        t1 = _make_tool("a")
        t2 = _make_tool("b")
        registry.register(t1)
        registry.register(t2)
        names = {t.name for t in registry.list_tools()}
        assert names == {"a", "b"}

    def test_get_for_agent_resolves_known_names(self) -> None:
        registry = ToolRegistry()
        t1 = _make_tool("read_file")
        t2 = _make_tool("git_diff")
        t3 = _make_tool("shell_history")
        registry.register(t1)
        registry.register(t2)
        registry.register(t3)
        result = registry.get_for_agent(["read_file", "git_diff"])
        assert [t.name for t in result] == ["read_file", "git_diff"]

    def test_get_for_agent_skips_unknown_names(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_tool("read_file"))
        result = registry.get_for_agent(["read_file", "nonexistent"])
        assert [t.name for t in result] == ["read_file"]

    def test_get_for_agent_empty_names(self) -> None:
        registry = ToolRegistry()
        registry.register(_make_tool("read_file"))
        assert registry.get_for_agent([]) == []


class TestCreateDefaultRegistry:
    def test_creates_registry_with_builtin_tools(self) -> None:
        registry = create_default_registry()
        tools = registry.list_tools()
        names = {t.name for t in tools}
        assert "read_file" in names
        assert "git_diff" in names
        assert "git_log" in names
        assert "shell_history" in names

    def test_builtin_tools_have_descriptions(self) -> None:
        registry = create_default_registry()
        for tool in registry.list_tools():
            assert tool.description, f"Tool {tool.name} has no description"

    def test_builtin_tools_have_parameters_schema(self) -> None:
        registry = create_default_registry()
        for tool in registry.list_tools():
            assert tool.parameters_schema, f"Tool {tool.name} has no parameters_schema"
            assert tool.parameters_schema.get("type") == "object"

    def test_builtin_tools_have_no_approval_policy(self) -> None:
        registry = create_default_registry()
        for tool in registry.list_tools():
            assert tool.approval_policy is None, (
                f"Tool {tool.name} unexpectedly has approval_policy"
            )

    def test_read_file_has_path_parameter(self) -> None:
        registry = create_default_registry()
        tool = registry.get("read_file")
        assert tool is not None
        props = tool.parameters_schema["properties"]
        assert "path" in props
        assert props["path"]["type"] == "string"

    def test_git_diff_has_no_required_parameters(self) -> None:
        registry = create_default_registry()
        tool = registry.get("git_diff")
        assert tool is not None
        assert tool.parameters_schema.get("required", []) == []

    def test_shell_history_has_optional_query(self) -> None:
        registry = create_default_registry()
        tool = registry.get("shell_history")
        assert tool is not None
        props = tool.parameters_schema["properties"]
        assert "query" in props
        assert (
            "required" not in tool.parameters_schema
            or "query" not in tool.parameters_schema.get("required", [])
        )

    def test_builtin_tool_callables_are_async(self) -> None:
        import inspect

        registry = create_default_registry()
        for tool in registry.list_tools():
            assert inspect.iscoroutinefunction(tool.callable), (
                f"Tool {tool.name} callable is not async"
            )
