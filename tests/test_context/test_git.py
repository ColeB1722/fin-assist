from __future__ import annotations

from unittest.mock import MagicMock, patch

from fin_assist.context.git import GitContext


class TestGitContext:
    def test_supported_types(self) -> None:
        ctx = GitContext()
        assert ctx._supported_types() == {"git_diff", "git_log", "git_status"}

    def test_supports_git_context(self) -> None:
        ctx = GitContext()
        assert ctx.supports_context("git_diff") is True
        assert ctx.supports_context("git_log") is True
        assert ctx.supports_context("git_status") is True
        assert ctx.supports_context("file") is False

    def test_is_git_available_cached(self) -> None:
        ctx = GitContext()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            assert ctx._is_git_available() is True
            assert ctx._is_git_available() is True
            mock_run.assert_called_once()

    def test_is_git_available_when_not_installed(self) -> None:
        ctx = GitContext()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            assert ctx._is_git_available() is False

    def test_search_returns_empty(self) -> None:
        ctx = GitContext()
        result = ctx.search("test")
        assert result == []

    def test_get_item_invalid_id(self) -> None:
        ctx = GitContext()
        result = ctx.get_item("invalid")
        assert result is not None
        assert result.status == "not_found"
        assert result.error_reason == "invalid_id_format"

    def test_get_item_git_diff(self) -> None:
        ctx = GitContext()
        with patch.object(ctx, "_is_git_available", return_value=True):
            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.stdout = "+ added line\n- removed line"
                mock_run.return_value = mock_result

                result = ctx.get_item("git_diff:dummy")
                assert result is not None
                assert result.type == "git_diff"
                assert "added line" in result.content

    def test_get_item_git_status(self) -> None:
        ctx = GitContext()
        with patch.object(ctx, "_is_git_available", return_value=True):
            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.stdout = "M modified.py\nA new.py"
                mock_run.return_value = mock_result

                result = ctx.get_item("git_status:dummy")
                assert result is not None
                assert result.type == "git_status"

    def test_get_item_git_log(self) -> None:
        ctx = GitContext()
        with patch.object(ctx, "_is_git_available", return_value=True):
            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.stdout = "abc123 Fix bug\ndef456 Add feature"
                mock_run.return_value = mock_result

                result = ctx.get_item("git_log:dummy")
                assert result is not None
                assert result.type == "git_log"

    def test_get_all_when_git_not_available(self) -> None:
        ctx = GitContext()
        with patch.object(ctx, "_is_git_available", return_value=False):
            result = ctx.get_all()
            assert result == []

    def test_get_all_returns_all_git_contexts(self) -> None:
        ctx = GitContext()
        with patch.object(ctx, "_is_git_available", return_value=True):
            with patch.object(ctx, "_get_diff") as mock_diff:
                with patch.object(ctx, "_get_status") as mock_status:
                    with patch.object(ctx, "_get_log") as mock_log:
                        mock_diff.return_value = MagicMock()
                        mock_status.return_value = MagicMock()
                        mock_log.return_value = MagicMock()

                        result = ctx.get_all()
                        assert len(result) == 3
