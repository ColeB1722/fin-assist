"""Tests for cli/interaction/chat.py — multi-turn chat loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fin_assist.cli.client import AgentResult
from fin_assist.cli.interaction.chat import run_chat_loop


def _make_result(
    output: str = "response", success: bool = True, context_id: str | None = "ctx-1"
) -> AgentResult:
    return AgentResult(success=success, output=output, context_id=context_id)


class TestRunChatLoop:
    async def test_exits_on_exit_command(self):
        send_fn = AsyncMock()

        with patch("fin_assist.cli.interaction.chat.Prompt.ask", return_value="/exit"):
            ctx = await run_chat_loop(send_fn, "default")

        send_fn.assert_not_called()
        assert ctx is None

    async def test_exits_on_quit_command(self):
        send_fn = AsyncMock()

        with patch("fin_assist.cli.interaction.chat.Prompt.ask", return_value="/quit"):
            ctx = await run_chat_loop(send_fn, "default")

        send_fn.assert_not_called()

    async def test_exits_on_q_shortcut(self):
        send_fn = AsyncMock()

        with patch("fin_assist.cli.interaction.chat.Prompt.ask", return_value="/q"):
            ctx = await run_chat_loop(send_fn, "default")

        send_fn.assert_not_called()

    async def test_sends_message_to_agent(self):
        send_fn = AsyncMock(return_value=_make_result())
        call_count = 0

        def ask_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "hello"
            return "/exit"

        with patch("fin_assist.cli.interaction.chat.Prompt.ask", side_effect=ask_side_effect):
            await run_chat_loop(send_fn, "default")

        send_fn.assert_called_once_with("default", "hello", None)

    async def test_propagates_context_id(self):
        send_fn = AsyncMock(return_value=_make_result(context_id="ctx-99"))
        call_count = 0

        def ask_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "first message"
            if call_count == 2:
                return "second message"
            return "/exit"

        with patch("fin_assist.cli.interaction.chat.Prompt.ask", side_effect=ask_side_effect):
            ctx = await run_chat_loop(send_fn, "default")

        assert ctx == "ctx-99"
        # Second call should carry the context_id from first response
        second_call = send_fn.call_args_list[1]
        assert second_call.args[2] == "ctx-99"

    async def test_skips_empty_input(self):
        send_fn = AsyncMock(return_value=_make_result())
        call_count = 0

        def ask_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "   "  # whitespace only
            return "/exit"

        with patch("fin_assist.cli.interaction.chat.Prompt.ask", side_effect=ask_side_effect):
            await run_chat_loop(send_fn, "default")

        send_fn.assert_not_called()

    async def test_continues_after_error(self):
        send_fn = AsyncMock(side_effect=[Exception("network error"), _make_result()])
        call_count = 0

        def ask_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "first"
            if call_count == 2:
                return "second"
            return "/exit"

        with patch("fin_assist.cli.interaction.chat.Prompt.ask", side_effect=ask_side_effect):
            ctx = await run_chat_loop(send_fn, "default")

        assert send_fn.call_count == 2

    async def test_exits_on_keyboard_interrupt(self):
        send_fn = AsyncMock()

        with patch(
            "fin_assist.cli.interaction.chat.Prompt.ask",
            side_effect=KeyboardInterrupt,
        ):
            ctx = await run_chat_loop(send_fn, "default")

        send_fn.assert_not_called()

    async def test_exits_on_eof_error(self):
        send_fn = AsyncMock()

        with patch(
            "fin_assist.cli.interaction.chat.Prompt.ask",
            side_effect=EOFError,
        ):
            ctx = await run_chat_loop(send_fn, "default")

        send_fn.assert_not_called()

    async def test_uses_initial_context_id(self):
        send_fn = AsyncMock(return_value=_make_result(context_id="ctx-initial"))

        def ask_side_effect(*args, **kwargs):
            return "/exit"

        with patch("fin_assist.cli.interaction.chat.Prompt.ask", side_effect=ask_side_effect):
            ctx = await run_chat_loop(send_fn, "default", context_id="ctx-initial")

        assert ctx == "ctx-initial"

    async def test_warns_on_unknown_slash_command(self):
        send_fn = AsyncMock()
        call_count = 0

        def ask_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "/unknown"
            return "/exit"

        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with (
            patch("fin_assist.cli.interaction.chat.Prompt.ask", side_effect=ask_side_effect),
            patch("fin_assist.cli.interaction.chat.console", test_console),
        ):
            await run_chat_loop(send_fn, "default")

        output = buf.getvalue()
        assert "Unknown command" in output
        send_fn.assert_not_called()
