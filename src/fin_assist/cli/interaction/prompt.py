"""FinPrompt — prompt_toolkit-backed input widget with fuzzy completion and history.

Supports two completion modes:

- ``/`` triggers **slash commands** (actions like /exit, /help, /sessions).
- ``@`` triggers **context injection** (@file:path, @git:diff, @git:log,
  @history:query).  After the user submits, ``resolve_at_references``
  replaces ``@type:ref`` tokens with resolved context content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, FuzzyCompleter, WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

if TYPE_CHECKING:
    from pathlib import Path

    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.document import Document

    from fin_assist.config.schema import ContextSettings

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


_AT_CONTEXT_TYPES: dict[str, str] = {
    "file:": "Inject file contents",
    "git:diff": "Inject git diff",
    "git:log": "Inject git log",
    "history:": "Inject shell history",
}


class AtCompleter(Completer):
    """Completer that activates when the input contains ``@`` at the cursor.

    Yields context-type completions (``file:``, ``git:diff``, etc.) and,
    for ``@file:``, delegates to ``FileFinder.search()`` for path-based
    file completion.
    """

    def __init__(self, context_settings: ContextSettings | None = None) -> None:
        self._context_settings = context_settings

    def get_completions(self, document: Document, complete_event: CompleteEvent):  # noqa: ANN201
        text = document.text_before_cursor
        at_pos = text.rfind("@")
        if at_pos == -1:
            return

        after_at = text[at_pos + 1 :]
        prefix_len = len(after_at)

        if not after_at or ":" not in after_at:
            for name, desc in _AT_CONTEXT_TYPES.items():
                if name.startswith(after_at):
                    yield Completion(
                        name,
                        start_position=-prefix_len,
                        display=name,
                        display_meta=desc,
                    )
            return

        if after_at.startswith("file:"):
            file_prefix = after_at[len("file:") :]
            yield from self._file_completions(file_prefix)

    def _file_completions(self, prefix: str):  # type: ignore[no-untyped-def]
        from fin_assist.context.files import FileFinder

        finder = FileFinder(settings=self._context_settings)  # type: ignore[arg-type]
        results = finder.search(prefix if prefix else "")
        for item in results:
            if item.status == "available":
                yield Completion(
                    item.id,
                    start_position=-len(prefix) if prefix else 0,
                    display=item.id,
                    display_meta="file",
                )


_AT_PATTERN = re.compile(r"@(\w+:\S*)")


def resolve_at_references(
    text: str,
    context_settings: ContextSettings | None = None,
) -> str:
    """Replace ``@type:ref`` tokens in *text* with resolved context content.

    Supported references:

    - ``@file:<path>`` — file contents via ``FileFinder``
    - ``@git:diff`` — git diff via ``GitContext``
    - ``@git:log`` — git log via ``GitContext``
    - ``@history:`` or ``@history:<query>`` — shell history

    Unrecognised ``@type:ref`` tokens are left as-is (not an error).
    """
    context_sections: list[str] = []
    remaining = text

    for match in _AT_PATTERN.finditer(text):
        ref = match.group(1)
        resolved = _resolve_single_ref(ref, context_settings)
        if resolved is not None:
            remaining = remaining.replace(match.group(0), "", 1)
            context_sections.append(resolved)

    if not context_sections:
        return text

    context_block = "\n\n".join(context_sections)
    prompt = remaining.strip()
    if prompt:
        return f"Context:\n{context_block}\n\nUser request:\n{prompt}"
    return f"Context:\n{context_block}"


def _resolve_single_ref(
    ref: str,
    context_settings: ContextSettings | None,
) -> str | None:
    """Resolve a single ``type:ref`` string.  Returns None for unknown types."""
    if ref.startswith("file:"):
        path = ref[len("file:") :]
        from fin_assist.context.files import FileFinder

        finder = FileFinder(settings=context_settings)
        item = finder.get_item(path)
        if item.status == "available":
            return f"[FILE: {path}]\n{item.content}"
        return f"[FILE: {path}] Error: {item.error_reason}"

    if ref == "git:diff":
        from fin_assist.context.git import GitContext

        ctx = GitContext(settings=context_settings)
        item = ctx.get_item("git_diff:diff")
        if item.status == "available":
            return f"[GIT DIFF]\n{item.content}"
        return f"[GIT DIFF] Error: {item.error_reason}"

    if ref == "git:log":
        from fin_assist.context.git import GitContext

        ctx = GitContext(settings=context_settings)
        item = ctx.get_item("git_log:log")
        if item.status == "available":
            return f"[GIT LOG]\n{item.content}"
        return f"[GIT LOG] Error: {item.error_reason}"

    if ref.startswith("history:"):
        from fin_assist.context.history import ShellHistory

        history = ShellHistory(settings=context_settings)
        query = ref[len("history:") :]
        items = history.search(query) if query else history.get_all()
        if items:
            content = "\n".join(item.content for item in items)
            return f"[SHELL HISTORY]\n{content}"
        return "[SHELL HISTORY] No history available"

    return None


class FinPrompt:
    """Reusable prompt_toolkit session with slash-command fuzzy completion.

    Features:
    - Fuzzy completion for slash commands (defined in SLASH_COMMANDS)
    - Tab completion for agent names when configured
    - ``@``-completion for context injection (file, git, history)
    - Persistent history across sessions
    - Readline-style keybindings
    """

    def __init__(
        self,
        agents: list[str] | None = None,
        history_path: Path = HISTORY_PATH,
        context_settings: ContextSettings | None = None,
    ) -> None:
        self.agents = agents or []
        self.history_path = history_path
        self._context_settings = context_settings

    def _build_completer(self) -> Completer:
        words = [cmd.name for cmd in SLASH_COMMANDS] + self.agents
        word_completer = WordCompleter(words, ignore_case=True)
        slash_completer = SlashCompleter(FuzzyCompleter(word_completer))
        at_completer = AtCompleter(context_settings=self._context_settings)
        return _CombinedCompleter(slash_completer, at_completer)

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


class _CombinedCompleter(Completer):
    """Delegate to the first completer that yields results.

    Tries slash completer first (for ``/`` prefix), then at completer
    (for ``@`` prefix).  If neither matches, yields nothing.
    """

    def __init__(self, slash: Completer, at: Completer) -> None:
        self._slash = slash
        self._at = at

    def get_completions(self, document: Document, complete_event: CompleteEvent):  # noqa: ANN201
        text = document.text_before_cursor.lstrip()
        if text.startswith("/"):
            yield from self._slash.get_completions(document, complete_event)
        elif "@" in document.text_before_cursor:
            yield from self._at.get_completions(document, complete_event)
