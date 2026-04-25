"""Tests for cli/interaction/chat.py — multi-turn chat loop."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fin_assist.agents.metadata import AgentResult
from fin_assist.cli.client import StreamEvent
from fin_assist.cli.interaction.chat import run_chat_loop


def _make_result(
    output: str = "response", success: bool = True, context_id: str | None = "ctx-1"
) -> AgentResult:
    return AgentResult(success=success, output=output, context_id=context_id)


async def _stream_fn_returning(
    result: AgentResult,
) -> AsyncIterator[StreamEvent]:
    """Create a stream function that yields a text delta then a completed event."""
    yield StreamEvent(kind="text_delta", text=result.output)
    yield StreamEvent(kind="completed", result=result)


def _make_stream_fn(result: AgentResult):
    """Create a mock stream function that returns an async iterator of events."""

    async def _gen(agent_name, prompt, context_id=None):
        yield StreamEvent(kind="text_delta", text=result.output)
        yield StreamEvent(kind="completed", result=result)

    mock = MagicMock(side_effect=_gen)
    return mock


class TestRunChatLoop:
    async def test_exits_on_exit_command(self):
        stream_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="/exit")

        ctx = await run_chat_loop(stream_fn, "default", prompt=mock_fp)

        stream_fn.assert_not_called()
        assert ctx is None

    async def test_quit_is_unrecognized_command(self):
        stream_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["/quit", "/exit"])

        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with patch("fin_assist.cli.interaction.chat.console", test_console):
            await run_chat_loop(stream_fn, "default", prompt=mock_fp)

        output = buf.getvalue()
        assert "Unknown command" in output
        stream_fn.assert_not_called()

    async def test_sends_message_to_agent(self):
        result = _make_result()
        stream_fn = _make_stream_fn(result)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["hello", "/exit"])

        await run_chat_loop(stream_fn, "default", prompt=mock_fp)

        stream_fn.assert_called_once_with("default", "hello", None)

    async def test_propagates_context_id(self):
        result = _make_result(context_id="ctx-99")
        stream_fn = _make_stream_fn(result)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["first message", "second message", "/exit"])

        ctx = await run_chat_loop(stream_fn, "default", prompt=mock_fp)

        assert ctx == "ctx-99"
        second_call = stream_fn.call_args_list[1]
        assert second_call.args[2] == "ctx-99"

    async def test_skips_empty_input(self):
        stream_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["   ", "/exit"])

        await run_chat_loop(stream_fn, "default", prompt=mock_fp)

        stream_fn.assert_not_called()

    async def test_continues_after_error(self):
        result = _make_result()
        call_count = 0

        async def _stream_gen(agent_name, prompt, context_id=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("network error")
            yield StreamEvent(kind="text_delta", text=result.output)
            yield StreamEvent(kind="completed", result=result)

        stream_fn = MagicMock(side_effect=_stream_gen)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["first", "second", "/exit"])

        ctx = await run_chat_loop(stream_fn, "default", prompt=mock_fp)

        assert stream_fn.call_count == 2

    async def test_exits_on_keyboard_interrupt(self):
        stream_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=KeyboardInterrupt)

        ctx = await run_chat_loop(stream_fn, "default", prompt=mock_fp)

        stream_fn.assert_not_called()

    async def test_exits_on_eof_error(self):
        stream_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=EOFError)

        ctx = await run_chat_loop(stream_fn, "default", prompt=mock_fp)

        stream_fn.assert_not_called()

    async def test_uses_initial_context_id(self):
        result = _make_result(context_id="ctx-initial")
        stream_fn = _make_stream_fn(result)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="/exit")

        ctx = await run_chat_loop(stream_fn, "default", context_id="ctx-initial", prompt=mock_fp)

        assert ctx == "ctx-initial"

    async def test_warns_on_unknown_slash_command(self):
        stream_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["/unknown", "/exit"])

        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with patch("fin_assist.cli.interaction.chat.console", test_console):
            await run_chat_loop(stream_fn, "default", prompt=mock_fp)

        output = buf.getvalue()
        assert "Unknown command" in output
        stream_fn.assert_not_called()

    async def test_help_shows_available_commands(self):
        stream_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["/help", "/exit"])

        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with patch("fin_assist.cli.interaction.chat.console", test_console):
            await run_chat_loop(stream_fn, "default", prompt=mock_fp)

        output = buf.getvalue()
        assert "/exit" in output
        assert "/help" in output
        assert "/sessions" in output
        stream_fn.assert_not_called()

    async def test_sessions_lists_saved_sessions(self, tmp_path):
        stream_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["/sessions", "/exit"])

        agent_dir = tmp_path / "default"
        agent_dir.mkdir()
        import json

        session_data = {"session_id": "cool-slug", "context_id": "ctx-abc12345"}
        (agent_dir / "cool-slug.json").write_text(json.dumps(session_data))

        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with (
            patch("fin_assist.cli.interaction.chat.console", test_console),
            patch("fin_assist.cli.display.console", test_console),
            patch("fin_assist.cli.display.SESSIONS_DIR", tmp_path),
        ):
            await run_chat_loop(stream_fn, "default", prompt=mock_fp)

        output = buf.getvalue()
        assert "cool-slug" in output
        assert "ctx-abc1" in output
        stream_fn.assert_not_called()

    async def test_sessions_shows_no_sessions_message(self, tmp_path):
        stream_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["/sessions", "/exit"])

        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with (
            patch("fin_assist.cli.interaction.chat.console", test_console),
            patch("fin_assist.cli.display.console", test_console),
            patch("fin_assist.cli.display.SESSIONS_DIR", tmp_path),
        ):
            await run_chat_loop(stream_fn, "default", prompt=mock_fp)

        output = buf.getvalue()
        assert "No saved sessions" in output
        stream_fn.assert_not_called()

    async def test_creates_finprompt_if_not_provided(self):
        result = _make_result()
        stream_fn = _make_stream_fn(result)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["hello", "/exit"])

        with patch("fin_assist.cli.interaction.chat.FinPrompt", return_value=mock_fp) as mock_init:
            await run_chat_loop(stream_fn, "default")
            mock_init.assert_called_once()

        stream_fn.assert_called_once_with("default", "hello", None)


class TestChatLoopThinking:
    async def test_thinking_not_shown_by_default(self):
        result_with_thinking = AgentResult(
            success=True, output="answer", thinking=["hmm"], context_id="ctx-1"
        )
        stream_fn = _make_stream_fn(result_with_thinking)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["hello", "/exit"])

        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with (
            patch("fin_assist.cli.interaction.chat.console", test_console),
            patch("fin_assist.cli.interaction.response.console", test_console),
            patch("fin_assist.cli.display.console", test_console),
        ):
            await run_chat_loop(stream_fn, "default", prompt=mock_fp)

        output = buf.getvalue()
        assert "hmm" not in output

    async def test_thinking_shown_when_flag_set(self):
        result_with_thinking = AgentResult(
            success=True, output="answer", thinking=["hmm", "let me see"], context_id="ctx-1"
        )

        async def _stream_with_thinking(agent_name, prompt, context_id=None):
            for t in result_with_thinking.thinking:
                yield StreamEvent(kind="thinking_delta", text=t)
            yield StreamEvent(kind="text_delta", text="answer")
            yield StreamEvent(kind="completed", result=result_with_thinking)

        stream_fn = MagicMock(side_effect=_stream_with_thinking)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["hello", "/exit"])

        with (
            patch(
                "fin_assist.cli.interaction.chat.render_stream",
                new_callable=AsyncMock,
                return_value=result_with_thinking,
            ) as mock_render,
        ):
            await run_chat_loop(stream_fn, "default", prompt=mock_fp, show_thinking=True)

        mock_render.assert_called_once()
        assert mock_render.call_args.kwargs["show_thinking"] is True

    async def test_no_thinking_rendered_when_empty(self):
        result = AgentResult(success=True, output="answer", thinking=[], context_id="ctx-1")
        stream_fn = _make_stream_fn(result)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["hello", "/exit"])

        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with (
            patch("fin_assist.cli.interaction.chat.console", test_console),
            patch("fin_assist.cli.interaction.response.console", test_console),
            patch("fin_assist.cli.display.console", test_console),
        ):
            await run_chat_loop(stream_fn, "default", prompt=mock_fp, show_thinking=True)

        output = buf.getvalue()
        assert "Thinking" not in output


class TestChatLoopDeferredApproval:
    async def test_approve_and_resume(self):
        result = _make_result()
        deferred_calls = [
            {
                "tool_name": "run_shell",
                "tool_call_id": "call_1",
                "args": {"command": "ls"},
                "reason": "requires approval",
            }
        ]

        async def _stream_gen(agent_name, prompt, context_id=None, approval_decisions=None):
            if approval_decisions is None:
                yield StreamEvent(kind="text_delta", text="generated command")
                yield StreamEvent(
                    kind="input_required", result=result, deferred_calls=deferred_calls
                )
            else:
                yield StreamEvent(kind="text_delta", text="command output")
                yield StreamEvent(kind="completed", result=result)

        stream_fn = MagicMock(side_effect=_stream_gen)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["run ls", "/exit"])

        from fin_assist.agents.tools import ApprovalDecision

        decisions = [ApprovalDecision(tool_call_id="call_1", approved=True)]
        with patch(
            "fin_assist.cli.interaction.approve.run_approval_widget",
            new_callable=AsyncMock,
            return_value=decisions,
        ):
            ctx = await run_chat_loop(stream_fn, "shell", prompt=mock_fp)

        assert stream_fn.call_count == 2
        second_call = stream_fn.call_args_list[1]
        assert second_call.kwargs.get("approval_decisions") == decisions

    async def test_deny_continues_chat(self):
        result = _make_result()
        deferred_calls = [
            {
                "tool_name": "run_shell",
                "tool_call_id": "call_1",
                "args": {"command": "rm -rf /"},
                "reason": "requires approval",
            }
        ]

        async def _stream_gen(agent_name, prompt, context_id=None, approval_decisions=None):
            if approval_decisions is None:
                yield StreamEvent(kind="text_delta", text="generated command")
                yield StreamEvent(
                    kind="input_required", result=result, deferred_calls=deferred_calls
                )
            else:
                yield StreamEvent(kind="text_delta", text="denied output")
                yield StreamEvent(kind="completed", result=result)

        stream_fn = MagicMock(side_effect=_stream_gen)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["delete everything", "/exit"])

        from fin_assist.agents.tools import ApprovalDecision

        decisions = [
            ApprovalDecision(tool_call_id="call_1", approved=False, denial_reason="Too dangerous")
        ]
        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)
        with (
            patch("fin_assist.cli.interaction.chat.console", test_console),
            patch(
                "fin_assist.cli.interaction.approve.run_approval_widget",
                new_callable=AsyncMock,
                return_value=decisions,
            ),
        ):
            ctx = await run_chat_loop(stream_fn, "shell", prompt=mock_fp)

        assert stream_fn.call_count == 2

    async def test_cancel_deferred_skips_resume(self):
        result = _make_result()
        deferred_calls = [
            {
                "tool_name": "run_shell",
                "tool_call_id": "call_1",
                "args": {"command": "ls"},
                "reason": "requires approval",
            }
        ]

        async def _stream_gen(agent_name, prompt, context_id=None, approval_decisions=None):
            yield StreamEvent(kind="text_delta", text="generated command")
            yield StreamEvent(kind="input_required", result=result, deferred_calls=deferred_calls)

        stream_fn = MagicMock(side_effect=_stream_gen)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["run ls", "/exit"])

        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)
        with (
            patch("fin_assist.cli.interaction.chat.console", test_console),
            patch(
                "fin_assist.cli.interaction.approve.run_approval_widget",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            ctx = await run_chat_loop(stream_fn, "shell", prompt=mock_fp)

        assert stream_fn.call_count == 1
        output = buf.getvalue()
        assert "cancelled" in output.lower()
