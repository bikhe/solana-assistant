# Generated from protocol/ipc.schema.json by scripts/gen_protocol.py. Do not edit.

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class EmptyParams(BaseModel):
    pass
    model_config = ConfigDict(
        extra="forbid",
    )


class OkResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ok: bool


class Settings(BaseModel):
    """
    The full user settings document. Its shape is defined by the pydantic model in core/solana_core/config/.
    """

    model_config = ConfigDict(
        extra="allow",
    )


class ToolInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str
    description: str
    risk: Literal["safe", "confirm", "dangerous"] = Field(
        ...,
        description="safe runs at once, confirm waits for a voice yes or a click, dangerous needs a click.",
    )
    source: Literal["builtin", "mcp", "skill"]
    enabled: bool


class McpServerConfig(BaseModel):
    """
    Same shape as one entry of mcpServers in Claude Desktop config. stdio servers use command/args/env, HTTP servers use url/headers.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None


class McpServerInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str
    config: McpServerConfig
    enabled: bool
    status: Literal["connected", "connecting", "disconnected", "error"]
    error: str | None = None
    tools: list[ToolInfo]


class SkillInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    name: str
    description: str
    languages: list[Literal["ru", "en"]]
    builtin: bool
    enabled: bool


class ModelInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    kind: Literal["wake", "vad", "stt", "tts", "llm", "embedding"]
    name: str
    size_bytes: int = Field(..., ge=0)
    installed: bool


class PingResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    pong: Literal[True]
    version: str = Field(..., description="solana-core version")
    protocol_version: int
    fake: bool = Field(..., description="true when core runs with --fake")


class PingRequest(BaseModel):
    params: EmptyParams
    result: PingResult


class SettingsResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    settings: Settings


class SettingsGetRequest(BaseModel):
    params: EmptyParams
    result: SettingsResult


class SettingsSetParams(BaseModel):
    """
    Deep-merge patch applied to the current settings. Secrets (API keys) never go through settings; they are stored in the OS keyring.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    patch: Settings


class SettingsSetRequest(BaseModel):
    params: SettingsSetParams
    result: SettingsResult


class ChatSendParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    text: str = Field(..., min_length=1)
    language: Literal["ru", "en"] | None = None


class ChatSendResult(BaseModel):
    """
    The answer itself streams as assistant.delta / assistant.done events with this turn_id.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    turn_id: str


class ChatSendRequest(BaseModel):
    params: ChatSendParams
    result: ChatSendResult


class VoiceMuteParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    muted: bool


class VoiceMuteRequest(BaseModel):
    params: VoiceMuteParams
    result: VoiceMuteParams


class ConfirmReplyParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    request_id: str
    approved: bool
    always: bool | None = Field(
        None,
        description="Always allow this tool from now on. Ignored for dangerous tools.",
    )


class ConfirmReplyRequest(BaseModel):
    params: ConfirmReplyParams
    result: OkResult


class ToolsListResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    tools: list[ToolInfo]


class ToolsListRequest(BaseModel):
    params: EmptyParams
    result: ToolsListResult


class ToolsSetEnabledParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str
    enabled: bool


class ToolsSetEnabledRequest(BaseModel):
    params: ToolsSetEnabledParams
    result: ToolInfo


class McpListResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    servers: list[McpServerInfo]


class McpListRequest(BaseModel):
    params: EmptyParams
    result: McpListResult


class McpAddParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str = Field(..., min_length=1)
    config: McpServerConfig


class McpAddRequest(BaseModel):
    params: McpAddParams
    result: McpServerInfo


class McpNameParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str


class McpRemoveRequest(BaseModel):
    params: McpNameParams
    result: OkResult


class McpSetEnabledParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str
    enabled: bool


class McpSetEnabledRequest(BaseModel):
    params: McpSetEnabledParams
    result: McpServerInfo


class SkillsListResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    skills: list[SkillInfo]


class SkillsListRequest(BaseModel):
    params: EmptyParams
    result: SkillsListResult


class SkillsInstallParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    source: str = Field(
        ..., description="Local folder, path to a .zip file, or a git URL."
    )


class SkillsInstallRequest(BaseModel):
    params: SkillsInstallParams
    result: SkillInfo


class SkillIdParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str


class SkillsRemoveRequest(BaseModel):
    params: SkillIdParams
    result: OkResult


class SkillsSetEnabledParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    enabled: bool


class SkillsSetEnabledRequest(BaseModel):
    params: SkillsSetEnabledParams
    result: SkillInfo


class ModelsListResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    models: list[ModelInfo]


class ModelsListRequest(BaseModel):
    params: EmptyParams
    result: ModelsListResult


class ModelsDownloadParams(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    model_id: str


class ModelsDownloadResult(BaseModel):
    """
    Progress arrives as download.progress events with this download_id.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    download_id: str


class ModelsDownloadRequest(BaseModel):
    params: ModelsDownloadParams
    result: ModelsDownloadResult


class StateEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    state: Literal[
        "idle", "wake", "listening", "thinking", "speaking", "muted", "error"
    ] = Field(
        ...,
        description="Main loop: idle -> wake -> listening -> thinking -> speaking -> idle. muted and error can be entered from any state.",
    )
    previous: (
        Literal["idle", "wake", "listening", "thinking", "speaking", "muted", "error"]
        | None
    ) = Field(
        None,
        description="Main loop: idle -> wake -> listening -> thinking -> speaking -> idle. muted and error can be entered from any state.",
    )
    reason: str | None = Field(
        None,
        description="Short machine-readable cause, e.g. wake_word, hotkey, timeout.",
    )


class TranscriptEvent(BaseModel):
    """
    Used by both transcript.partial and transcript.final.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    utterance_id: str
    text: str
    language: Literal["ru", "en"] | None = None


class AssistantDeltaEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    turn_id: str
    text: str = Field(..., description="Next chunk of the answer.")


class AssistantDoneEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    turn_id: str
    text: str = Field(..., description="The full answer.")
    interrupted: bool | None = None


class ToolStartedEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    call_id: str
    turn_id: str | None = None
    tool: str
    arguments: dict[str, Any]


class ToolFinishedEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    call_id: str
    tool: str
    ok: bool
    summary: str | None = None
    error: str | None = None


class ConfirmRequestEvent(BaseModel):
    """
    Ask the user to approve a tool call. The app answers with confirm.reply.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    request_id: str
    tool: str
    risk: Literal["safe", "confirm", "dangerous"] = Field(
        ...,
        description="safe runs at once, confirm waits for a voice yes or a click, dangerous needs a click.",
    )
    title: str = Field(..., description="Human readable, in the user's language.")
    details: str | None = None
    arguments: dict[str, Any]
    voice_allowed: bool = Field(
        ..., description="false for dangerous tools: only a click can approve."
    )
    timeout_s: float | None = Field(None, gt=0.0)


class DownloadProgressEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    download_id: str
    model_id: str
    downloaded_bytes: int = Field(..., ge=0)
    total_bytes: int | None = Field(..., ge=0)
    done: bool
    error: str | None = None


class ErrorEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: str = Field(
        ...,
        description="Stable machine-readable code, e.g. mic_unavailable, llm_unreachable.",
    )
    message: str = Field(..., description="Human readable, in the user's language.")
    recoverable: bool


class EventMap(BaseModel):
    """
    Every notification the core sends to the app.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    state: StateEvent
    transcript_partial: TranscriptEvent = Field(..., alias="transcript.partial")
    transcript_final: TranscriptEvent = Field(..., alias="transcript.final")
    assistant_delta: AssistantDeltaEvent = Field(..., alias="assistant.delta")
    assistant_done: AssistantDoneEvent = Field(..., alias="assistant.done")
    tool_started: ToolStartedEvent = Field(..., alias="tool.started")
    tool_finished: ToolFinishedEvent = Field(..., alias="tool.finished")
    confirm_request: ConfirmRequestEvent = Field(..., alias="confirm.request")
    download_progress: DownloadProgressEvent = Field(..., alias="download.progress")
    error: ErrorEvent


class StateGetRequest(BaseModel):
    params: EmptyParams
    result: StateEvent


class RequestMap(BaseModel):
    """
    Every request method the core accepts.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    ping: PingRequest
    state_get: StateGetRequest = Field(..., alias="state.get")
    settings_get: SettingsGetRequest = Field(..., alias="settings.get")
    settings_set: SettingsSetRequest = Field(..., alias="settings.set")
    chat_send: ChatSendRequest = Field(..., alias="chat.send")
    voice_mute: VoiceMuteRequest = Field(..., alias="voice.mute")
    confirm_reply: ConfirmReplyRequest = Field(..., alias="confirm.reply")
    tools_list: ToolsListRequest = Field(..., alias="tools.list")
    tools_set_enabled: ToolsSetEnabledRequest = Field(..., alias="tools.set_enabled")
    mcp_list: McpListRequest = Field(..., alias="mcp.list")
    mcp_add: McpAddRequest = Field(..., alias="mcp.add")
    mcp_remove: McpRemoveRequest = Field(..., alias="mcp.remove")
    mcp_set_enabled: McpSetEnabledRequest = Field(..., alias="mcp.set_enabled")
    skills_list: SkillsListRequest = Field(..., alias="skills.list")
    skills_install: SkillsInstallRequest = Field(..., alias="skills.install")
    skills_remove: SkillsRemoveRequest = Field(..., alias="skills.remove")
    skills_set_enabled: SkillsSetEnabledRequest = Field(..., alias="skills.set_enabled")
    models_list: ModelsListRequest = Field(..., alias="models.list")
    models_download: ModelsDownloadRequest = Field(..., alias="models.download")


class IpcProtocol(BaseModel):
    """
    Solana IPC: JSON-RPC 2.0 over WebSocket between solana-app and solana-core. RequestMap lists app -> core requests (params and result of each method). EventMap lists core -> app notifications (params of each event). Field names on the wire are snake_case. This file is the single source of truth: TS types and pydantic models are generated from it.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    protocol_version: Literal[1]
    requests: RequestMap
    events: EventMap
