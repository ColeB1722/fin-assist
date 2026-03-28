from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.widgets import SelectionList

if TYPE_CHECKING:
    from collections.abc import Callable

    from fin_assist.config.schema import ThinkingEffort


class ThinkingSelector(SelectionList):
    OPTIONS: list[tuple[str, str]] = [
        ("Off", "off"),
        ("Low", "low"),
        ("Medium", "medium"),
        ("High", "high"),
    ]

    def __init__(self, on_change: Callable[[ThinkingEffort], None] | None = None) -> None:
        super().__init__(*self.OPTIONS, id="thinking-selector")
        self._on_change = on_change
        self.select("medium")

    def set_value(self, value: str | None) -> None:
        if value is None:
            value = "off"
        elif value not in ("off", "low", "medium", "high"):
            value = "medium"
        self.deselect_all()
        self.select(value)

    def get_value(self) -> str | None:
        selected = self.selected
        if selected and selected[0]:
            val = str(selected[0])
            return None if val == "off" else val
        return "medium"

    def on_selection_changed(self, event: SelectionList.SelectedChanged) -> None:
        selection = event.control.selected
        if selection and self._on_change:
            value = str(selection[0])
            effort = cast("ThinkingEffort", None if value == "off" else value)
            self._on_change(effort)
