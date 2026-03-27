from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from fin_assist.context.base import ContextItem, ContextProvider, ContextType

if TYPE_CHECKING:
    from fin_assist.config.schema import ContextSettings


class GitContext(ContextProvider):
    def __init__(self, settings: ContextSettings | None = None) -> None:
        self._settings = settings
        self._git_available: bool | None = None

    def _supported_types(self) -> set[ContextType]:
        types: set[ContextType] = {"git_diff", "git_log", "git_status"}
        return types

    def _is_git_available(self) -> bool:
        if self._git_available is None:
            try:
                subprocess.run(
                    ["git", "--version"],
                    capture_output=True,
                    timeout=5,
                )
                self._git_available = True
            except (subprocess.SubprocessError, OSError):
                self._git_available = False
        return self._git_available

    def search(self, query: str) -> list[ContextItem]:
        return []

    def get_item(self, id: str) -> ContextItem:
        parts = id.split(":", 1)
        if len(parts) != 2:
            return ContextItem(
                id=id,
                type="git_status",
                status="not_found",
                error_reason="invalid_id_format",
            )
        context_type, _ = parts
        match context_type:
            case "git_diff":
                return self._get_diff()
            case "git_status":
                return self._get_status()
            case "git_log":
                return self._get_log()
            case _:
                return ContextItem(
                    id=id,
                    type="git_status",
                    status="not_found",
                    error_reason=f"unknown_git_context_type: {context_type}",
                )

    def get_all(self) -> list[ContextItem]:
        if not self._is_git_available():
            return []
        return [
            self._get_diff(),
            self._get_status(),
            self._get_log(),
        ]

    def _get_diff(self) -> ContextItem:
        if not self._is_git_available():
            return ContextItem(
                id="git_diff",
                type="git_diff",
                status="error",
                error_reason="git_not_available",
            )
        try:
            unstaged_result = subprocess.run(
                ["git", "diff", "--no-ext-diff"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            staged_result = subprocess.run(
                ["git", "diff", "--no-ext-diff", "--cached"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            content = ""
            if unstaged_result.stdout:
                content += f"# Unstaged changes:\n{unstaged_result.stdout}"
            if staged_result.stdout:
                content += f"\n# Staged changes:\n{staged_result.stdout}"
            if not content:
                content = "No uncommitted changes"
            return ContextItem(
                id="git_diff",
                type="git_diff",
                content=content,
                metadata={},
                status="available",
            )
        except (subprocess.SubprocessError, OSError) as e:
            return ContextItem(
                id="git_diff",
                type="git_diff",
                status="error",
                error_reason=f"git_command_failed: {e}",
            )

    def _get_status(self) -> ContextItem:
        if not self._is_git_available():
            return ContextItem(
                id="git_status",
                type="git_status",
                status="error",
                error_reason="git_not_available",
            )
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            content = result.stdout if result.stdout else "Clean working tree"
            return ContextItem(
                id="git_status",
                type="git_status",
                content=content,
                metadata={},
                status="available",
            )
        except (subprocess.SubprocessError, OSError) as e:
            return ContextItem(
                id="git_status",
                type="git_status",
                status="error",
                error_reason=f"git_command_failed: {e}",
            )

    def _get_log(self) -> ContextItem:
        if not self._is_git_available():
            return ContextItem(
                id="git_log",
                type="git_log",
                status="error",
                error_reason="git_not_available",
            )
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-10"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            content = result.stdout if result.stdout else "No commit history"
            return ContextItem(
                id="git_log",
                type="git_log",
                content=content,
                metadata={},
                status="available",
            )
        except (subprocess.SubprocessError, OSError) as e:
            return ContextItem(
                id="git_log",
                type="git_log",
                status="error",
                error_reason=f"git_command_failed: {e}",
            )
