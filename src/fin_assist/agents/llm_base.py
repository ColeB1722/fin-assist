"""LLMBaseAgent: intermediate base class for all pydantic-ai-backed agents.

Extracts the shared model-building infrastructure that would otherwise be
duplicated across every concrete agent (DefaultAgent, ShellAgent, future
SDDAgent, TDDAgent, etc.):

- Constructor: ``config``, ``credentials``, lazy ``_registry``
- ``supports_context``: defaults to accepting all ``ContextType`` values
- ``_get_registry``: lazy ``ProviderRegistry`` initialisation
- ``_get_enabled_providers``: reads config to build the ordered provider list
- ``_get_model_name``: per-provider model name resolution with fallback
- ``_build_model``: constructs a single model or ``FallbackModel`` from config

Concrete agents only need to implement the BaseAgent abstract interface
(``name``, ``description``, ``system_prompt``, ``output_type``, ``run``) and
their own ``_build_agent``/internal generation logic.
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, get_args

from fin_assist.agents.base import BaseAgent
from fin_assist.context.base import ContextType

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from fin_assist.config.schema import Config
    from fin_assist.credentials.store import CredentialStore


class LLMBaseAgent[T](BaseAgent[T], ABC):
    """Intermediate base providing shared model-building for pydantic-ai agents.

    Subclasses must still implement all abstract properties/methods from
    ``BaseAgent``.  What they get for free:

    - ``__init__(config, credentials)``
    - ``supports_context`` — accepts all ``ContextType`` values by default
      (override to restrict)
    - ``_build_model`` — single model or ``FallbackModel`` from config
    - ``_get_enabled_providers``, ``_get_model_name``, ``_get_registry``
    """

    def __init__(self, config: Config, credentials: CredentialStore) -> None:
        self._config = config
        self._credentials = credentials
        self._registry = None
        self._agent = None

    # ------------------------------------------------------------------
    # BaseAgent.supports_context default
    # ------------------------------------------------------------------

    _SUPPORTED_CONTEXT_TYPES: frozenset[str] = frozenset(get_args(ContextType))

    def supports_context(self, context_type: str) -> bool:
        """Accept all ContextType values by default.

        Override in subclasses that only support a subset of context types
        (e.g. a docs-only SDDAgent).
        """
        return context_type in self._SUPPORTED_CONTEXT_TYPES

    # ------------------------------------------------------------------
    # Shared model-building utilities
    # ------------------------------------------------------------------

    def _get_registry(self):
        if self._registry is None:
            from fin_assist.llm.model_registry import ProviderRegistry

            self._registry = ProviderRegistry()
        return self._registry

    def _build_model(self) -> Model:
        from pydantic_ai.models.fallback import FallbackModel

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
