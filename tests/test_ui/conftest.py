from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from fin_assist.credentials.store import CredentialStore


@pytest.fixture
def mock_credentials_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    creds_file = tmp_path / "credentials.json"
    monkeypatch.setattr("fin_assist.credentials.store.CREDENTIALS_FILE", creds_file)
    return creds_file


@pytest.fixture
def credential_store(mock_credentials_file: Path) -> Generator[CredentialStore, None, None]:
    with patch.dict("os.environ", {}, clear=True):
        yield CredentialStore()
