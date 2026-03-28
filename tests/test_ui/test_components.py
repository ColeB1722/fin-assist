from __future__ import annotations

import pytest

from fin_assist.ui.agent_output import AgentOutput
from fin_assist.ui.agent_selector import AgentSelector
from fin_assist.ui.model_selector import ModelSelector
from fin_assist.ui.prompt_input import PromptInput
from fin_assist.ui.thinking_selector import ThinkingSelector


class TestPromptInput:
    def test_initializes_with_placeholder(self) -> None:
        input_widget = PromptInput()
        assert input_widget.placeholder == "Enter your request..."

    def test_has_correct_id(self) -> None:
        input_widget = PromptInput()
        assert input_widget.id == "prompt-input"


class TestAgentOutput:
    def test_initializes_empty(self) -> None:
        output = AgentOutput()
        assert output._text == ""

    def test_update_sets_text(self) -> None:
        output = AgentOutput()
        output.update("Hello")
        assert output._text == "Hello"

    def test_append_concatenates_text(self) -> None:
        output = AgentOutput()
        output.update("Hello")
        output.append(" World")
        assert output._text == "Hello World"


class TestAgentSelector:
    def test_set_agents_populates_options(self) -> None:
        selector = AgentSelector()
        agents = [("default", "Default Agent"), ("shell", "Shell Agent")]
        selector.set_agents(agents)
        assert selector.selected_agent == "default"

    def test_initial_selected_agent_is_none(self) -> None:
        selector = AgentSelector()
        assert selector.selected_agent is None


class TestModelSelector:
    def test_set_providers_populates_options(self) -> None:
        selector = ModelSelector()
        providers = ["anthropic", "openai", "ollama"]
        selector.set_providers(providers, default="openai")
        assert selector.selected_provider == "openai"

    def test_initial_selected_provider_is_none(self) -> None:
        selector = ModelSelector()
        assert selector.selected_provider is None


class TestThinkingSelector:
    def test_initializes_with_medium_selected(self) -> None:
        selector = ThinkingSelector()
        assert selector.get_value() == "medium"

    def test_set_value_off_returns_none(self) -> None:
        selector = ThinkingSelector()
        selector.set_value("off")
        assert selector.get_value() is None

    def test_set_value_low_returns_low(self) -> None:
        selector = ThinkingSelector()
        selector.set_value("low")
        assert selector.get_value() == "low"

    def test_set_value_none_returns_none(self) -> None:
        selector = ThinkingSelector()
        selector.set_value(None)
        assert selector.get_value() is None

    def test_set_value_invalid_defaults_to_medium(self) -> None:
        selector = ThinkingSelector()
        selector.set_value("invalid")
        assert selector.get_value() == "medium"
