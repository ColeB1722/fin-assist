"""Tests for FileFinder — os.walk + pathspec + rapidfuzz implementation.

These are behavioural tests against a real temporary directory tree, not
mocks of ``subprocess.run``.  If you're here because a test failed, start
by verifying the behaviour the test names in plain English — don't
reach for mocks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fin_assist.config.schema import ContextSettings
from fin_assist.context.files import FileFinder


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Build a small repo-like tree for FileFinder to walk.

    Layout:
        tmp_path/
            .gitignore               (ignores ``secret.txt`` and ``build/``)
            README.md
            secret.txt               (gitignored — but should still appear,
                                      since we ignore gitignore for files)
            config.toml              (not gitignored)
            src/
                main.py
                util.py
            build/
                output.bin           (pruned: directory matches gitignore)
            .venv/
                site-packages/
                    junk.py          (pruned: fallback directory prune)
            __pycache__/
                cache.pyc            (pruned: fallback directory prune)
    """
    (tmp_path / ".gitignore").write_text("secret.txt\nbuild/\n")
    (tmp_path / "README.md").write_text("hello")
    (tmp_path / "secret.txt").write_text("shh")
    (tmp_path / "config.toml").write_text("[a]\nb = 1\n")

    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('main')")
    (src / "util.py").write_text("def f(): pass")

    build = tmp_path / "build"
    build.mkdir()
    (build / "output.bin").write_text("binary")

    venv = tmp_path / ".venv" / "site-packages"
    venv.mkdir(parents=True)
    (venv / "junk.py").write_text("junk")

    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "cache.pyc").write_text("bytecode")

    return tmp_path


class TestSupportedTypes:
    def test_supports_file(self) -> None:
        finder = FileFinder()
        assert finder.supports_context("file") is True

    def test_does_not_support_history(self) -> None:
        finder = FileFinder()
        assert finder.supports_context("history") is False


class TestScan:
    def test_walks_tree_and_returns_relative_paths(self, tree: Path) -> None:
        finder = FileFinder(root=tree)
        paths = finder.search_paths("")
        assert "README.md" in paths
        assert "config.toml" in paths
        assert "src/main.py" in paths
        assert "src/util.py" in paths

    def test_prunes_gitignored_directories(self, tree: Path) -> None:
        finder = FileFinder(root=tree)
        paths = finder.search_paths("")
        assert not any(p.startswith("build/") for p in paths)

    def test_prunes_fallback_dirs_without_gitignore(self, tmp_path: Path) -> None:
        """With no .gitignore, directory floor still prunes .venv + __pycache__."""
        (tmp_path / "real.py").write_text("x")
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "junk.py").write_text("x")
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "a.pyc").write_text("x")

        finder = FileFinder(root=tmp_path)
        paths = finder.search_paths("")
        assert "real.py" in paths
        assert not any(".venv" in p for p in paths)
        assert not any("__pycache__" in p for p in paths)

    def test_includes_gitignored_files(self, tree: Path) -> None:
        """Individual files in .gitignore are still listed (design choice)."""
        finder = FileFinder(root=tree)
        paths = finder.search_paths("")
        assert "secret.txt" in paths

    def test_excludes_files_over_max_size(self, tmp_path: Path) -> None:
        (tmp_path / "small.txt").write_text("x")
        (tmp_path / "big.txt").write_text("x" * 500)
        settings = ContextSettings(max_file_size=100)

        finder = FileFinder(settings=settings, root=tmp_path)
        paths = finder.search_paths("")
        assert "small.txt" in paths
        assert "big.txt" not in paths


class TestFuzzySearch:
    def test_empty_query_returns_all(self, tree: Path) -> None:
        finder = FileFinder(root=tree)
        all_paths = finder.search_paths("")
        assert len(all_paths) > 0

    def test_exact_match_ranks_first(self, tree: Path) -> None:
        finder = FileFinder(root=tree)
        paths = finder.search_paths("config.toml")
        assert paths[0] == "config.toml"

    def test_substring_match(self, tree: Path) -> None:
        finder = FileFinder(root=tree)
        paths = finder.search_paths("main")
        assert "src/main.py" in paths

    def test_fuzzy_match_tolerates_gaps(self, tree: Path) -> None:
        """rapidfuzz should match ``cfg`` against ``config.toml``-ish names."""
        finder = FileFinder(root=tree)
        paths = finder.search_paths("cfg")
        assert "config.toml" in paths

    def test_no_false_positives_for_unrelated_query(self, tree: Path) -> None:
        finder = FileFinder(root=tree)
        paths = finder.search_paths("zzznopesuchthing")
        assert paths == []


class TestCache:
    def test_second_call_reuses_cache(self, tree: Path) -> None:
        finder = FileFinder(root=tree)
        finder.search_paths("")
        # Add a new file — without invalidate it should not appear.
        (tree / "new.txt").write_text("new")
        paths = finder.search_paths("")
        assert "new.txt" not in paths

    def test_invalidate_rescans(self, tree: Path) -> None:
        finder = FileFinder(root=tree)
        finder.search_paths("")
        (tree / "new.txt").write_text("new")
        finder.invalidate()
        paths = finder.search_paths("")
        assert "new.txt" in paths


class TestGetItem:
    def test_nonexistent_file(self, tmp_path: Path) -> None:
        finder = FileFinder(root=tmp_path)
        result = finder.get_item(str(tmp_path / "nope.py"))
        assert result.status == "not_found"
        assert result.error_reason == "file does not exist"

    def test_reads_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "hello.py"
        path.write_text("print('hi')")
        finder = FileFinder(root=tmp_path)
        result = finder.get_item(str(path))
        assert result.status == "available"
        assert result.type == "file"
        assert result.content == "print('hi')"

    def test_excludes_files_over_size_limit(self, tmp_path: Path) -> None:
        path = tmp_path / "big.py"
        path.write_text("x" * 1000)
        settings = ContextSettings(max_file_size=50)
        finder = FileFinder(settings=settings, root=tmp_path)

        result = finder.get_item(str(path))
        assert result.status == "excluded"
        assert result.error_reason == "file_size_exceeded"
        assert result.metadata["size"] == 1000
        assert result.metadata["limit"] == 50
        assert result.content == ""


class TestSearchAndGetAll:
    def test_search_returns_context_items(self, tree: Path) -> None:
        finder = FileFinder(root=tree)
        items = finder.search("main")
        assert len(items) > 0
        assert all(item.type == "file" for item in items)

    def test_get_all_returns_every_file(self, tree: Path) -> None:
        finder = FileFinder(root=tree)
        items = finder.get_all()
        ids = {item.id for item in items}
        assert "README.md" in ids
        assert "config.toml" in ids
