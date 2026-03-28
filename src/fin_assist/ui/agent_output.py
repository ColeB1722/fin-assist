from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import VerticalScroll
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import ComposeResult


class AgentOutput(VerticalScroll):
    def __init__(self) -> None:
        super().__init__(id="agent-output")
        self._text = ""
        self._content = Static("", id="output-content")

    def compose(self) -> ComposeResult:
        yield self._content

    def update(self, text: str) -> None:
        self._text = text
        self._content.update(text)

    def append(self, text: str) -> None:
        self._text += text
        self._content.update(self._text)
