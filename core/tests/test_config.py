from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from solana_core.config import ConfigStore, MemorySecretStore, Settings
from solana_core.config.store import deep_merge


def test_defaults_without_file(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "missing" / "config.toml")
    assert store.settings == Settings()
    assert store.settings.general.language == "ru"


def test_save_and_load(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    store = ConfigStore(path)
    store.update({"voice": {"wake_sensitivity": 0.7}, "mcp": {"servers": {"fs": {"command": "x"}}}})
    assert path.exists()
    loaded = ConfigStore(path).settings
    assert loaded.voice.wake_sensitivity == 0.7
    assert loaded.mcp.servers["fs"].command == "x"
    assert loaded.voice.input_device is None


def test_invalid_patch_keeps_settings(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    with pytest.raises(ValidationError):
        store.update({"voice": {"wake_sensitivity": 5}})
    with pytest.raises(ValidationError):
        store.update({"unknown": 1})
    assert store.settings == Settings()


def test_broken_file_is_backed_up(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("this is = = not toml", encoding="utf-8")
    store = ConfigStore(path)
    assert store.settings == Settings()
    assert (tmp_path / "config.toml.bak").exists()


def test_deep_merge() -> None:
    assert deep_merge({"a": {"b": 1, "c": 2}, "d": 1}, {"a": {"b": 3}}) == {
        "a": {"b": 3, "c": 2},
        "d": 1,
    }


def test_memory_secrets() -> None:
    secrets = MemorySecretStore()
    assert secrets.get("anthropic_api_key") is None
    secrets.set("anthropic_api_key", "sk")
    assert secrets.get("anthropic_api_key") == "sk"
    secrets.delete("anthropic_api_key")
    secrets.delete("anthropic_api_key")
    assert secrets.get("anthropic_api_key") is None
