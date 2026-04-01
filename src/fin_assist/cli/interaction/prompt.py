"""FinPrompt — prompt_toolkit-backed input widget with fuzzy completion and history."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import FuzzyCompleter, WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

HISTORY_PATH = Path("~/.local/share/fin/history").expanduser()


class FinPrompt:
    """Reusable prompt_toolkit session with slash-command fuzzy completion.

    Features:
    - Fuzzy completion for slash commands (/exit, /quit, /q, /switch, /help)
    - Tab completion for agent names when configured
    - Persistent history across sessions
    - Readline-style keybindings
    """

    SLASH_COMMANDS = ["/exit", "/quit", "/q", "/switch", "/help"]

    def __init__(
        self,
        agents: list[str] | None = None,
        history_path: Path = HISTORY_PATH,
    ) -> None:
        self.agents = agents or []
        self.history_path = history_path

    def _build_completer(self) -> FuzzyCompleter:
        words = self.SLASH_COMMANDS + self.agents
        word_completer = WordCompleter(words, ignore_case=True)
        return FuzzyCompleter(word_completer)

    def _build_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("c-c", eager=True)
        def _interrupt(event):
            raise KeyboardInterrupt()

        @kb.add("c-d", eager=True)
        def _eof(event):
            raise EOFError()

        return kb

    def _build_session(self) -> PromptSession[str]:
        return PromptSession(
            completer=self._build_completer(),
            history=FileHistory(self.history_path),
            key_bindings=self._build_key_bindings(),
            style=Style.from_dict({"": "#ansibrightgreen"}),
        )

    async def ask(self, prompt_text: str) -> str:
        """Prompt for input with completion and history.

        Args:
            prompt_text: The prompt text to display.

        Returns:
            The user's input string (may be empty).
        """
        try:
            session = self._build_session()
            return await session.prompt_async(prompt_text)
        except (KeyboardInterrupt, EOFError):
            return ""
