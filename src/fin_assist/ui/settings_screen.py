from __future__ import annotations

from typing import TYPE_CHECKING

from textual.screen import ModalScreen

from fin_assist.ui.connect import ConnectDialog

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from fin_assist.credentials.store import CredentialStore


class SettingsScreen(ModalScreen):
    def __init__(self, credential_store: CredentialStore) -> None:
        super().__init__()
        self._credential_store = credential_store

    def compose(self) -> ComposeResult:
        yield ConnectDialog(credential_store=self._credential_store)
