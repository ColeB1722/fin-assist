from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

from fin_assist.context.base import ContextItem, ContextProvider, ContextType

if TYPE_CHECKING:
    from fin_assist.config.schema import ContextSettings

SENSITIVE_PATTERNS = [
    re.compile(r"export\s+\w*(?:API|TOKEN|KEY|SECRET|PASSWORD|PASS)\w*=", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|token|secret|password)\b.*=", re.IGNORECASE),
    re.compile(r"-H\s+['\"]Authorization:\s*Bearer", re.IGNORECASE),
    re.compile(r"aws_access_key_id|aws_secret_access_key", re.IGNORECASE),
]


def _is_command_sensitive(command: str) -> bool:
    return any(pattern.search(command) for pattern in SENSITIVE_PATTERNS)


class ShellHistory(ContextProvider):
    def __init__(self, settings: ContextSettings | None = None) -> None:
        self._settings = settings
        self._fish_available: bool | None = None
        self._cache: list[ContextItem] | None = None

    def _supported_types(self) -> set[ContextType]:
        types: set[ContextType] = {"history"}
        return types

    def _is_fish_available(self) -> bool:
        if self._fish_available is None:
            try:
                subprocess.run(
                    ["fish", "--version"],
                    capture_output=True,
                    timeout=5,
                )
                self._fish_available = True
            except (subprocess.SubprocessError, OSError):
                self._fish_available = False
        return self._fish_available

    def _get_max_history_items(self) -> int:
        if self._settings:
            return self._settings.max_history_items
        return 50

    def search(self, query: str) -> list[ContextItem]:
        if not self._is_fish_available():
            return []
        history = self._get_history()
        if not query:
            return history
        filtered = [item for item in history if query.lower() in item.content.lower()]
        return filtered

    def get_item(self, id: str) -> ContextItem:
        try:
            idx = int(id)
        except ValueError:
            return ContextItem(
                id=id,
                type="history",
                status="not_found",
                error_reason="invalid_id_format",
            )
        history = self._get_history()
        if 0 <= idx < len(history):
            return history[idx]
        return ContextItem(
            id=id,
            type="history",
            status="not_found",
            error_reason="index_out_of_range",
        )

    def get_all(self) -> list[ContextItem]:
        return self._get_history()

    def _get_history(self) -> list[ContextItem]:
        if self._cache is not None:
            return self._cache
        if not self._is_fish_available():
            return []
        try:
            result = subprocess.run(
                ["fish", "-c", "history"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []
            lines = result.stdout.splitlines()
            max_items = self._get_max_history_items()
            items = []
            for idx, line in enumerate(lines[:max_items]):
                line = line.strip()
                if line and not line.startswith("#") and not _is_command_sensitive(line):
                    items.append(
                        ContextItem(
                            id=str(idx),
                            type="history",
                            content=line,
                            metadata={"index": idx},
                            status="available",
                        )
                    )
            self._cache = items
            return self._cache
        except (subprocess.SubprocessError, OSError):
            return []
