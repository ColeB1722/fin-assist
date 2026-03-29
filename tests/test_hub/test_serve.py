"""Tests for the fin-assist serve entry point."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fin_assist.__main__ import main


class TestServeCommand:
    def test_serve_builds_hub_app_and_runs_uvicorn(self) -> None:
        """fin-assist serve should create a hub app and call uvicorn.run."""
        with (
            patch("fin_assist.__main__.create_hub_app") as mock_create,
            patch("fin_assist.__main__.uvicorn") as mock_uvicorn,
        ):
            mock_app = MagicMock()
            mock_create.return_value = mock_app

            main(["serve"])

            mock_create.assert_called_once()
            mock_uvicorn.run.assert_called_once()
            # Confirm the created app is passed to uvicorn
            call_args = mock_uvicorn.run.call_args
            assert call_args.args[0] is mock_app or call_args.kwargs.get("app") is mock_app

    def test_serve_binds_to_localhost(self) -> None:
        """Server should always bind to 127.0.0.1."""
        with (
            patch("fin_assist.__main__.create_hub_app", return_value=MagicMock()),
            patch("fin_assist.__main__.uvicorn") as mock_uvicorn,
        ):
            main(["serve"])

            call_kwargs = mock_uvicorn.run.call_args
            # host may be a positional-or-keyword arg — check both
            host = call_kwargs.kwargs.get("host") or (
                call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
            )
            assert host == "127.0.0.1"

    def test_serve_uses_configured_port(self) -> None:
        """Default port should be 4096."""
        with (
            patch("fin_assist.__main__.create_hub_app", return_value=MagicMock()),
            patch("fin_assist.__main__.uvicorn") as mock_uvicorn,
        ):
            main(["serve"])

            call_kwargs = mock_uvicorn.run.call_args
            port = call_kwargs.kwargs.get("port")
            assert port == 4096

    def test_no_args_prints_help(self, capsys) -> None:
        """Running with no args should print usage help without crashing."""
        import sys

        with patch.object(sys, "argv", ["fin-assist"]):
            # argparse prints help and may raise SystemExit(0) — catch it
            try:
                main([])
            except SystemExit as e:
                assert e.code in (0, None)
        # Should not raise an unhandled exception
