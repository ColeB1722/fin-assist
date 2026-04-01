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
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="/exit")

        ctx = await run_chat_loop(send_fn, "default", prompt=mock_fp)

        send_fn.assert_not_called()
        assert ctx is None

    async def test_exits_on_quit_command(self):
        send_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="/quit")

        ctx = await run_chat_loop(send_fn, "default", prompt=mock_fp)

        send_fn.assert_not_called()

    async def test_exits_on_q_shortcut(self):
        send_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="/q")

        ctx = await run_chat_loop(send_fn, "default", prompt=mock_fp)

        send_fn.assert_not_called()

    async def test_sends_message_to_agent(self):
        send_fn = AsyncMock(return_value=_make_result())
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["hello", "/exit"])

        await run_chat_loop(send_fn, "default", prompt=mock_fp)

        send_fn.assert_called_once_with("default", "hello", None)

    async def test_propagates_context_id(self):
        send_fn = AsyncMock(return_value=_make_result(context_id="ctx-99"))
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["first message", "second message", "/exit"])

        ctx = await run_chat_loop(send_fn, "default", prompt=mock_fp)

        assert ctx == "ctx-99"
        second_call = send_fn.call_args_list[1]
        assert second_call.args[2] == "ctx-99"

    async def test_skips_empty_input(self):
        send_fn = AsyncMock(return_value=_make_result())
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["   ", "/exit"])

        await run_chat_loop(send_fn, "default", prompt=mock_fp)

        send_fn.assert_not_called()

    async def test_continues_after_error(self):
        send_fn = AsyncMock(side_effect=[Exception("network error"), _make_result()])
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["first", "second", "/exit"])

        ctx = await run_chat_loop(send_fn, "default", prompt=mock_fp)

        assert send_fn.call_count == 2

    async def test_exits_on_keyboard_interrupt(self):
        send_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=KeyboardInterrupt)

        ctx = await run_chat_loop(send_fn, "default", prompt=mock_fp)

        send_fn.assert_not_called()

    async def test_exits_on_eof_error(self):
        send_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=EOFError)

        ctx = await run_chat_loop(send_fn, "default", prompt=mock_fp)

        send_fn.assert_not_called()

    async def test_uses_initial_context_id(self):
        send_fn = AsyncMock(return_value=_make_result(context_id="ctx-initial"))
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(return_value="/exit")

        ctx = await run_chat_loop(send_fn, "default", context_id="ctx-initial", prompt=mock_fp)

        assert ctx == "ctx-initial"

    async def test_warns_on_unknown_slash_command(self):
        send_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["/unknown", "/exit"])

        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with patch("fin_assist.cli.interaction.chat.console", test_console):
            await run_chat_loop(send_fn, "default", prompt=mock_fp)

        output = buf.getvalue()
        assert "Unknown command" in output
        send_fn.assert_not_called()

    async def test_creates_finprompt_if_not_provided(self):
        send_fn = AsyncMock(return_value=_make_result())
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["hello", "/exit"])

        with patch("fin_assist.cli.interaction.chat.FinPrompt", return_value=mock_fp) as mock_init:
            await run_chat_loop(send_fn, "default")
            mock_init.assert_called_once()

        send_fn.assert_called_once_with("default", "hello", None)
