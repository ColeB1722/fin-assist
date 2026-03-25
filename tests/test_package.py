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
        """Test that python -m fin_assist runs without error."""
        result = subprocess.run(
            [sys.executable, "-m", "fin_assist"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "fin-assist" in result.stdout.lower()
