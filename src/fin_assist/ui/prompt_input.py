from __future__ import annotations

from textual.widgets import TextArea


class PromptInput(TextArea):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Enter your request...",
            id="prompt-input",
        )
