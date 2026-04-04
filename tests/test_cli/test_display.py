"""Tests for cli/display.py — Rich output rendering."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock, patch

from rich.console import Console

from fin_assist.agents.base import AgentCardMeta
from fin_assist.cli.client import DiscoveredAgent
from fin_assist.cli.display import (
    render_agent_card,
    render_agents_list,
    render_auth_required,
    render_command,
    render_error,
    render_info,
    render_response,
    render_success,
    render_warnings,
)


def _capture_output(fn, *args, **kwargs) -> str:
    """Run a display function with a StringIO console and capture output."""
    buf = StringIO()
    test_console = Console(file=buf, force_terminal=False, highlight=False)
    with patch("fin_assist.cli.display.console", test_console):
        fn(*args, **kwargs)
    return buf.getvalue()


class TestRenderCommand:
    def test_renders_without_error(self):
        # Should not raise
        output = _capture_output(render_command, "ls -la")
        assert len(output) > 0

    def test_includes_command_text(self):
        output = _capture_output(render_command, "echo hello")
        assert "echo hello" in output

    def test_renders_warnings_when_present(self):
        output = _capture_output(render_command, "ls", warnings=["might be slow"])
        assert "might be slow" in output

    def test_no_warnings_when_empty(self):
        output = _capture_output(render_command, "ls", warnings=[])
        assert "Warnings" not in output


class TestRenderResponse:
    def test_renders_text(self):
        output = _capture_output(render_response, "Here is my response")
        assert "Here is my response" in output

    def test_includes_agent_name(self):
        output = _capture_output(render_response, "hello", agent_name="default")
        assert "default" in output


class TestRenderWarnings:
    def test_renders_each_warning(self):
        output = _capture_output(render_warnings, ["warning one", "warning two"])
        assert "warning one" in output
        assert "warning two" in output

    def test_no_output_for_empty_warnings(self):
        output = _capture_output(render_warnings, [])
        assert output == ""


class TestRenderError:
    def test_renders_message(self):
        output = _capture_output(render_error, "something went wrong")
        assert "something went wrong" in output


class TestRenderSuccess:
    def test_renders_message(self):
        output = _capture_output(render_success, "operation succeeded")
        assert "operation succeeded" in output


class TestRenderInfo:
    def test_renders_message(self):
        output = _capture_output(render_info, "loading...")
        assert "loading..." in output


class TestRenderAuthRequired:
    def test_renders_provider_name(self):
        output = _capture_output(render_auth_required, "anthropic")
        assert "anthropic" in output.lower()

    def test_renders_env_var_hint(self):
        output = _capture_output(render_auth_required, "anthropic")
        assert "ANTHROPIC_API_KEY" in output

    def test_renders_distinct_from_generic_error(self):
        """Should use 'Authentication required' or similar, not 'Error:'."""
        output = _capture_output(render_auth_required, "anthropic")
        assert "auth" in output.lower()

    def test_renders_multiple_providers(self):
        output = _capture_output(render_auth_required, "anthropic, openrouter")
        assert "anthropic" in output.lower()
        assert "openrouter" in output.lower()


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

    def test_renders_agent_name(self):
        agent = self._make_agent(name="shell")
        output = _capture_output(render_agent_card, agent)
        assert "shell" in output

    def test_renders_agent_description(self):
        agent = self._make_agent(description="Runs shell commands")
        output = _capture_output(render_agent_card, agent)
        assert "Runs shell commands" in output

    def test_renders_one_shot_for_non_multi_turn(self):
        agent = self._make_agent(card_meta=AgentCardMeta(multi_turn=False))
        output = _capture_output(render_agent_card, agent)
        assert "one-shot" in output

    def test_renders_requires_approval_flag(self):
        agent = self._make_agent(card_meta=AgentCardMeta(requires_approval=True))
        output = _capture_output(render_agent_card, agent)
        assert "requires approval" in output

    def test_renders_supports_regenerate_flag(self):
        agent = self._make_agent(card_meta=AgentCardMeta(supports_regenerate=True))
        output = _capture_output(render_agent_card, agent)
        assert "supports regenerate" in output


class TestRenderAgentsList:
    def test_renders_all_agents(self):
        agents = [
            DiscoveredAgent(
                name="shell",
                description="Shell",
                url="http://localhost/agents/shell/",
                card_meta=AgentCardMeta(),
            ),
            DiscoveredAgent(
                name="default",
                description="Default",
                url="http://localhost/agents/default/",
                card_meta=AgentCardMeta(),
            ),
        ]
        output = _capture_output(render_agents_list, agents)
        assert "shell" in output
        assert "default" in output

    def test_renders_header(self):
        output = _capture_output(render_agents_list, [])
        assert "Available agents" in output
