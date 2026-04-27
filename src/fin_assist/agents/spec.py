"""AgentSpec — the single agent specification class for fin-assist.

All agent behavior (system prompt, output type, thinking, serving modes,
approval) is derived from an ``AgentConfig`` instance.  There are no
subclasses — different agents are different configurations, not different
classes.

AgentSpec is a **pure config object** with zero framework imports.  All
LLM framework interaction (model construction, agent building, streaming)
lives in ``PydanticAIBackend`` (or any other ``AgentBackend`` impl).

Why no ABC?
~~~~~~~~~~~
There is only one agent implementation.  An ABC with a single impl is
ceremony.  If a type bound is needed for DI/mocking, ``typing.Protocol``
supports structural subtyping without requiring inheritance.

A Rust/Gleam agent would not subclass a Python ABC — it would serve its
own A2A endpoint over HTTP.  The interop boundary is the A2A protocol,
not Python inheritance.

Usage::

    from fin_assist.config.schema import AgentConfig
    from fin_assist.agents.spec import AgentSpec

    cfg = AgentConfig(system_prompt="shell", output_type="command", serving_modes=["do"])
    agent = AgentSpec(name="shell", agent_config=cfg, config=config, credentials=creds)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from fin_assist.agents.metadata import AgentCardMeta
from fin_assist.providers import PROVIDER_META

if TYPE_CHECKING:
    from fin_assist.config.schema import AgentConfig, Config
    from fin_assist.credentials.store import CredentialStore


class AgentSpec:
    """Config-driven agent specification whose behavior is fully specified by ``AgentConfig``.

    This replaces the former ``BaseAgent`` ABC, ``DefaultAgent``, and
    ``ShellAgent``.  Different agents are created by passing different
    ``AgentConfig`` values, not by subclassing.
    """

    _CONTEXT_TYPE_MAP: dict[str, str] = {
        "read_file": "file",
        "git_diff": "git_diff",
        "git_log": "git_log",
        "shell_history": "history",
    }

    def __init__(
        self,
        *,
        name: str,
        agent_config: AgentConfig,
        config: Config,
        credentials: CredentialStore,
    ) -> None:
        self._name = name
        self._agent_config = agent_config
        self._config = config
        self._credentials = credentials

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._agent_config.description or f"Agent: {self._name}"

    @property
    def system_prompt(self) -> str:
        from fin_assist.agents.registry import SYSTEM_PROMPTS

        prompt_name = self._agent_config.system_prompt
        if prompt_name in SYSTEM_PROMPTS:
            return SYSTEM_PROMPTS[prompt_name]
        return prompt_name

    @property
    def output_type(self) -> type[Any]:
        from fin_assist.agents.registry import OUTPUT_TYPES

        type_name = self._agent_config.output_type
        if type_name in OUTPUT_TYPES:
            return OUTPUT_TYPES[type_name]
        return str

    @property
    def thinking(self) -> Literal["off", "low", "medium", "high"] | None:
        return self._agent_config.thinking

    @property
    def default_model(self) -> str:
        return self._config.general.default_model

    @property
    def _supported_context_types(self) -> set[str]:
        return {
            self._CONTEXT_TYPE_MAP[t]
            for t in self._agent_config.tools
            if t in self._CONTEXT_TYPE_MAP
        }

    @property
    def agent_card_metadata(self) -> AgentCardMeta:
        cfg = self._agent_config
        return AgentCardMeta(
            serving_modes=cfg.serving_modes,
            supports_thinking=cfg.thinking is not None and cfg.thinking != "off",
            tags=cfg.tags,
            supported_context_types=sorted(self._supported_context_types),
        )

    @property
    def tools(self) -> list[str]:
        return self._agent_config.tools

    def supports_context(self, context_type: str) -> bool:
        return context_type in self._supported_context_types

    def check_credentials(self) -> list[str]:
        """Return names of enabled providers that require an API key but have none configured.

        An empty list means all credentials are present.
        """
        missing: list[str] = []
        for provider in self.get_enabled_providers():
            meta = PROVIDER_META.get(provider)
            if meta is not None and meta.requires_api_key and not self.get_api_key(provider):
                missing.append(provider)
        return missing

    def get_api_key(self, provider: str) -> str | None:
        return self._credentials.get_api_key(provider)

    def get_model_name(self, provider: str, default: str) -> str:
        provider_config = self._config.providers.get(provider)
        if provider_config and provider_config.default_model:
            return provider_config.default_model
        return default

    def get_enabled_providers(self) -> list[str]:
        default_provider = self._config.general.default_provider
        enabled = [default_provider]
        for name, provider_config in self._config.providers.items():
            if name != default_provider and provider_config.enabled:
                enabled.append(name)
        return enabled
