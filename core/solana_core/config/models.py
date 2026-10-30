"""Settings model. This is the shape of ``settings`` in the IPC protocol.

Add fields with defaults only, so old config files keep loading.
API keys never live here: see ``secrets.py``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from solana_core.protocol import Language

BrainMode = Literal["cloud", "local", "hybrid"]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class GeneralSettings(_Section):
    language: Language = "ru"
    autostart: bool = False
    first_run_done: bool = False


class VoiceSettings(_Section):
    wake_word_enabled: bool = True
    wake_sensitivity: float = Field(0.5, ge=0.0, le=1.0)
    input_device: str | None = None
    output_device: str | None = None
    stt_provider: str = "faster-whisper"
    tts_provider: str = "silero"
    tts_voice: str | None = None
    end_of_speech_ms: int = Field(1000, ge=200, le=5000)
    push_to_talk_hotkey: str = "CommandOrControl+Shift+Space"


class BrainSettings(_Section):
    mode: BrainMode = "local"
    cloud_provider: str = "anthropic"
    cloud_model: str = "claude-sonnet-5-5"
    cloud_base_url: str | None = None
    local_provider: str = "ollama"
    local_model: str = "qwen3:8b"
    local_base_url: str = "http://127.0.0.1:11434/v1"


class ToolsSettings(_Section):
    always_allow: list[str] = Field(default_factory=list)
    disabled: list[str] = Field(default_factory=list)


class McpServerEntry(_Section):
    """One MCP server, same fields as Claude Desktop ``mcpServers`` plus ``enabled``."""

    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class McpSettings(_Section):
    servers: dict[str, McpServerEntry] = Field(default_factory=dict)


class SkillsSettings(_Section):
    disabled: list[str] = Field(default_factory=list)


class Settings(_Section):
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    brain: BrainSettings = Field(default_factory=BrainSettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    skills: SkillsSettings = Field(default_factory=SkillsSettings)
