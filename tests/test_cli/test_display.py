"""Tests for cli/display.py — Rich output rendering.

Test strategy: mock ``console.print`` and assert on the Rich objects
passed to it.  This tests *what* is rendered, not *how* Rich formats
it — resilient to Rich version changes or theme tweaks.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from fin_assist.agents.metadata import AgentCardMeta
from fin_assist.cli.client import DiscoveredAgent
from fin_assist.cli.display import (
    render_agent_card,
    render_agents_list,
    render_auth_required,
    render_error,
    render_info,
    render_response,
    render_thinking,
    render_warnings,
)


def _mock_console():
    """Return a MagicMock to patch over ``fin_assist.cli.display.console``."""
    return MagicMock()


class TestRenderResponse:
    def test_prints_panel_with_markdown(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_response("Here is my response")
        mock.print.assert_called_once()
        panel = mock.print.call_args[0][0]
        assert isinstance(panel, Panel)
        assert isinstance(panel.renderable, Markdown)

    def test_panel_title_includes_agent_name(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_response("hello", agent_name="default")
        panel = mock.print.call_args[0][0]
        assert "default" in str(panel.title)


class TestRenderWarnings:
    def test_prints_panel_when_warnings_present(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_warnings(["warning one", "warning two"])
        mock.print.assert_called_once()
        panel = mock.print.call_args[0][0]
        assert isinstance(panel, Panel)

    def test_no_print_when_empty(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_warnings([])
        mock.print.assert_not_called()


class TestRenderError:
    def test_prints_error_message(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_error("something went wrong")
        mock.print.assert_called_once()
        rendered = str(mock.print.call_args[0][0])
        assert "something went wrong" in rendered


class TestRenderInfo:
    def test_prints_info_message(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_info("loading...")
        mock.print.assert_called_once()
        rendered = str(mock.print.call_args[0][0])
        assert "loading..." in rendered


class TestRenderAuthRequired:
    def test_prints_yellow_panel(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_auth_required("anthropic")
        mock.print.assert_called_once()
        panel = mock.print.call_args[0][0]
        assert isinstance(panel, Panel)
        assert panel.border_style == "yellow"

    def test_panel_content_mentions_provider(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_auth_required("anthropic")
        panel = mock.print.call_args[0][0]
        text = panel.renderable
        assert isinstance(text, Text)
        rendered = text.plain
        assert "anthropic" in rendered.lower()

    def test_panel_content_includes_env_var_hint(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_auth_required("anthropic")
        panel = mock.print.call_args[0][0]
        rendered = panel.renderable.plain
        assert "ANTHROPIC_API_KEY" in rendered


class TestRenderThinking:
    def test_prints_panel_per_block(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_thinking(["block one", "block two"])
        positional_calls = [c for c in mock.print.call_args_list if c[0]]
        panels = [c[0][0] for c in positional_calls]
        thinking_panels = [p for p in panels if isinstance(p, Panel)]
        assert len(thinking_panels) == 2

    def test_panel_title_is_thinking(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_thinking(["hmm"])
        panel = mock.print.call_args_list[0][0][0]
        assert isinstance(panel, Panel)
        assert "Thinking" in str(panel.title)

    def test_no_print_when_empty(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_thinking([])
        mock.print.assert_not_called()


class TestRenderAgentCard:
    def _make_agent(self, **kwargs) -> DiscoveredAgent:
        defaults = {
            "name": "shell",
            "description": "Shell command generator",
            "url": "http://localhost/agents/shell/",
            "card_meta": AgentCardMeta(),
        }
        defaults.update(kwargs)
        return DiscoveredAgent(**defaults)

    def test_prints_agent_name(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_agent_card(self._make_agent(name="shell"))
        first_line = str(mock.print.call_args_list[0][0][0])
        assert "shell" in first_line

    def test_prints_description(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_agent_card(self._make_agent(description="Runs shell commands"))
        first_line = str(mock.print.call_args_list[0][0][0])
        assert "Runs shell commands" in first_line

    def test_prints_serving_modes(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_agent_card(
                self._make_agent(card_meta=AgentCardMeta(serving_modes=["do", "talk"]))
            )
        second_line = str(mock.print.call_args_list[1][0][0])
        assert "do" in second_line
        assert "talk" in second_line


class TestRenderAgentsList:
    def test_calls_render_agent_card_per_agent(self):
        agents = [
            DiscoveredAgent(
                name="shell",
                description="Shell",
                url="http://localhost/agents/shell/",
            ),
            DiscoveredAgent(
                name="default",
                description="Default",
                url="http://localhost/agents/default/",
            ),
        ]
        with patch("fin_assist.cli.display.render_agent_card") as mock_card:
            render_agents_list(agents)
        assert mock_card.call_count == 2

    def test_prints_header(self):
        mock = _mock_console()
        with patch("fin_assist.cli.display.console", mock):
            render_agents_list([])
        first_print = str(mock.print.call_args_list[0][0][0])
        assert "Available agents" in first_print
