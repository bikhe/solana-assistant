"""API keys and tokens, kept in the OS keyring (Windows Credential Manager, macOS Keychain,
Secret Service on Linux). Never written to the TOML file or sent in ``settings``."""

from __future__ import annotations

import contextlib
from abc import ABC, abstractmethod

SERVICE = "solana-assistant"


class SecretStore(ABC):
    @abstractmethod
    def get(self, key: str) -> str | None: ...

    @abstractmethod
    def set(self, key: str, value: str) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...


class KeyringSecretStore(SecretStore):
    def __init__(self, service: str = SERVICE) -> None:
        self.service = service

    def get(self, key: str) -> str | None:
        import keyring

        value: str | None = keyring.get_password(self.service, key)
        return value

    def set(self, key: str, value: str) -> None:
        import keyring

        keyring.set_password(self.service, key, value)

    def delete(self, key: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        with contextlib.suppress(PasswordDeleteError):
            keyring.delete_password(self.service, key)


class MemorySecretStore(SecretStore):
    """For tests and ``--fake`` mode."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)
