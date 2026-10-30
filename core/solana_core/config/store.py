"""Read and write settings as TOML."""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from platformdirs import user_config_path

from solana_core.config.models import Settings

log = logging.getLogger(__name__)

APP_NAME = "solana"


def default_config_path() -> Path:
    """``SOLANA_CONFIG`` if set, otherwise ``<user config dir>/solana/config.toml``."""
    if env := os.environ.get("SOLANA_CONFIG"):
        return Path(env)
    return user_config_path(APP_NAME, appauthor=False) / "config.toml"


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Return ``base`` with ``patch`` merged in. Nested dicts merge, everything else replaces."""
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()
        self.settings = self.load()

    def load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            data = tomllib.loads(self.path.read_text(encoding="utf-8"))
            return Settings.model_validate(data)
        except (tomllib.TOMLDecodeError, ValueError) as exc:
            backup = self.path.with_suffix(".toml.bak")
            log.warning("config %s is invalid (%s); moved to %s", self.path, exc, backup)
            self.path.replace(backup)
            return Settings()

    def save(self, settings: Settings | None = None) -> None:
        if settings is not None:
            self.settings = settings
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = self.settings.model_dump(mode="json", exclude_none=True)
        tmp = self.path.with_suffix(".toml.tmp")
        tmp.write_text(tomli_w.dumps(data), encoding="utf-8")
        tmp.replace(self.path)

    def update(self, patch: dict[str, Any]) -> Settings:
        """Deep-merge ``patch``, validate, save and return the new settings.

        Raises ``pydantic.ValidationError`` and keeps the old settings if the patch is invalid.
        """
        merged = deep_merge(self.settings.model_dump(mode="json"), patch)
        settings = Settings.model_validate(merged)
        self.save(settings)
        return settings
