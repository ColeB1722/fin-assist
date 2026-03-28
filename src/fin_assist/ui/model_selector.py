from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import SelectionList

if TYPE_CHECKING:
    from collections.abc import Callable


class ModelSelector(SelectionList):
    def __init__(
        self,
        on_change: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(id="model-selector")
        self._on_change = on_change
        self._selected_provider: str | None = None
        self._selected_model: str | None = None

    def set_providers(
        self,
        providers: list[str],
        default: str | None = None,
    ) -> None:
        self.clear_options()
        for provider in providers:
            self.add_option((provider, provider))
        if providers:
            selected = default if default and default in providers else providers[0]
            self.select(selected)
            self._selected_provider = selected
            self._selected_model = None

    @property
    def selected_provider(self) -> str | None:
        return self._selected_provider

    @property
    def selected_model(self) -> str | None:
        return self._selected_model

    def on_selection_changed(self, event: SelectionList.SelectedChanged) -> None:
        selection = event.control.selected
        if selection:
            provider = str(selection[0])
            self._selected_provider = provider
            if self._on_change:
                self._on_change(provider, self._selected_model or "")
