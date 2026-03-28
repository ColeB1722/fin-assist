from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from fin_assist.agents.default import DefaultAgent
from fin_assist.ui.agent_output import AgentOutput
from fin_assist.ui.agent_selector import AgentSelector
from fin_assist.ui.model_selector import ModelSelector
from fin_assist.ui.prompt_input import PromptInput
from fin_assist.ui.settings_screen import SettingsScreen
from fin_assist.ui.thinking_selector import ThinkingSelector

if TYPE_CHECKING:
    from fin_assist.agents.base import BaseAgent
    from fin_assist.config.schema import Config, ThinkingEffort
    from fin_assist.credentials.store import CredentialStore


class FinAssistApp(App):
    CSS = """
    #header {
        height: 3;
        background: $surface;
    }
    #output-area {
        height: 1fr;
        background: $surface;
    }
    #input-area {
        height: 5;
        dock: bottom;
        background: $surface;
    }
    #prompt-input {
        height: 1fr;
    }
    """

    def __init__(
        self,
        config: Config,
        credentials: CredentialStore,
        default_agent: BaseAgent | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._credentials = credentials
        self._current_agent = default_agent
        self._output = AgentOutput()
        self._prompt_input = PromptInput()
        self._agent_selector = AgentSelector(on_change=self._on_agent_changed)
        self._model_selector = ModelSelector(on_change=self._on_model_changed)
        self._thinking_selector = ThinkingSelector(on_change=self._on_thinking_changed)
        self._run_button = Button("Run", id="run-btn", variant="primary")
        self._settings_button = Button("\u2699", id="settings-btn", variant="default")

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static("fin-assist", id="title")
            yield self._agent_selector
            yield self._model_selector
            yield self._thinking_selector
            yield self._settings_button

        with Vertical(id="output-area"):
            yield self._output

        with Horizontal(id="input-area"):
            yield self._prompt_input
            yield self._run_button

    def on_mount(self) -> None:
        self._initialize_components()

    def _initialize_components(self) -> None:
        providers = list(self._config.providers.keys()) or ["anthropic"]
        default_provider = self._config.general.default_provider
        self._model_selector.set_providers(providers, default=default_provider)

        agents = [("default", "General-purpose assistant")]
        self._agent_selector.set_agents(agents)

        thinking_effort = self._config.general.thinking_effort
        self._thinking_selector.set_value(thinking_effort)

        if self._current_agent is None:
            self._current_agent = DefaultAgent(self._config, self._credentials)

    def _on_agent_changed(self, agent_name: str) -> None:
        self.notify(f"Agent changed to: {agent_name}")

    def _on_model_changed(self, provider: str, model: str) -> None:
        self.notify(f"Provider changed to: {provider}")

    def _on_thinking_changed(self, effort: ThinkingEffort) -> None:
        self._config.general.thinking_effort = effort
        if isinstance(self._current_agent, DefaultAgent):
            self._current_agent._agent = None
        self.notify(f"Thinking set to: {effort or 'off'}")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run-btn":
            await self._run_agent()
        elif event.button.id == "settings-btn":
            self._show_settings()

    async def _run_agent(self) -> None:
        prompt = self._prompt_input.text
        if not prompt:
            return

        self._output.update(f"Running agent...\n\nUser: {prompt}\n\nAgent: ")
        self._run_button.disabled = True

        try:
            if self._current_agent:
                result = await self._current_agent.run(prompt, [])
                self._output.append(f"\n\nResult: {result.output}")
                if result.warnings:
                    self._output.append(f"\n\nWarnings: {result.warnings}")
        except Exception as e:
            self._output.append(f"\n\nError: {e}")
        finally:
            self._run_button.disabled = False

    def _show_settings(self) -> None:
        settings = SettingsScreen(credential_store=self._credentials)
        self.push_screen(settings)
