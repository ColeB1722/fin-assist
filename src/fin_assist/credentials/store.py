from __future__ import annotations

import json
import os
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import keyring

CREDENTIALS_FILE = Path("~/.local/share/fin/credentials.json").expanduser()


class CredentialStore:
    def __init__(self, credentials_file: Path | None = None) -> None:
        self._credentials_file = credentials_file or CREDENTIALS_FILE
        self._credentials_file.parent.mkdir(parents=True, exist_ok=True)

    def get_api_key(self, provider: str) -> str | None:
        env_var = f"{provider.upper()}_API_KEY"
        if env_value := os.environ.get(env_var):
            return env_value

        if file_value := self._get_from_file(provider):
            return file_value

        if keyring_value := get_keyring_key(provider):
            return keyring_value

        return None

    def set_api_key(self, provider: str, api_key: str) -> None:
        data = self._read_file()
        if provider not in data:
            data[provider] = {}
        data[provider]["api_key"] = api_key
        data[provider]["created_at"] = self._get_timestamp()
        self._write_file(data)

    def _get_from_file(self, provider: str) -> str | None:
        data = self._read_file()
        return data.get(provider, {}).get("api_key")

    def _read_file(self) -> dict[str, dict]:
        if not self._credentials_file.exists():
            return {}
        try:
            return json.loads(self._credentials_file.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_file(self, data: dict[str, dict]) -> None:
        self._credentials_file.parent.mkdir(parents=True, exist_ok=True)
        self._credentials_file.write_text(json.dumps(data, indent=2))

    @staticmethod
    def _get_timestamp() -> str:
        return datetime.now(UTC).isoformat()


def get_keyring_key(provider: str) -> str | None:
    with suppress(Exception):
        return keyring.get_password("fin-assist", provider)
    return None


def set_keyring_key(provider: str, api_key: str) -> None:
    with suppress(Exception):
        keyring.set_password("fin-assist", provider, api_key)


def keyring_available() -> bool:
    with suppress(Exception):
        keyring.get_password("fin-assist", "__test__")
        return True
    return False
