"""Tests for cli/interaction/chat.py — multi-turn chat loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fin_assist.agents.metadata import AgentCardMeta
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

    async def test_quit_is_unrecognized_command(self):
        send_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["/quit", "/exit"])

        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with patch("fin_assist.cli.interaction.chat.console", test_console):
            await run_chat_loop(send_fn, "default", prompt=mock_fp)

        output = buf.getvalue()
        assert "Unknown command" in output
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

    async def test_help_shows_available_commands(self):
        send_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["/help", "/exit"])

        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with patch("fin_assist.cli.interaction.chat.console", test_console):
            await run_chat_loop(send_fn, "default", prompt=mock_fp)

        output = buf.getvalue()
        assert "/exit" in output
        assert "/help" in output
        assert "/sessions" in output
        send_fn.assert_not_called()

    async def test_sessions_lists_saved_sessions(self, tmp_path):
        send_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["/sessions", "/exit"])

        # Create a fake session file
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
            patch("fin_assist.cli.interaction.chat.SESSIONS_DIR", tmp_path),
        ):
            await run_chat_loop(send_fn, "default", prompt=mock_fp)

        output = buf.getvalue()
        assert "cool-slug" in output
        assert "ctx-abc1" in output
        send_fn.assert_not_called()

    async def test_sessions_shows_no_sessions_message(self, tmp_path):
        send_fn = AsyncMock()
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["/sessions", "/exit"])

        from io import StringIO
        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False)

        with (
            patch("fin_assist.cli.interaction.chat.console", test_console),
            patch("fin_assist.cli.interaction.chat.SESSIONS_DIR", tmp_path),
        ):
            await run_chat_loop(send_fn, "default", prompt=mock_fp)

        output = buf.getvalue()
        assert "No saved sessions" in output
        send_fn.assert_not_called()

    async def test_creates_finprompt_if_not_provided(self):
        send_fn = AsyncMock(return_value=_make_result())
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["hello", "/exit"])

        with patch("fin_assist.cli.interaction.chat.FinPrompt", return_value=mock_fp) as mock_init:
            await run_chat_loop(send_fn, "default")
            mock_init.assert_called_once()

        send_fn.assert_called_once_with("default", "hello", None)


class TestChatLoopThinking:
    async def test_thinking_not_shown_by_default(self):
        result_with_thinking = AgentResult(
            success=True, output="answer", thinking=["hmm"], context_id="ctx-1"
        )
        send_fn = AsyncMock(return_value=result_with_thinking)
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
            await run_chat_loop(send_fn, "default", prompt=mock_fp)

        output = buf.getvalue()
        assert "hmm" not in output
        assert "answer" in output

    async def test_thinking_shown_when_flag_set(self):
        result_with_thinking = AgentResult(
            success=True, output="answer", thinking=["hmm", "let me see"], context_id="ctx-1"
        )
        send_fn = AsyncMock(return_value=result_with_thinking)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["hello", "/exit"])

        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True, legacy_windows=False)

        with (
            patch("fin_assist.cli.interaction.chat.console", test_console),
            patch("fin_assist.cli.interaction.response.console", test_console),
            patch("fin_assist.cli.display.console", test_console),
        ):
            await run_chat_loop(send_fn, "default", prompt=mock_fp, show_thinking=True)

        output = buf.getvalue()
        assert "hmm" in output
        assert "let me see" in output
        assert "answer" in output

    async def test_thinking_shown_before_response(self):
        result_with_thinking = AgentResult(
            success=True, output="answer", thinking=["reasoning"], context_id="ctx-1"
        )
        send_fn = AsyncMock(return_value=result_with_thinking)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["hello", "/exit"])

        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True, legacy_windows=False)

        with (
            patch("fin_assist.cli.interaction.chat.console", test_console),
            patch("fin_assist.cli.interaction.response.console", test_console),
            patch("fin_assist.cli.display.console", test_console),
        ):
            await run_chat_loop(send_fn, "default", prompt=mock_fp, show_thinking=True)

        output = buf.getvalue()
        reasoning_pos = output.find("reasoning")
        answer_pos = output.find("answer")
        assert reasoning_pos < answer_pos

    async def test_no_thinking_rendered_when_empty(self):
        result = AgentResult(success=True, output="answer", thinking=[], context_id="ctx-1")
        send_fn = AsyncMock(return_value=result)
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
            await run_chat_loop(send_fn, "default", prompt=mock_fp, show_thinking=True)

        output = buf.getvalue()
        assert "Thinking" not in output
        assert "answer" in output


class TestChatLoopCardMeta:
    async def test_requires_approval_shows_widget_in_talk(self):
        result = AgentResult(success=True, output="rm -rf /tmp", context_id="ctx-1")
        send_fn = AsyncMock(return_value=result)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["delete temp", "/exit"])
        card_meta = AgentCardMeta(requires_approval=True)

        from fin_assist.cli.interaction.approve import ApprovalAction

        with (
            patch(
                "fin_assist.cli.interaction.response.run_approve_widget",
                new_callable=AsyncMock,
                return_value=ApprovalAction.CANCEL,
            ) as mock_widget,
        ):
            await run_chat_loop(send_fn, "shell", prompt=mock_fp, card_meta=card_meta)

        mock_widget.assert_called_once()

    async def test_no_approval_widget_when_not_required(self):
        result = AgentResult(success=True, output="hello", context_id="ctx-1")
        send_fn = AsyncMock(return_value=result)
        mock_fp = MagicMock()
        mock_fp.ask = AsyncMock(side_effect=["hi", "/exit"])
        card_meta = AgentCardMeta(requires_approval=False)

        with (
            patch("fin_assist.cli.interaction.response.run_approve_widget") as mock_widget,
        ):
            await run_chat_loop(send_fn, "default", prompt=mock_fp, card_meta=card_meta)

        mock_widget.assert_not_called()
