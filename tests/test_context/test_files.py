from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fin_assist.context.files import FileFinder


class TestFileFinder:
    def test_supported_types(self) -> None:
        finder = FileFinder()
        assert finder._supported_types() == {"file"}

    def test_supports_file_context(self) -> None:
        finder = FileFinder()
        assert finder.supports_context("file") is True
        assert finder.supports_context("history") is False

    def test_search_with_find(self) -> None:
        finder = FileFinder()
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "./path/to/file1.py\n./path/to/file2.py"
            mock_run.return_value = mock_result

            with patch.object(finder, "get_item") as mock_get_item:
                mock_item = MagicMock()
                mock_get_item.return_value = mock_item

                result = finder.search("*.py")
                assert len(result) == 2
                mock_run.assert_called_once()

    def test_get_item_nonexistent_file(self) -> None:
        finder = FileFinder()
        result = finder.get_item("/nonexistent/file.py")
        assert result is not None
        assert result.status == "not_found"
        assert result.error_reason == "file does not exist"

    def test_get_item_readable_file(self) -> None:
        finder = FileFinder()
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.is_file", return_value=True):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 100
                    with patch("pathlib.Path.read_text", return_value="print('hello')"):
                        result = finder.get_item("/test/file.py")
                        assert result is not None
                        assert result.type == "file"
                        assert result.content == "print('hello')"

    def test_get_item_too_large(self) -> None:
        from fin_assist.config.schema import ContextSettings

        settings = ContextSettings(max_file_size=50)
        finder = FileFinder(settings=settings)

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.is_file", return_value=True):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 1000
                    result = finder.get_item("/test/large_file.py")
                    assert result is not None
                    assert result.type == "file"
                    assert result.status == "excluded"
                    assert result.metadata["size_exceeded"] is True
                    assert result.metadata["size"] == 1000
                    assert result.metadata["limit"] == 50
                    assert result.content == ""

    def test_get_all(self) -> None:
        finder = FileFinder()
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "./file1.py\n./file2.py"
            mock_run.return_value = mock_result

            with patch.object(finder, "get_item") as mock_get_item:
                mock_item = MagicMock()
                mock_get_item.return_value = mock_item

                result = finder.get_all()
                assert len(result) == 2
