from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import SelectionList

if TYPE_CHECKING:
    from collections.abc import Callable


class AgentSelector(SelectionList):
    def __init__(
        self,
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(id="agent-selector")
        self._on_change = on_change
        self._selected_agent: str | None = None

    def set_agents(self, agents: list[tuple[str, str]]) -> None:
        self.clear_options()
        for name, description in agents:
            self.add_option((description, name))
        if agents:
            self.select(agents[0][0])
            self._selected_agent = agents[0][0]

    @property
    def selected_agent(self) -> str | None:
        return self._selected_agent

    def on_selection_changed(self, event: SelectionList.SelectedChanged) -> None:
        selection = event.control.selected
        if selection:
            self._selected_agent = str(selection[0] if selection else None)
            if self._on_change:
                self._on_change(self._selected_agent)
