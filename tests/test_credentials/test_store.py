from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fin_assist.credentials.store import CredentialStore


@pytest.fixture
def mock_env_vars() -> dict[str, str]:
    return {}


@pytest.fixture
def mock_credentials_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    creds_file = tmp_path / "credentials.json"
    monkeypatch.setattr("fin_assist.credentials.store.CREDENTIALS_FILE", creds_file)
    return creds_file


@pytest.fixture
def credential_store(mock_env_vars: dict[str, str], mock_credentials_file: Path) -> CredentialStore:
    with patch.dict("os.environ", mock_env_vars, clear=True):
        return CredentialStore()


class TestCredentialStoreGetApiKey:
    def test_returns_env_var_when_set(
        self,
        mock_env_vars: dict[str, str],
        mock_credentials_file: Path,
    ) -> None:
        mock_env_vars["ANTHROPIC_API_KEY"] = "env-key-123"
        with patch.dict("os.environ", mock_env_vars, clear=True):
            store = CredentialStore()
            result = store.get_api_key("anthropic")
        assert result == "env-key-123"

    def test_returns_file_value_when_env_not_set(
        self,
        mock_credentials_file: Path,
    ) -> None:
        mock_credentials_file.write_text('{"anthropic": {"api_key": "file-key-456"}}')
        with patch.dict("os.environ", {}, clear=True):
            store = CredentialStore()
            result = store.get_api_key("anthropic")
        assert result == "file-key-456"

    def test_env_var_takes_precedence_over_file(
        self,
        mock_env_vars: dict[str, str],
        mock_credentials_file: Path,
    ) -> None:
        mock_env_vars["ANTHROPIC_API_KEY"] = "env-key-789"
        mock_credentials_file.write_text('{"anthropic": {"api_key": "file-key-999"}}')
        with patch.dict("os.environ", mock_env_vars, clear=True):
            store = CredentialStore()
            result = store.get_api_key("anthropic")
        assert result == "env-key-789"

    def test_returns_none_when_not_found(
        self,
        mock_credentials_file: Path,
    ) -> None:
        mock_credentials_file.write_text("{}")
        with patch.dict("os.environ", {}, clear=True):
            store = CredentialStore()
            result = store.get_api_key("anthropic")
        assert result is None

    def test_returns_none_for_missing_file(
        self,
        mock_credentials_file: Path,
    ) -> None:
        if mock_credentials_file.exists():
            mock_credentials_file.unlink()
        with patch.dict("os.environ", {}, clear=True):
            store = CredentialStore()
            result = store.get_api_key("anthropic")
        assert result is None

    def test_falls_back_to_keyring_when_file_missing(
        self,
        mock_credentials_file: Path,
    ) -> None:
        if mock_credentials_file.exists():
            mock_credentials_file.unlink()
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "fin_assist.credentials.store.keyring.get_password",
                return_value="keyring-key",
            ):
                store = CredentialStore()
                result = store.get_api_key("anthropic")
        assert result == "keyring-key"


class TestCredentialStoreSetApiKey:
    def test_writes_api_key_to_file(
        self,
        mock_credentials_file: Path,
    ) -> None:
        with patch.dict("os.environ", {}, clear=True):
            store = CredentialStore()
            store.set_api_key("anthropic", "new-key-123")

        import json

        data = json.loads(mock_credentials_file.read_text())
        assert data["anthropic"]["api_key"] == "new-key-123"
        assert "created_at" in data["anthropic"]

    def test_preserves_existing_credentials(
        self,
        mock_credentials_file: Path,
    ) -> None:
        mock_credentials_file.write_text('{"openrouter": {"api_key": "existing-key"}}')
        with patch.dict("os.environ", {}, clear=True):
            store = CredentialStore()
            store.set_api_key("anthropic", "new-key")

        import json

        data = json.loads(mock_credentials_file.read_text())
        assert data["openrouter"]["api_key"] == "existing-key"
        assert data["anthropic"]["api_key"] == "new-key"

    def test_overwrites_existing_key(
        self,
        mock_credentials_file: Path,
    ) -> None:
        mock_credentials_file.write_text('{"anthropic": {"api_key": "old-key"}}')
        with patch.dict("os.environ", {}, clear=True):
            store = CredentialStore()
            store.set_api_key("anthropic", "new-key")

        import json

        data = json.loads(mock_credentials_file.read_text())
        assert data["anthropic"]["api_key"] == "new-key"
