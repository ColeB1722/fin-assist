from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fin_assist.credentials.store import CredentialStore


@pytest.fixture
def mock_credentials_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    creds_file = tmp_path / "credentials.json"
    monkeypatch.setattr("fin_assist.credentials.store.CREDENTIALS_FILE", creds_file)
    return creds_file


@pytest.fixture
def credential_store(mock_credentials_file: Path) -> CredentialStore:
    with patch.dict("os.environ", {}, clear=True):
        return CredentialStore()
