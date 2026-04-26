"""FinPrompt — prompt_toolkit-backed input widget with fuzzy completion and history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, FuzzyCompleter, WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

if TYPE_CHECKING:
    from pathlib import Path

    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.document import Document

from fin_assist.paths import HISTORY_PATH


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str = ""


SLASH_COMMANDS: list[SlashCommand] = [
    SlashCommand("/exit", "End the conversation"),
    SlashCommand("/help", "Show this help message"),
    SlashCommand("/sessions", "List saved sessions for this agent"),
]


class SlashCompleter(Completer):
    """Completer that only activates when the input starts with ``/``.

    Delegates to *inner* (typically a ``FuzzyCompleter``) for the actual
    completion candidates — but yields nothing when the user is typing
    ordinary chat text.
    """

    def __init__(self, inner: Completer) -> None:
        self.inner = inner

    def get_completions(self, document: Document, complete_event: CompleteEvent):  # noqa: ANN201
        """Yield completions only when the current line starts with ``/``."""
        if not document.text_before_cursor.lstrip().startswith("/"):
            return
        yield from self.inner.get_completions(document, complete_event)


class FinPrompt:
    """Reusable prompt_toolkit session with slash-command fuzzy completion.

    Features:
    - Fuzzy completion for slash commands (defined in SLASH_COMMANDS)
    - Tab completion for agent names when configured
    - Persistent history across sessions
    - Readline-style keybindings
    """

    def __init__(
        self,
        agents: list[str] | None = None,
        history_path: Path = HISTORY_PATH,
    ) -> None:
        self.agents = agents or []
        self.history_path = history_path

    def _build_completer(self) -> SlashCompleter:
        words = [cmd.name for cmd in SLASH_COMMANDS] + self.agents
        word_completer = WordCompleter(words, ignore_case=True)
        return SlashCompleter(FuzzyCompleter(word_completer))

    def _build_session(self) -> PromptSession[str]:
        return PromptSession(
            completer=self._build_completer(),
            history=FileHistory(self.history_path),
            style=Style.from_dict({"": "#ansibrightgreen"}),
        )

    async def ask(self, prompt_text: str, *, default: str | None = None) -> str:
        """Prompt for input with completion and history.

        Args:
            prompt_text: The prompt text to display.
            default: Optional default text to pre-fill the input with.

        Returns:
            The user's input string (may be empty).

        Raises:
            KeyboardInterrupt: When the user presses Ctrl+C.
            EOFError: When the user presses Ctrl+D.
        """
        session = self._build_session()
        return await session.prompt_async(prompt_text, default=default or "")
