"""Tests for platform-level ToolRegistry, ToolDefinition, and built-in tool callables."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from fin_assist.agents.tools import (
    ApprovalDecision,
    ApprovalPolicy,
    DeferredToolCall,
    ToolDefinition,
    ToolRegistry,
    create_default_registry,
)


async def _invoke(tool: ToolDefinition, **kwargs: Any) -> str:
    result = tool.callable(**kwargs)
    if isinstance(result, str):
        return result
    return await result


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

    def test_context_tools_have_no_approval_policy(self) -> None:
        registry = create_default_registry()
        context_tools = ["read_file", "git_diff", "git_log", "shell_history"]
        for name in context_tools:
            tool = registry.get(name)
            assert tool is not None
            assert tool.approval_policy is None, (
                f"Tool {tool.name} unexpectedly has approval_policy"
            )

    def test_run_shell_has_always_approval_policy(self) -> None:
        registry = create_default_registry()
        tool = registry.get("run_shell")
        assert tool is not None
        assert tool.approval_policy is not None
        assert tool.approval_policy.mode == "always"
        assert tool.approval_policy.reason is not None

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


class TestApprovalPolicy:
    def test_always_mode(self) -> None:
        policy = ApprovalPolicy(mode="always", reason="test")
        assert policy.mode == "always"
        assert policy.reason == "test"

    def test_never_mode(self) -> None:
        policy = ApprovalPolicy(mode="never")
        assert policy.mode == "never"
        assert policy.reason is None


class TestDeferredToolCall:
    def test_stores_fields(self) -> None:
        call = DeferredToolCall(
            tool_name="run_shell",
            tool_call_id="call_1",
            args={"command": "ls"},
            reason="requires approval",
        )
        assert call.tool_name == "run_shell"
        assert call.tool_call_id == "call_1"
        assert call.args == {"command": "ls"}
        assert call.reason == "requires approval"

    def test_reason_defaults_none(self) -> None:
        call = DeferredToolCall(
            tool_name="run_shell",
            tool_call_id="call_1",
            args={},
        )
        assert call.reason is None


class TestApprovalDecision:
    def test_approved(self) -> None:
        decision = ApprovalDecision(tool_call_id="call_1", approved=True)
        assert decision.tool_call_id == "call_1"
        assert decision.approved is True
        assert decision.override_args is None
        assert decision.denial_reason is None

    def test_denied_with_reason(self) -> None:
        decision = ApprovalDecision(
            tool_call_id="call_2", approved=False, denial_reason="Too dangerous"
        )
        assert decision.approved is False
        assert decision.denial_reason == "Too dangerous"

    def test_approved_with_override_args(self) -> None:
        decision = ApprovalDecision(
            tool_call_id="call_3",
            approved=True,
            override_args={"command": "ls -la"},
        )
        assert decision.override_args == {"command": "ls -la"}


class TestReadFileCallable:
    @pytest.mark.asyncio
    async def test_returns_content_when_available(self) -> None:
        from fin_assist.context.base import ContextItem

        mock_item = ContextItem(
            id="test.py", type="file", content="file content", status="available"
        )
        with patch("fin_assist.context.files.FileFinder") as MockFinder:
            MockFinder.return_value.get_item.return_value = mock_item
            registry = create_default_registry()
            tool = registry.get("read_file")
            assert tool is not None
            result = await _invoke(tool, path="test.py")
        assert result == "file content"

    @pytest.mark.asyncio
    async def test_returns_error_when_not_available(self) -> None:
        from fin_assist.context.base import ContextItem

        mock_item = ContextItem(
            id="missing.py",
            type="file",
            status="not_found",
            error_reason="File not found",
        )
        with patch("fin_assist.context.files.FileFinder") as MockFinder:
            MockFinder.return_value.get_item.return_value = mock_item
            registry = create_default_registry()
            tool = registry.get("read_file")
            assert tool is not None
            result = await _invoke(tool, path="missing.py")
        assert "Error reading file" in result
        assert "missing.py" in result
        assert "File not found" in result


class TestGitDiffCallable:
    @pytest.mark.asyncio
    async def test_returns_diff_when_available(self) -> None:
        from fin_assist.context.base import ContextItem

        mock_item = ContextItem(
            id="git_diff:diff", type="git_diff", content="diff content", status="available"
        )
        with patch("fin_assist.context.git.GitContext") as MockCtx:
            MockCtx.return_value.get_item.return_value = mock_item
            registry = create_default_registry()
            tool = registry.get("git_diff")
            assert tool is not None
            result = await _invoke(tool)
        assert result == "diff content"

    @pytest.mark.asyncio
    async def test_returns_error_when_not_available(self) -> None:
        from fin_assist.context.base import ContextItem

        mock_item = ContextItem(
            id="git_diff:diff",
            type="git_diff",
            status="error",
            error_reason="Not a git repo",
        )
        with patch("fin_assist.context.git.GitContext") as MockCtx:
            MockCtx.return_value.get_item.return_value = mock_item
            registry = create_default_registry()
            tool = registry.get("git_diff")
            assert tool is not None
            result = await _invoke(tool)
        assert "Error getting git diff" in result


class TestGitLogCallable:
    @pytest.mark.asyncio
    async def test_returns_log_when_available(self) -> None:
        from fin_assist.context.base import ContextItem

        mock_item = ContextItem(
            id="git_log:log", type="git_log", content="abc123 commit", status="available"
        )
        with patch("fin_assist.context.git.GitContext") as MockCtx:
            MockCtx.return_value.get_item.return_value = mock_item
            registry = create_default_registry()
            tool = registry.get("git_log")
            assert tool is not None
            result = await _invoke(tool)
        assert result == "abc123 commit"

    @pytest.mark.asyncio
    async def test_returns_error_when_not_available(self) -> None:
        from fin_assist.context.base import ContextItem

        mock_item = ContextItem(
            id="git_log:log",
            type="git_log",
            status="error",
            error_reason="git not available",
        )
        with patch("fin_assist.context.git.GitContext") as MockCtx:
            MockCtx.return_value.get_item.return_value = mock_item
            registry = create_default_registry()
            tool = registry.get("git_log")
            assert tool is not None
            result = await _invoke(tool)
        assert "Error getting git log" in result


class TestShellHistoryCallable:
    @pytest.mark.asyncio
    async def test_returns_search_results_with_query(self) -> None:
        from fin_assist.context.base import ContextItem

        mock_items = [
            ContextItem(id="0", type="history", content="git status", status="available"),
            ContextItem(id="1", type="history", content="git commit", status="available"),
        ]
        with patch("fin_assist.context.history.ShellHistory") as MockHistory:
            MockHistory.return_value.search.return_value = mock_items
            registry = create_default_registry()
            tool = registry.get("shell_history")
            assert tool is not None
            result = await _invoke(tool, query="git")
        assert "git status" in result
        assert "git commit" in result
        MockHistory.return_value.search.assert_called_once_with("git")

    @pytest.mark.asyncio
    async def test_returns_all_without_query(self) -> None:
        from fin_assist.context.base import ContextItem

        mock_items = [
            ContextItem(id="0", type="history", content="ls", status="available"),
        ]
        with patch("fin_assist.context.history.ShellHistory") as MockHistory:
            MockHistory.return_value.get_all.return_value = mock_items
            registry = create_default_registry()
            tool = registry.get("shell_history")
            assert tool is not None
            result = await _invoke(tool)
        assert "ls" in result
        MockHistory.return_value.get_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_message_when_empty(self) -> None:
        with patch("fin_assist.context.history.ShellHistory") as MockHistory:
            MockHistory.return_value.get_all.return_value = []
            registry = create_default_registry()
            tool = registry.get("shell_history")
            assert tool is not None
            result = await _invoke(tool)
        assert result == "No shell history available."


class _FakeProc:
    """Minimal stand-in for ``asyncio.subprocess.Process`` used by _run_shell tests."""

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        communicate_delay: float = 0.0,
        communicate_raises: BaseException | None = None,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode: int | None = None
        self._final_returncode = returncode
        self._communicate_delay = communicate_delay
        self._communicate_raises = communicate_raises
        self.terminate_called = False
        self.kill_called = False
        self._terminated = __import__("asyncio").Event()

    async def communicate(self) -> tuple[bytes, bytes]:
        import asyncio

        if self._communicate_raises is not None:
            raise self._communicate_raises
        if self._communicate_delay > 0:
            # Wait until terminated or the delay elapses (simulating a long-running proc).
            try:
                await asyncio.wait_for(self._terminated.wait(), timeout=self._communicate_delay)
            except TimeoutError:
                pass
        self.returncode = self._final_returncode
        return self._stdout, self._stderr

    def terminate(self) -> None:
        self.terminate_called = True
        self.returncode = -15
        self._terminated.set()

    def kill(self) -> None:
        self.kill_called = True
        self.returncode = -9
        self._terminated.set()

    async def wait(self) -> int:
        await self._terminated.wait()
        assert self.returncode is not None
        return self.returncode


async def _get_run_shell_tool() -> ToolDefinition:
    registry = create_default_registry()
    tool = registry.get("run_shell")
    assert tool is not None
    return tool


class TestRunShellCallable:
    async def test_success(self) -> None:
        proc = _FakeProc(stdout=b"hi\n")
        with patch("asyncio.create_subprocess_shell", return_value=proc):
            tool = await _get_run_shell_tool()
            result = await _invoke(tool, command="echo hi")
        assert result == "hi\n"

    async def test_includes_stderr(self) -> None:
        proc = _FakeProc(stdout=b"out", stderr=b"warn")
        with patch("asyncio.create_subprocess_shell", return_value=proc):
            tool = await _get_run_shell_tool()
            result = await _invoke(tool, command="cmd")
        assert "out" in result
        assert "STDERR: warn" in result

    async def test_includes_exit_code_on_failure(self) -> None:
        proc = _FakeProc(returncode=1)
        with patch("asyncio.create_subprocess_shell", return_value=proc):
            tool = await _get_run_shell_tool()
            result = await _invoke(tool, command="cmd")
        assert "Exit code: 1" in result

    async def test_returns_no_output_marker_when_empty(self) -> None:
        proc = _FakeProc()
        with patch("asyncio.create_subprocess_shell", return_value=proc):
            tool = await _get_run_shell_tool()
            result = await _invoke(tool, command="true")
        assert "(no output)" in result

    async def test_timeout_terminates_child(self) -> None:
        # communicate_delay longer than timeout -> _run_shell should terminate.
        proc = _FakeProc(communicate_delay=5.0)
        with (
            patch("asyncio.create_subprocess_shell", return_value=proc),
            patch("fin_assist.agents.tools._RUN_SHELL_TIMEOUT_SECONDS", 0.05),
        ):
            tool = await _get_run_shell_tool()
            result = await _invoke(tool, command="sleep 60")
        assert "timed out" in result
        assert proc.terminate_called, "child should be terminated on timeout"

    async def test_spawn_failure_returns_error_message(self) -> None:
        with patch("asyncio.create_subprocess_shell", side_effect=OSError("no fork")):
            tool = await _get_run_shell_tool()
            result = await _invoke(tool, command="bad cmd")
        assert "Error executing command" in result
        assert "no fork" in result

    async def test_communicate_error_returns_error_message_and_terminates(self) -> None:
        proc = _FakeProc(communicate_raises=OSError("pipe broke"))
        with patch("asyncio.create_subprocess_shell", return_value=proc):
            tool = await _get_run_shell_tool()
            result = await _invoke(tool, command="cmd")
        assert "Error executing command" in result
        assert "pipe broke" in result
        assert proc.terminate_called, "child should be terminated on I/O error"

    async def test_cancellation_terminates_child_and_propagates(self) -> None:
        import asyncio

        proc = _FakeProc(communicate_delay=5.0)
        with patch("asyncio.create_subprocess_shell", return_value=proc):
            tool = await _get_run_shell_tool()
            task = asyncio.create_task(_invoke(tool, command="sleep 60"))
            # Let the task reach `communicate()` before cancelling.
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert proc.terminate_called, "child should be terminated on cancellation"


class TestCreateDefaultRegistryContextSettings:
    def test_accepts_context_settings(self):
        from fin_assist.config.schema import ContextSettings

        settings = ContextSettings(max_file_size=500)
        registry = create_default_registry(context_settings=settings)
        assert registry is not None
        assert len(registry.list_tools()) > 0

    def test_none_context_settings_works(self):
        registry = create_default_registry(context_settings=None)
        assert registry is not None
