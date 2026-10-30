"""Sample MCP servers, skills and models shown in --fake mode."""

from __future__ import annotations

from dataclasses import dataclass, field

from solana_core.protocol.generated import (
    McpServerConfig,
    McpServerInfo,
    ModelInfo,
    SkillInfo,
    ToolInfo,
)


def _mcp_servers() -> dict[str, McpServerInfo]:
    fs = McpServerInfo(
        name="filesystem",
        config=McpServerConfig(
            command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "~"]
        ),
        enabled=True,
        status="connected",
        tools=[
            ToolInfo(
                name="filesystem.read_file",
                description="Прочитать файл",
                risk="confirm",
                source="mcp",
                enabled=True,
            )
        ],
    )
    ha = McpServerInfo(
        name="home-assistant",
        config=McpServerConfig(url="http://homeassistant.local:8123/mcp_server/sse"),
        enabled=False,
        status="disconnected",
        tools=[],
    )
    return {fs.name: fs, ha.name: ha}


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
    mcp: dict[str, McpServerInfo] = field(default_factory=_mcp_servers)
    skills: dict[str, SkillInfo] = field(default_factory=_skills)
    models: dict[str, ModelInfo] = field(default_factory=_models)
