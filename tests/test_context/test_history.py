from __future__ import annotations

from unittest.mock import MagicMock, patch

from fin_assist.context.history import ShellHistory


class TestShellHistory:
    def test_supported_types(self) -> None:
        history = ShellHistory()
        assert history._supported_types() == {"history"}

    def test_supports_history_context(self) -> None:
        history = ShellHistory()
        assert history.supports_context("history") is True
        assert history.supports_context("file") is False

    def test_is_fish_available_cached(self) -> None:
        history = ShellHistory()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            assert history._is_fish_available() is True
            assert history._is_fish_available() is True
            mock_run.assert_called_once()

    def test_is_fish_available_when_not_installed(self) -> None:
        history = ShellHistory()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            assert history._is_fish_available() is False

    def test_search_returns_empty_when_fish_not_available(self) -> None:
        history = ShellHistory()
        with patch.object(history, "_is_fish_available", return_value=False):
            result = history.search("test")
            assert result == []

    def test_search_with_query_filters_results(self) -> None:
        history = ShellHistory()
        with patch.object(history, "_is_fish_available", return_value=True):
            with patch.object(history, "_get_history") as mock_get:
                mock_item1 = MagicMock()
                mock_item1.content = "git status"
                mock_item2 = MagicMock()
                mock_item2.content = "ls -la"
                mock_get.return_value = [mock_item1, mock_item2]

                result = history.search("git")
                assert len(result) == 1
                assert result[0].content == "git status"

    def test_search_without_query_returns_all(self) -> None:
        history = ShellHistory()
        with patch.object(history, "_is_fish_available", return_value=True):
            with patch.object(history, "_get_history") as mock_get:
                mock_item1 = MagicMock()
                mock_item1.content = "git status"
                mock_item2 = MagicMock()
                mock_item2.content = "ls -la"
                mock_get.return_value = [mock_item1, mock_item2]

                result = history.search("")
                assert len(result) == 2

    def test_get_item_invalid_id(self) -> None:
        history = ShellHistory()
        with patch.object(history, "_is_fish_available", return_value=True):
            result = history.get_item("not_a_number")
            assert result is not None
            assert result.status == "not_found"
            assert result.error_reason == "invalid_id_format"

    def test_get_item_valid_index(self) -> None:
        history = ShellHistory()
        with patch.object(history, "_is_fish_available", return_value=True):
            with patch.object(history, "_get_history") as mock_get:
                mock_item = MagicMock()
                mock_get.return_value = [mock_item]
                result = history.get_item("0")
                assert result == mock_item

    def test_get_item_out_of_range(self) -> None:
        history = ShellHistory()
        with patch.object(history, "_is_fish_available", return_value=True):
            with patch.object(history, "_get_history") as mock_get:
                mock_get.return_value = [MagicMock(), MagicMock()]
                result = history.get_item("100")
                assert result is not None
                assert result.status == "not_found"
                assert result.error_reason == "index_out_of_range"

    def test_get_all_returns_history_items(self) -> None:
        history = ShellHistory()
        with patch.object(history, "_is_fish_available", return_value=True):
            with patch.object(history, "_get_history") as mock_get:
                mock_item = MagicMock()
                mock_get.return_value = [mock_item]
                result = history.get_all()
                assert result == [mock_item]

    def test_get_all_empty_when_fish_not_available(self) -> None:
        history = ShellHistory()
        with patch.object(history, "_is_fish_available", return_value=False):
            result = history.get_all()
            assert result == []

    def test_get_history_respects_max_items(self) -> None:
        from fin_assist.config.schema import ContextSettings

        settings = ContextSettings(max_history_items=5)
        history = ShellHistory(settings=settings)

        with patch.object(history, "_is_fish_available", return_value=True):
            with patch("subprocess.run") as mock_run:
                lines = "\n".join([f"cmd{i}" for i in range(20)])
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = lines
                mock_run.return_value = mock_result

                result = history._get_history()
                assert len(result) == 5
