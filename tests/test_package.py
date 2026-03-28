"""Smoke tests for package entry point."""

import subprocess
import sys


class TestPackage:
    """Tests for package-level functionality."""

    def test_import_package(self) -> None:
        """Test that importing fin_assist succeeds."""
        import fin_assist

        assert fin_assist is not None

    def test_main_callable(self) -> None:
        """Test that main entry point exists and is callable."""
        from fin_assist.__main__ import main

        assert callable(main)

    def test_module_execution(self) -> None:
        """Test that python -m fin_assist can be imported.

        Note: Full execution would launch the TUI which blocks, so we just
        verify the module is importable and main is callable.
        """
        from fin_assist.__main__ import main
        import fin_assist.__main__

        assert hasattr(fin_assist.__main__, "main")
