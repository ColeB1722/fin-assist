from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.general.default_provider = "anthropic"
    config.general.default_model = "claude-sonnet-4-6"
    config.providers = {}
    return config


@pytest.fixture
def mock_credentials():
    creds = MagicMock()
    creds.get_api_key.return_value = "test-key"
    return creds


@pytest.fixture
def expected_context_types():
    from fin_assist.context.base import ContextType

    return frozenset(ContextType.__args__)
