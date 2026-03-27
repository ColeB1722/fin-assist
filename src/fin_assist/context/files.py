from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from fin_assist.context.base import ContextItem, ContextProvider, ContextType

if TYPE_CHECKING:
    from fin_assist.config.schema import ContextSettings


class FileFinder(ContextProvider):
    def __init__(self, settings: ContextSettings | None = None) -> None:
        self._settings = settings

    def _supported_types(self) -> set[ContextType]:
        types: set[ContextType] = {"file"}
        return types

    def _get_max_file_size(self) -> int:
        if self._settings:
            return self._settings.max_file_size
        return 100_000

    def search(self, query: str) -> list[ContextItem]:
        results = self._run_find(query)
        return [self._file_result_to_context_item(r) for r in results]

    def get_item(self, id: str) -> ContextItem:
        path = Path(id)
        if not path.exists() or not path.is_file():
            return ContextItem(
                id=id,
                type="file",
                content="",
                metadata={"path": str(path)},
                status="not_found",
                error_reason="file does not exist",
            )
        max_size = self._get_max_file_size()
        file_size = path.stat().st_size
        if file_size > max_size:
            return ContextItem(
                id=id,
                type="file",
                content="",
                metadata={
                    "path": str(path),
                    "size_exceeded": True,
                    "size": file_size,
                    "limit": max_size,
                },
                status="excluded",
                error_reason="file_size_exceeded",
            )
        try:
            content = path.read_text()
        except OSError as e:
            return ContextItem(
                id=id,
                type="file",
                content="",
                metadata={"path": str(path)},
                status="error",
                error_reason=f"os_error: {e}",
            )
        except UnicodeDecodeError as e:
            return ContextItem(
                id=id,
                type="file",
                content="",
                metadata={"path": str(path)},
                status="error",
                error_reason=f"encoding_error: {e}",
            )
        return ContextItem(
            id=id,
            type="file",
            content=content,
            metadata={"path": str(path), "size": file_size},
            status="available",
        )

    def get_all(self) -> list[ContextItem]:
        results = self._run_find("")
        return [self._file_result_to_context_item(r) for r in results]

    def _run_find(self, query: str) -> list[str]:
        max_size_bytes = self._get_max_file_size()
        cmd = ["find", ".", "-type", "f", "-size", f"-{max_size_bytes}c"]
        if query:
            cmd.append("-name")
            cmd.append(query)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=Path.cwd(),
            )
            if result.returncode != 0:
                return []
            paths = []
            for line in result.stdout.splitlines():
                if line and line != ".":
                    rel_path = line[2:] if line.startswith("./") else line
                    paths.append(rel_path)
            return paths
        except (subprocess.SubprocessError, OSError):
            return []

    def _file_result_to_context_item(self, filepath: str) -> ContextItem:
        return self.get_item(filepath)
