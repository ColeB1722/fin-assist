"""Tests for cli/display.py — Rich output rendering."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock, patch

from rich.console import Console

from fin_assist.agents.metadata import AgentCardMeta
from fin_assist.cli.client import AgentResult, DiscoveredAgent
from fin_assist.cli.display import (
    ProgressiveDisplay,
    render_agent_card,
    render_agent_output,
    render_agents_list,
    render_auth_required,
    render_collapsed_thinking,
    render_command,
    render_error,
    render_info,
    render_markdown,
    render_response,
    render_success,
    render_thinking,
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


class TestRenderThinking:
    def test_renders_thinking_content(self):
        output = _capture_output(render_thinking, ["Let me think about this..."])
        assert "Let me think about this..." in output

    def test_includes_thinking_label(self):
        output = _capture_output(render_thinking, ["hmm"])
        assert "Thinking" in output

    def test_no_output_for_empty_list(self):
        output = _capture_output(render_thinking, [])
        assert output == ""

    def test_renders_multiple_blocks(self):
        output = _capture_output(render_thinking, ["first", "second"])
        assert "first" in output
        assert "second" in output


class TestRenderMarkdown:
    def test_renders_markdown_text(self):
        output = _capture_output(render_markdown, "Hello **world**")
        assert "world" in output

    def test_no_panel_wrapper(self):
        output = _capture_output(render_markdown, "plain text")
        assert "──" not in output


class TestRenderAgentOutput:
    def _make_meta(self, **kwargs) -> AgentCardMeta:
        return AgentCardMeta(**kwargs)

    def test_auth_required_renders_auth_panel(self):
        result = AgentResult(success=False, output="anthropic", metadata={"auth_required": True})
        meta = self._make_meta()
        output = _capture_output(render_agent_output, result, meta)
        assert "auth" in output.lower()

    def test_failed_result_renders_error(self):
        result = AgentResult(success=False, output="something went wrong")
        meta = self._make_meta()
        output = _capture_output(render_agent_output, result, meta)
        assert "something went wrong" in output

    def test_text_do_mode_uses_panel(self):
        result = AgentResult(success=True, output="Here is my answer")
        meta = self._make_meta(requires_approval=False)
        output = _capture_output(render_agent_output, result, meta, mode="do")
        assert "Here is my answer" in output

    def test_text_talk_mode_uses_markdown(self):
        result = AgentResult(success=True, output="Here is my answer")
        meta = self._make_meta(requires_approval=False)
        output = _capture_output(render_agent_output, result, meta, mode="talk")
        assert "Here is my answer" in output

    def test_command_renders_syntax_panel(self):
        result = AgentResult(success=True, output="ls -la", warnings=[], metadata={})
        meta = self._make_meta(requires_approval=True)
        output = _capture_output(render_agent_output, result, meta)
        assert "ls -la" in output
        assert "Generated Command" in output

    def test_thinking_shown_when_flag_set(self):
        result = AgentResult(success=True, output="answer", thinking=["hmm"])
        meta = self._make_meta()
        output = _capture_output(render_agent_output, result, meta, show_thinking=True)
        assert "hmm" in output

    def test_thinking_not_shown_by_default(self):
        result = AgentResult(success=True, output="answer", thinking=["hmm"])
        meta = self._make_meta()
        output = _capture_output(render_agent_output, result, meta)
        assert "hmm" not in output

    def test_warnings_shown_for_text_response(self):
        result = AgentResult(success=True, output="answer", warnings=["be careful"])
        meta = self._make_meta(requires_approval=False)
        output = _capture_output(render_agent_output, result, meta)
        assert "be careful" in output


# ---------------------------------------------------------------------------
# ProgressiveDisplay
# ---------------------------------------------------------------------------


class TestProgressiveDisplay:
    def test_update_with_thinking_partial(self):
        """Partial result with thinking updates token count."""
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False, highlight=False)
        display = ProgressiveDisplay(test_console)

        partial = AgentResult(
            success=False,
            output="",
            partial=True,
            thinking=["let me think about this"],
            thinking_token_count=5,
        )
        # Don't start live display — just test the state update logic
        display.update(partial)
        assert display._thinking_tokens == 5
        assert display._thinking_done is False

    def test_update_with_text_partial_marks_thinking_done(self):
        """When partial has output text, thinking is marked done."""
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False, highlight=False)
        display = ProgressiveDisplay(test_console)

        partial = AgentResult(
            success=False,
            output="The answer is",
            partial=True,
            thinking_token_count=10,
        )
        display.update(partial)
        assert display._thinking_done is True
        assert display._output_text == "The answer is"

    def test_update_with_final_result(self):
        """Final result sets output and marks thinking done."""
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False, highlight=False)
        display = ProgressiveDisplay(test_console)

        final = AgentResult(
            success=True,
            output="Paris is the capital of France.",
            thinking=["Let me recall geography facts"],
        )
        display.update(final)
        assert display._thinking_done is True
        assert display._output_text == "Paris is the capital of France."
        assert display._thinking_tokens > 0

    def test_context_manager_start_stop(self):
        """Entering and exiting the context manager starts/stops Live."""
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=False, highlight=False)
        display = ProgressiveDisplay(test_console)

        with display:
            assert display._live is not None
        assert display._live is None


class TestRenderCollapsedThinking:
    def test_renders_token_count(self):
        output = _capture_output(render_collapsed_thinking, 1247)
        assert "1247" in output
        assert "thinking" in output

    def test_zero_tokens_no_output(self):
        output = _capture_output(render_collapsed_thinking, 0)
        assert output == ""
