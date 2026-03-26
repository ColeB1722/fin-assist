from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING, cast

from textual import on
from textual.containers import Vertical
from textual.widgets import Button, Checkbox, Input, Static

from fin_assist.providers import PROVIDER_META, get_providers_requiring_api_key

if TYPE_CHECKING:
    from fin_assist.credentials.store import CredentialStore


_PROVIDERS_REQUIRING_API_KEY = get_providers_requiring_api_key()


class ConnectDialog(Static):
    class Step(IntEnum):
        SELECT_PROVIDER = 1
        ENTER_API_KEY = 2
        CONFIRM = 3

    def __init__(
        self,
        credential_store: CredentialStore,
        keyring_available: bool = True,
    ) -> None:
        super().__init__()
        self._credential_store = credential_store
        self._keyring_available = keyring_available
        self._step = self.Step.SELECT_PROVIDER
        self._selected_provider: str | None = None
        self._api_key = ""
        self._use_keyring = False
        self._error_message: str | None = None
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def compose(self):
        yield Static("Connect to Provider", id="title")
        with Vertical(id="provider-buttons"):
            for provider_key, meta in PROVIDER_META.items():
                yield Button(meta.display, id=f"provider-{provider_key}", variant="default")
        yield Button("Next", id="next-btn", disabled=True)
        yield Button("Cancel", id="cancel-btn")
        yield Input(placeholder="Enter API key", password=True, id="api-key-input")
        yield Checkbox("Save to keyring", id="use-keyring-check")
        yield Button("Back", id="back-btn")
        yield Button("Save", id="save-btn", disabled=True)
        yield Static("", id="status-message")

    def on_mount(self) -> None:
        self._refresh_ui()

    # ── Navigation ────────────────────────────────────────────────────────────

    def _go_to_step(self, step: Step | int) -> None:
        step_num = int(step)
        if (
            step_num == self.Step.ENTER_API_KEY
            and self._selected_provider is not None
            and not self._requires_api_key
        ):
            step_num = self.Step.CONFIRM
        self._step = self.Step(step_num)
        if self.is_mounted:
            self._refresh_ui()

    @property
    def _requires_api_key(self) -> bool:
        return self._selected_provider in _PROVIDERS_REQUIRING_API_KEY

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _refresh_ui(self) -> None:
        self._update_title()
        self._show_step()

    def _update_title(self) -> None:
        title = self.query_one("#title", Static)
        match self._step:
            case self.Step.SELECT_PROVIDER:
                title.update("Connect to Provider")
            case self.Step.ENTER_API_KEY:
                meta = PROVIDER_META.get(self._selected_provider or "")
                title.update(
                    f"Enter API Key for {meta.display if meta else self._selected_provider}"
                )
            case self.Step.CONFIRM:
                title.update("Connection Saved")

    def _show_step(self) -> None:
        match self._step:
            case self.Step.SELECT_PROVIDER:
                self._show_provider_step()
            case self.Step.ENTER_API_KEY:
                self._show_api_key_step()
            case self.Step.CONFIRM:
                self._show_confirm_step()

    def _show_provider_step(self) -> None:
        self._set_display("#provider-buttons", True)
        self._set_display("#next-btn", True)
        self._set_display("#cancel-btn", True)
        self._set_display("#api-key-input", False)
        self._set_display("#use-keyring-check", False)
        self._set_display("#back-btn", False)
        self._set_display("#save-btn", False)
        self.query_one("#status-message", Static).update("")

    def _show_api_key_step(self) -> None:
        self._set_display("#provider-buttons", False)
        self._set_display("#next-btn", False)
        self._set_display("#cancel-btn", True)
        self._set_display("#api-key-input", True)
        self.query_one("#api-key-input", Input).value = ""
        self._set_display("#use-keyring-check", self._keyring_available)
        self._set_display("#back-btn", True)
        self._set_display("#save-btn", True)
        self.query_one("#save-btn", Button).disabled = True
        self.query_one("#status-message", Static).update("")

    def _show_confirm_step(self) -> None:
        self._set_display("#provider-buttons", False)
        self._set_display("#next-btn", False)
        self._set_display("#cancel-btn", False)
        self._set_display("#api-key-input", False)
        self._set_display("#use-keyring-check", False)
        self._set_display("#back-btn", False)
        self._set_display("#save-btn", False)
        status = self.query_one("#status-message", Static)
        if self._error_message:
            status.update(f"[red]{self._error_message}[/red]")
        else:
            status.update(f"[green]API key saved for {self._selected_provider}[/green]")

    def _set_display(self, selector: str, visible: bool) -> None:
        widget = self.query_one(selector)
        widget.display = visible

    # ── Provider Selection ────────────────────────────────────────────────────

    def _select_provider(self, provider: str) -> None:
        self._selected_provider = provider
        self.query_one("#next-btn", Button).disabled = False
        for btn in self.query("#provider-buttons Button"):
            btn_id = btn.id
            if btn_id and btn_id.startswith("provider-"):
                key = btn_id[len("provider-") :]
                cast("Button", btn).variant = "primary" if key == provider else "default"

    # ── Event Handlers ───────────────────────────────────────────────────────

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if not button_id:
            return
        match button_id:
            case "next-btn":
                self._go_to_step(self.Step.ENTER_API_KEY)
            case "back-btn":
                self._go_to_step(self.Step.SELECT_PROVIDER)
            case "save-btn":
                self._save_credentials()
            case "cancel-btn":
                self._cancelled = True
            case _ if button_id.startswith("provider-"):
                self._select_provider(button_id[len("provider-") :])

    @on(Input.Changed, "#api-key-input")
    def on_api_key_changed(self, event: Input.Changed) -> None:
        self._api_key = event.value
        self.query_one("#save-btn", Button).disabled = not bool(event.value)

    @on(Checkbox.Changed, "#use-keyring-check")
    def on_keyring_changed(self, event: Checkbox.Changed) -> None:
        self._use_keyring = bool(event.value)

    # ── Credential Saving ─────────────────────────────────────────────────────

    def _save_credentials(self) -> None:
        if not self._selected_provider or not self._api_key:
            return

        try:
            self._credential_store.set_api_key(self._selected_provider, self._api_key)
            if self._use_keyring:
                _set_keyring_key(self._selected_provider, self._api_key)
            self._error_message = None
        except Exception as e:
            self._error_message = str(e)

        self._go_to_step(self.Step.CONFIRM)


def keyring_available() -> bool:
    from fin_assist.credentials.store import keyring_available as check

    return check()


def _set_keyring_key(provider: str, api_key: str) -> None:
    from fin_assist.credentials.store import set_keyring_key as store

    store(provider, api_key)
