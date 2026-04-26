"""Tests for fin_assist.paths — FIN_DATA_DIR env var support."""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fin_assist import paths as paths_module


@pytest.fixture()
def _reload_paths(monkeypatch):
    """Set FIN_DATA_DIR and reload paths module so DATA_DIR picks up the new value."""

    def _set_and_reload(value: str):
        monkeypatch.setenv("FIN_DATA_DIR", value)
        importlib.reload(paths_module)

    yield _set_and_reload

    monkeypatch.delenv("FIN_DATA_DIR", raising=False)
    importlib.reload(paths_module)


class TestPathsFinDataDir:
    def test_paths_honors_fin_data_dir(self, _reload_paths, tmp_path):
        _reload_paths(str(tmp_path / "fin-data"))
        assert paths_module.DATA_DIR == tmp_path / "fin-data"

    def test_paths_default_still_home_local_share(self):
        importlib.reload(paths_module)
        assert paths_module.DATA_DIR == Path("~/.local/share/fin").expanduser()

    def test_derived_paths_follow_data_dir(self, _reload_paths, tmp_path):
        custom = tmp_path / "custom-fin"
        _reload_paths(str(custom))
        assert paths_module.SESSIONS_DIR == custom / "sessions"
        assert paths_module.HISTORY_PATH == custom / "history"
        assert paths_module.PID_FILE == custom / "hub.pid"
        assert paths_module.CREDENTIALS_FILE == custom / "credentials.json"

    def test_relative_path_works(self, _reload_paths):
        _reload_paths("./.fin")
        assert paths_module.DATA_DIR == Path("./.fin")

    def test_server_settings_follows_data_dir_end_to_end(self, tmp_path):
        """FIN_DATA_DIR propagates to ServerSettings defaults in a fresh process."""
        custom = tmp_path / "e2e-fin"
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from fin_assist.config.schema import ServerSettings; "
                    "from fin_assist.paths import DATA_DIR; "
                    f"s = ServerSettings(); "
                    f"assert s.db_path == str(DATA_DIR / 'hub.db'), "
                    f"f'{{s.db_path}} != {{str(DATA_DIR / \"hub.db\")}}'; "
                    "print('OK')"
                ),
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "FIN_DATA_DIR": str(custom),
            },
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout
