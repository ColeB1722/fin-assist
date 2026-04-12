"""Tests for the fin-assist serve entry point."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fin_assist.cli.main import main


class TestServeCommand:
    def test_serve_builds_hub_app_and_runs_uvicorn(self) -> None:
        with (
            patch("fin_assist.cli.main.create_hub_app") as mock_create,
            patch("fin_assist.cli.main.configure_logging"),
            patch("fin_assist.hub.pidfile.acquire"),
            patch("fin_assist.cli.main.uvicorn.Config"),
            patch(
                "fin_assist.cli.main.uvicorn.Server", return_value=MagicMock()
            ) as mock_server_cls,
            patch("socket.socket", return_value=MagicMock()),
            patch("fin_assist.cli.main.asyncio.run"),
        ):
            mock_app = MagicMock()
            mock_create.return_value = mock_app
            main(["serve"])

            mock_create.assert_called_once()
            mock_server_cls.return_value.serve.assert_called_once()

    def test_serve_binds_to_localhost(self) -> None:
        with (
            patch("fin_assist.cli.main.create_hub_app", return_value=MagicMock()),
            patch("fin_assist.cli.main.configure_logging"),
            patch("fin_assist.hub.pidfile.acquire"),
            patch("fin_assist.cli.main.uvicorn.Config") as mock_config_cls,
            patch("fin_assist.cli.main.uvicorn.Server", return_value=MagicMock()),
            patch("socket.socket", return_value=MagicMock()),
            patch("fin_assist.cli.main.asyncio.run"),
        ):
            main(["serve"])

            call_kwargs = mock_config_cls.call_args
            assert call_kwargs.kwargs.get("host") == "127.0.0.1"

    def test_serve_uses_configured_port(self) -> None:
        with (
            patch("fin_assist.cli.main.create_hub_app", return_value=MagicMock()),
            patch("fin_assist.cli.main.configure_logging"),
            patch("fin_assist.hub.pidfile.acquire"),
            patch("fin_assist.cli.main.uvicorn.Config") as mock_config_cls,
            patch("fin_assist.cli.main.uvicorn.Server", return_value=MagicMock()),
            patch("socket.socket", return_value=MagicMock()),
            patch("fin_assist.cli.main.asyncio.run"),
        ):
            main(["serve"])

            call_kwargs = mock_config_cls.call_args
            assert call_kwargs.kwargs.get("port") == 4096

    def test_no_args_prints_help(self, capsys) -> None:
        """Running with no args should print usage help and exit with error code."""
        import sys

        with patch.object(sys, "argv", ["fin-assist"]):
            try:
                main([])
            except SystemExit as e:
                assert e.code == 2
        captured = capsys.readouterr()
        assert "fin-assist" in captured.err
