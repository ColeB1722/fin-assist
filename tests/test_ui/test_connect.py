from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fin_assist.credentials.store import CredentialStore
from fin_assist.llm.model_registry import ProviderRegistry


@pytest.fixture
def mock_credentials_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    creds_file = tmp_path / "credentials.json"
    monkeypatch.setattr("fin_assist.credentials.store.CREDENTIALS_FILE", creds_file)
    return creds_file


@pytest.fixture
def credential_store(mock_credentials_file: Path) -> CredentialStore:
    with patch.dict("os.environ", {}, clear=True):
        return CredentialStore()


@pytest.fixture
def provider_registry() -> ProviderRegistry:
    return ProviderRegistry()


class TestProviderList:
    def test_providers_from_registry(self, provider_registry: ProviderRegistry) -> None:
        from fin_assist.providers import PROVIDER_META

        providers = provider_registry.list_providers()
        for provider in providers:
            assert provider in PROVIDER_META

    def test_all_known_providers_in_options(self) -> None:
        from fin_assist.providers import PROVIDER_META

        expected = {"anthropic", "openai", "openrouter", "google", "ollama", "custom"}
        assert set(PROVIDER_META.keys()) == expected


class TestConnectDialogInit:
    def test_dialog_initializes_with_step_1(self) -> None:
        from fin_assist.ui.connect import ConnectDialog

        dialog = ConnectDialog(credential_store=CredentialStore())
        assert dialog._step == ConnectDialog.Step.SELECT_PROVIDER

    def test_no_provider_selected_initially(self) -> None:
        from fin_assist.ui.connect import ConnectDialog

        dialog = ConnectDialog(credential_store=CredentialStore())
        assert dialog._selected_provider is None

    def test_next_button_disabled_without_selection(self) -> None:
        from fin_assist.ui.connect import ConnectDialog

        dialog = ConnectDialog(credential_store=CredentialStore())
        assert dialog._selected_provider is None


class TestConnectDialogStep2:
    def test_custom_provider_skips_api_key_step(self) -> None:
        from fin_assist.ui.connect import ConnectDialog

        dialog = ConnectDialog(credential_store=CredentialStore())
        dialog._selected_provider = "custom"
        dialog._go_to_step(ConnectDialog.Step.ENTER_API_KEY)
        assert dialog._step == ConnectDialog.Step.CONFIRM

    def test_ollama_provider_skips_api_key_step(self) -> None:
        from fin_assist.ui.connect import ConnectDialog

        dialog = ConnectDialog(credential_store=CredentialStore())
        dialog._selected_provider = "ollama"
        dialog._go_to_step(ConnectDialog.Step.ENTER_API_KEY)
        assert dialog._step == ConnectDialog.Step.CONFIRM

    def test_anthroopic_requires_api_key(self) -> None:
        from fin_assist.ui.connect import ConnectDialog

        dialog = ConnectDialog(credential_store=CredentialStore())
        dialog._selected_provider = "anthropic"
        dialog._go_to_step(ConnectDialog.Step.ENTER_API_KEY)
        assert dialog._step == ConnectDialog.Step.ENTER_API_KEY


class TestConnectDialogSave:
    def test_save_credentials_calls_store(self, credential_store: CredentialStore) -> None:
        from fin_assist.ui.connect import ConnectDialog

        with patch.object(credential_store, "set_api_key") as mock_set:
            dialog = ConnectDialog(credential_store=credential_store)
            dialog._selected_provider = "anthropic"
            dialog._api_key = "sk-test-key"
            dialog._use_keyring = False
            dialog._save_credentials()
            mock_set.assert_called_once_with("anthropic", "sk-test-key")

    def test_save_credentials_with_keyring(self, credential_store: CredentialStore) -> None:
        from fin_assist.ui.connect import ConnectDialog

        with patch.object(credential_store, "set_api_key"):
            with patch("fin_assist.ui.connect._set_keyring_key") as mock_keyring:
                dialog = ConnectDialog(credential_store=credential_store)
                dialog._selected_provider = "anthropic"
                dialog._api_key = "sk-test-key"
                dialog._use_keyring = True
                dialog._save_credentials()
                mock_keyring.assert_called_once_with("anthropic", "sk-test-key")

    def test_save_keyring_fallback_on_error(self, credential_store: CredentialStore) -> None:
        from fin_assist.ui.connect import ConnectDialog

        with patch.object(credential_store, "set_api_key", side_effect=Exception("Disk full")):
            dialog = ConnectDialog(credential_store=credential_store)
            dialog._selected_provider = "anthropic"
            dialog._api_key = "sk-test-key"
            dialog._use_keyring = False
            dialog._save_credentials()
            assert dialog._error_message is not None


class TestConnectDialogCancel:
    def test_cancel_dismisses_dialog(self) -> None:
        from fin_assist.ui.connect import ConnectDialog

        dialog = ConnectDialog(credential_store=CredentialStore())
        dialog._cancelled = True
        assert dialog._cancelled is True

    def test_cancel_does_not_save(self, credential_store: CredentialStore) -> None:
        from fin_assist.ui.connect import ConnectDialog

        with patch.object(credential_store, "set_api_key") as mock_set:
            dialog = ConnectDialog(credential_store=credential_store)
            dialog._cancelled = True
            mock_set.assert_not_called()


class TestConnectDialogKeyring:
    def test_keyring_available_respects_init_param(self) -> None:
        from fin_assist.ui.connect import ConnectDialog

        dialog = ConnectDialog(
            credential_store=CredentialStore(),
            keyring_available=False,
        )
        assert dialog._keyring_available is False

    def test_keyring_available_true_by_default(self) -> None:
        from fin_assist.ui.connect import ConnectDialog

        dialog = ConnectDialog(credential_store=CredentialStore())
        assert dialog._keyring_available is True


class TestConnectDialogNavigation:
    def test_go_to_step_1_resets_ui_state(self) -> None:
        from fin_assist.ui.connect import ConnectDialog

        dialog = ConnectDialog(credential_store=CredentialStore())
        dialog._step = ConnectDialog.Step.ENTER_API_KEY
        dialog._go_to_step(ConnectDialog.Step.SELECT_PROVIDER)
        assert dialog._step == ConnectDialog.Step.SELECT_PROVIDER

    def test_go_to_step_3_with_error_message(self) -> None:
        from fin_assist.ui.connect import ConnectDialog

        dialog = ConnectDialog(credential_store=CredentialStore())
        dialog._selected_provider = "anthropic"
        dialog._api_key = "sk-test-key"
        dialog._use_keyring = False
        dialog._error_message = None
        dialog._go_to_step(ConnectDialog.Step.CONFIRM)
        assert dialog._step == ConnectDialog.Step.CONFIRM


class TestProviderRequiresApiKey:
    def test_providers_requiring_api_key(self) -> None:
        from fin_assist.providers import get_providers_requiring_api_key

        providers = get_providers_requiring_api_key()
        assert "anthropic" in providers
        assert "openai" in providers
        assert "openrouter" in providers
        assert "google" in providers

    def test_providers_not_requiring_api_key(self) -> None:
        from fin_assist.providers import get_providers_requiring_api_key

        providers = get_providers_requiring_api_key()
        assert "custom" not in providers
        assert "ollama" not in providers
