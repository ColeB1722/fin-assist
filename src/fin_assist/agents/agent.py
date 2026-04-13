"""ConfigAgent — the single agent class for fin-assist.

All agent behavior (system prompt, output type, thinking, serving modes,
approval) is derived from an ``AgentConfig`` instance.  There are no
subclasses — different agents are different configurations, not different
classes.

Why no ABC?
~~~~~~~~~~~
There is only one agent implementation.  An ABC with a single impl is
ceremony.  If a type bound is needed for DI/mocking, ``typing.Protocol``
supports structural subtyping without requiring inheritance.

A Rust/Gleam agent would not subclass a Python ABC — it would serve its
own A2A endpoint over HTTP.  The interop boundary is the A2A protocol,
not Python inheritance.

Why not pydantic-ai AgentSpec / from_spec()?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``AgentSpec`` requires a model at construction time and calls
``infer_model()`` immediately — which needs API keys.  Our architecture
defers model resolution to run time (lazy, per-task) so the hub can
start and serve discovery endpoints before credentials are configured.
``Agent(model=None, defer_model_check=True)`` gives us this, but
``from_spec()`` does not support it.  Direct ``Agent()`` construction
is the right approach for our lazy-model pattern.

``AgentConfig`` still owns everything pydantic-ai doesn't know about
(serving modes, approval, credential injection, agent card metadata).
If ``from_spec()`` gains ``defer_model_check`` support in the future,
we can adopt it as an internal construction helper.

Usage::

    from fin_assist.config.schema import AgentConfig
    from fin_assist.agents.agent import ConfigAgent

    cfg = AgentConfig(system_prompt="shell", output_type="command", serving_modes=["do"])
    agent = ConfigAgent(name="shell", agent_config=cfg, config=config, credentials=creds)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, get_args

from fin_assist.agents.metadata import AgentCardMeta, MissingCredentialsError
from fin_assist.context.base import ContextType
from fin_assist.providers import PROVIDER_META

if TYPE_CHECKING:
    from pydantic_ai import Agent as PydanticAgent
    from pydantic_ai.models import Model

    from fin_assist.config.schema import AgentConfig, Config
    from fin_assist.credentials.store import CredentialStore
    from fin_assist.llm.model_registry import ProviderRegistry


class ConfigAgent:
    """Config-driven agent whose behavior is fully specified by ``AgentConfig``.

    This replaces the former ``BaseAgent`` ABC, ``DefaultAgent``, and
    ``ShellAgent``.  Different agents are created by passing different
    ``AgentConfig`` values, not by subclassing.
    """

    _SUPPORTED_CONTEXT_TYPES: frozenset[str] = frozenset(get_args(ContextType))

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
        self._registry: ProviderRegistry | None = None

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
    def agent_card_metadata(self) -> AgentCardMeta:
        cfg = self._agent_config
        return AgentCardMeta(
            serving_modes=cfg.serving_modes,
            multi_turn="talk" in cfg.serving_modes,
            supports_thinking=cfg.thinking is not None and cfg.thinking != "off",
            tags=cfg.tags,
            requires_approval=cfg.requires_approval,
        )

    def supports_context(self, context_type: str) -> bool:
        return context_type in self._SUPPORTED_CONTEXT_TYPES

    def build_pydantic_agent(self) -> PydanticAgent[Any, Any]:
        """Build the pydantic-ai Agent that the FinAssistWorker will execute.

        The Agent is constructed **without a model** — pydantic-ai accepts
        ``model=None`` at construction and resolves it at run time via the
        ``model`` parameter on ``agent.run()``.  This lets the hub start and
        serve discovery/health endpoints even when credentials are not yet
        configured.

        We use direct ``Agent()`` construction rather than ``Agent.from_spec()``
        because ``from_spec()`` requires a model immediately and calls
        ``infer_model()`` (which needs API keys).  See module docstring for
        the full rationale.
        """
        from pydantic_ai import Agent
        from pydantic_ai.capabilities import Thinking

        thinking_effort = self._agent_config.thinking
        capabilities = (
            [Thinking(effort=thinking_effort)]
            if thinking_effort and thinking_effort != "off"
            else None
        )
        return Agent(
            output_type=self.output_type,
            instructions=self.system_prompt,
            capabilities=capabilities,
        )

    def check_credentials(self) -> list[str]:
        """Return names of enabled providers that require an API key but have none configured.

        An empty list means all credentials are present.
        """
        missing: list[str] = []
        for provider in self._get_enabled_providers():
            meta = PROVIDER_META.get(provider)
            if (
                meta is not None
                and meta.requires_api_key
                and not self._credentials.get_api_key(provider)
            ):
                missing.append(provider)
        return missing

    def build_model(self) -> Model:
        from pydantic_ai.models.fallback import FallbackModel

        missing = self.check_credentials()
        if missing:
            raise MissingCredentialsError(providers=missing)

        default_model = self._config.general.default_model
        enabled_providers = self._get_enabled_providers()

        if len(enabled_providers) == 1:
            provider_name = enabled_providers[0]
            model_name = self._get_model_name(provider_name, default_model)
            api_key = self._credentials.get_api_key(provider_name)
            return self._get_registry().create_model(provider_name, model_name, api_key=api_key)

        models = []
        for provider_name in enabled_providers:
            model_name = self._get_model_name(provider_name, default_model)
            api_key = self._credentials.get_api_key(provider_name)
            model = self._get_registry().create_model(provider_name, model_name, api_key=api_key)
            models.append(model)

        return FallbackModel(*models)

    def _get_registry(self) -> ProviderRegistry:
        if self._registry is None:
            from fin_assist.llm.model_registry import ProviderRegistry

            self._registry = ProviderRegistry()
        return self._registry

    def _get_model_name(self, provider: str, default: str) -> str:
        provider_config = self._config.providers.get(provider)
        if provider_config and provider_config.default_model:
            return provider_config.default_model
        return default

    def _get_enabled_providers(self) -> list[str]:
        default_provider = self._config.general.default_provider
        enabled = [default_provider]
        for name, provider_config in self._config.providers.items():
            if name != default_provider and provider_config.enabled:
                enabled.append(name)
        return enabled
