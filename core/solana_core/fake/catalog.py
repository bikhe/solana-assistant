"""Sample skills and models shown in --fake mode. MCP has its own demo in ``mcp/fake.py``."""

from __future__ import annotations

from dataclasses import dataclass, field

from solana_core.protocol.generated import (
    ModelInfo,
    SkillInfo,
)


def _skills() -> dict[str, SkillInfo]:
    items = [
        SkillInfo(
            id="timers",
            name="Таймеры",
            description="Таймеры и напоминания",
            languages=["ru", "en"],
            builtin=True,
            enabled=True,
        ),
        SkillInfo(
            id="weather",
            name="Погода",
            description="Прогноз погоды",
            languages=["ru", "en"],
            builtin=True,
            enabled=True,
        ),
    ]
    return {s.id: s for s in items}


def _models() -> dict[str, ModelInfo]:
    items = [
        ModelInfo(
            id="wake-ey-solana",
            kind="wake",
            name="«Эй, Солана»",
            size_bytes=1_200_000,
            installed=True,
        ),
        ModelInfo(
            id="silero-vad", kind="vad", name="Silero VAD", size_bytes=2_300_000, installed=True
        ),
        ModelInfo(
            id="whisper-small",
            kind="stt",
            name="Whisper small",
            size_bytes=488_000_000,
            installed=False,
        ),
        ModelInfo(
            id="silero-tts-ru",
            kind="tts",
            name="Silero TTS (ru)",
            size_bytes=60_000_000,
            installed=False,
        ),
    ]
    return {m.id: m for m in items}


@dataclass
class FakeCatalog:
    skills: dict[str, SkillInfo] = field(default_factory=_skills)
    models: dict[str, ModelInfo] = field(default_factory=_models)
