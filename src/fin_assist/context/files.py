"""File discovery + fuzzy path matching for ``@file:`` completion.

Replaces an earlier ``find(1)`` subprocess approach which blocked the
prompt_toolkit event loop on every keystroke and scanned the full tree
including ``.venv``, ``.git``, etc.

Design:

- Walk the tree once with ``os.walk``, honouring ``.gitignore`` via
  ``pathspec`` and a minimal hardcoded floor (``.git``, ``__pycache__``,
  ``.venv``, ``node_modules``, ``.direnv``, ``.devenv``, ``.fin``).
- Cache the resulting path list on the ``FileFinder`` instance.
- Fuzzy-match queries with ``rapidfuzz.process.extract`` (``WRatio``
  scorer) for path-aware ranking.

Callers should instantiate a single ``FileFinder`` per REPL turn (or
longer) and call ``invalidate()`` to force a re-scan.
"""

from __future__ import annotations

import os
from pathlib import Path

import pathspec
from rapidfuzz import fuzz, process

from fin_assist.config.schema import ContextSettings
from fin_assist.context.base import ContextItem, ContextProvider, ContextType

# Directories always pruned even when no .gitignore is present.  Kept small
# on purpose: .gitignore is the source of truth; this is the floor for
# directories (caches, VCS metadata, virtualenvs) that almost always want
# to be hidden regardless.
_FALLBACK_PRUNE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".direnv",
        ".devenv",
        ".fin",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)

# Cap on completion results returned per query.  Enough to be useful,
# small enough that prompt_toolkit renders instantly.
_MAX_COMPLETION_RESULTS = 50

# rapidfuzz score floor for a match to be returned (0-100).  Empirically
# 40 keeps out noise while allowing loose matches like ``cfg`` → ``config.toml``.
_MIN_MATCH_SCORE = 40


class FileFinder(ContextProvider):
    """Provider for ``@file:`` references.

    Scans the working directory once, caches the result, and serves
    fuzzy-matched path queries from the in-memory list.
    """

    def __init__(
        self,
        settings: ContextSettings | None = None,
        root: Path | None = None,
    ) -> None:
        self._settings = settings or ContextSettings()
        self._root = root or Path.cwd()
        self._paths_cache: list[str] | None = None

    # ------------------------------------------------------------------ API

    def _supported_types(self) -> set[ContextType]:
        return {"file"}

    def invalidate(self) -> None:
        """Drop the cached file list so the next search rescans the tree."""
        self._paths_cache = None

    def search(self, query: str) -> list[ContextItem]:
        paths = self.search_paths(query)
        return [self.get_item(p) for p in paths]

    def search_paths(self, query: str) -> list[str]:
        """Return matching file paths without reading contents.

        Used by completion menus.  With an empty query returns all paths
        (capped at ``_MAX_COMPLETION_RESULTS``).  Otherwise fuzzy-matches
        with rapidfuzz and returns results ranked by score.
        """
        paths = self._get_paths()
        if not query:
            return paths[:_MAX_COMPLETION_RESULTS]

        matches = process.extract(
            query,
            paths,
            scorer=fuzz.WRatio,
            limit=_MAX_COMPLETION_RESULTS,
            score_cutoff=_MIN_MATCH_SCORE,
        )
        return [match[0] for match in matches]

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
        max_size = self._settings.max_file_size
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
        return [self.get_item(p) for p in self._get_paths()]

    # --------------------------------------------------------------- internal

    def _get_paths(self) -> list[str]:
        if self._paths_cache is None:
            self._paths_cache = self._scan_paths()
        return self._paths_cache

    def _scan_paths(self) -> list[str]:
        """Walk the tree, pruning directories via ``.gitignore`` + fallback set.

        ``.gitignore`` is applied to *directories only* — individual
        gitignored files (``config.toml``, ``hub.log``, ``.env``) are
        intentionally included so users can ``@file:`` them in prompts.
        Directory-level pruning is where the perf win lives; file-level
        gitignore adds noise without meaningful speedup.

        Returns relative POSIX paths sorted for stability.  Silently
        drops entries we can't stat — completion is best-effort UX.
        """
        root = self._root
        spec = self._load_gitignore_spec(root)
        max_size = self._settings.max_file_size
        results: list[str] = []

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            rel_dir = Path(dirpath).relative_to(root)

            # Prune in-place so os.walk skips these subtrees entirely.
            dirnames[:] = [
                d
                for d in dirnames
                if d not in _FALLBACK_PRUNE_DIRS
                and not _matches_spec(spec, rel_dir / d, is_dir=True)
            ]

            for fname in filenames:
                rel_path = rel_dir / fname
                try:
                    if (Path(dirpath) / fname).stat().st_size > max_size:
                        continue
                except OSError:
                    continue
                results.append(rel_path.as_posix())

        results.sort()
        return results

    @staticmethod
    def _load_gitignore_spec(root: Path) -> pathspec.PathSpec | None:
        """Load ``<root>/.gitignore`` as a ``PathSpec`` if present."""
        gitignore = root / ".gitignore"
        if not gitignore.is_file():
            return None
        try:
            with gitignore.open() as f:
                return pathspec.PathSpec.from_lines("gitignore", f)
        except OSError:
            return None


def _matches_spec(spec: pathspec.PathSpec | None, path: Path, *, is_dir: bool) -> bool:
    """Return True if *path* is ignored by *spec*.

    Appends ``/`` to the path string for directories — pathspec treats
    trailing-slash patterns as directory-only matches.
    """
    if spec is None:
        return False
    path_str = path.as_posix()
    if is_dir:
        path_str += "/"
    return spec.match_file(path_str)
