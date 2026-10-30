"""Handlers for every request in protocol/ipc.schema.json.

Methods owned by later work packages raise NOT_IMPLEMENTED in normal mode and use
sample data in --fake mode, so the app can be built against them already.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Coroutine
from typing import Any

from pydantic import ValidationError

from solana_core import __version__
from solana_core.brain.base import TextDelta
from solana_core.brain.dialog import ToolFinished, ToolStarted, TurnDone
from solana_core.fake.catalog import FakeCatalog
from solana_core.protocol import PROTOCOL_VERSION, Language
from solana_core.protocol.generated import (
    AssistantDeltaEvent,
    AssistantDoneEvent,
    ChatSendParams,
    ChatSendResult,
    ConfirmReplyParams,
    DownloadProgressEvent,
    EmptyParams,
    ErrorEvent,
    McpAddParams,
    McpListResult,
    McpNameParams,
    McpServerInfo,
    McpSetEnabledParams,
    ModelsDownloadParams,
    ModelsDownloadResult,
    ModelsListResult,
    OkResult,
    PingResult,
    Settings,
    SettingsResult,
    SettingsSetParams,
    SkillIdParams,
    SkillInfo,
    SkillsInstallParams,
    SkillsListResult,
    SkillsSetEnabledParams,
    StateEvent,
    ToolFinishedEvent,
    ToolInfo,
    ToolsListResult,
    ToolsSetEnabledParams,
    ToolStartedEvent,
    VoiceMuteParams,
)
from solana_core.server.core import Core
from solana_core.server.rpc import (
    CONFLICT,
    INVALID_PARAMS,
    NOT_FOUND,
    Dispatcher,
    RpcError,
    not_implemented,
)


def build_dispatcher(core: Core) -> Dispatcher:
    rpc = Dispatcher()
    catalog = FakeCatalog() if core.fake else None
    background: set[asyncio.Task[None]] = set()

    def spawn(coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        background.add(task)
        task.add_done_callback(background.discard)

    def settings_result() -> SettingsResult:
        return SettingsResult(settings=Settings(**core.config.settings.model_dump(mode="json")))

    @rpc.method("ping")
    async def ping(_: EmptyParams) -> PingResult:
        return PingResult(
            pong=True, version=__version__, protocol_version=PROTOCOL_VERSION, fake=core.fake
        )

    @rpc.method("state.get")
    async def state_get(_: EmptyParams) -> StateEvent:
        return core.state_event()

    @rpc.method("settings.get")
    async def settings_get(_: EmptyParams) -> SettingsResult:
        return settings_result()

    @rpc.method("settings.set")
    async def settings_set(params: SettingsSetParams) -> SettingsResult:
        try:
            core.config.update(params.patch.model_dump())
        except ValidationError as exc:
            raise RpcError(
                INVALID_PARAMS, "Invalid settings", exc.errors(include_url=False)
            ) from exc
        return settings_result()

    @rpc.method("voice.mute")
    async def voice_mute(params: VoiceMuteParams) -> VoiceMuteParams:
        if params.muted:
            core.set_state("muted", "user")
        elif core.muted:
            core.set_state("idle", "user")
        return VoiceMuteParams(muted=core.muted)

    @rpc.method("chat.send")
    async def chat_send(params: ChatSendParams) -> ChatSendResult:
        if core.llm is None:
            raise not_implemented("chat")
        turn_id = uuid.uuid4().hex
        language = params.language or core.config.settings.general.language
        spawn(_chat_turn(core, turn_id, params.text, language))
        return ChatSendResult(turn_id=turn_id)

    @rpc.method("confirm.reply")
    async def confirm_reply(params: ConfirmReplyParams) -> OkResult:
        return OkResult(ok=core.resolve_confirmation(params.request_id, params.approved))

    @rpc.method("tools.list")
    async def tools_list(_: EmptyParams) -> ToolsListResult:
        return ToolsListResult(tools=core.tools.infos())

    @rpc.method("tools.set_enabled")
    async def tools_set_enabled(params: ToolsSetEnabledParams) -> ToolInfo:
        try:
            core.tools.set_enabled(params.name, params.enabled)
        except KeyError as exc:
            raise RpcError(NOT_FOUND, f"Unknown tool: {params.name}") from exc
        core.config.update({"tools": {"disabled": core.tools.disabled_names()}})
        return core.tools.info(params.name)

    # MCP (WP7)
    @rpc.method("mcp.list")
    async def mcp_list(_: EmptyParams) -> McpListResult:
        return McpListResult(servers=list(catalog.mcp.values()) if catalog else [])

    @rpc.method("mcp.add")
    async def mcp_add(params: McpAddParams) -> McpServerInfo:
        if catalog is None:
            raise not_implemented("mcp.add")
        if params.name in catalog.mcp:
            raise RpcError(CONFLICT, f"MCP server already exists: {params.name}")
        server = McpServerInfo(
            name=params.name, config=params.config, enabled=True, status="connecting", tools=[]
        )
        catalog.mcp[params.name] = server
        return server

    @rpc.method("mcp.remove")
    async def mcp_remove(params: McpNameParams) -> OkResult:
        if catalog is None:
            raise not_implemented("mcp.remove")
        return OkResult(ok=catalog.mcp.pop(params.name, None) is not None)

    @rpc.method("mcp.set_enabled")
    async def mcp_set_enabled(params: McpSetEnabledParams) -> McpServerInfo:
        if catalog is None:
            raise not_implemented("mcp.set_enabled")
        server = catalog.mcp.get(params.name)
        if server is None:
            raise RpcError(NOT_FOUND, f"Unknown MCP server: {params.name}")
        server.enabled = params.enabled
        server.status = "connected" if params.enabled else "disconnected"
        return server

    # Skills (WP8)
    @rpc.method("skills.list")
    async def skills_list(_: EmptyParams) -> SkillsListResult:
        return SkillsListResult(skills=list(catalog.skills.values()) if catalog else [])

    @rpc.method("skills.install")
    async def skills_install(params: SkillsInstallParams) -> SkillInfo:
        if catalog is None:
            raise not_implemented("skills.install")
        skill_id = params.source.rstrip("/\\").rsplit("/", 1)[-1].removesuffix(".zip") or "skill"
        skill = SkillInfo(
            id=skill_id,
            name=skill_id,
            description=f"Установлен из {params.source}",
            languages=["ru"],
            builtin=False,
            enabled=True,
        )
        catalog.skills[skill_id] = skill
        return skill

    @rpc.method("skills.remove")
    async def skills_remove(params: SkillIdParams) -> OkResult:
        if catalog is None:
            raise not_implemented("skills.remove")
        return OkResult(ok=catalog.skills.pop(params.id, None) is not None)

    @rpc.method("skills.set_enabled")
    async def skills_set_enabled(params: SkillsSetEnabledParams) -> SkillInfo:
        if catalog is None:
            raise not_implemented("skills.set_enabled")
        skill = catalog.skills.get(params.id)
        if skill is None:
            raise RpcError(NOT_FOUND, f"Unknown skill: {params.id}")
        skill.enabled = params.enabled
        return skill

    # Models (WP2)
    @rpc.method("models.list")
    async def models_list(_: EmptyParams) -> ModelsListResult:
        return ModelsListResult(models=list(catalog.models.values()) if catalog else [])

    @rpc.method("models.download")
    async def models_download(params: ModelsDownloadParams) -> ModelsDownloadResult:
        if catalog is None:
            raise not_implemented("models.download")
        model = catalog.models.get(params.model_id)
        if model is None:
            raise RpcError(NOT_FOUND, f"Unknown model: {params.model_id}")
        download_id = uuid.uuid4().hex
        spawn(_fake_download(core, catalog, download_id, params.model_id))
        return ModelsDownloadResult(download_id=download_id)

    return rpc


async def _chat_turn(core: Core, turn_id: str, text: str, language: Language) -> None:
    """Run one text turn through ``core.dialog`` and forward its events to the app."""
    dialog = core.dialog
    assert dialog is not None
    async with core.turn_lock:
        core.set_state("thinking", "chat")
        async for event in dialog.turn(text, language=language, turn_id=turn_id):
            if isinstance(event, TextDelta):
                if core.state != "speaking":
                    core.set_state("speaking")
                core.bus.emit(
                    "assistant.delta", AssistantDeltaEvent(turn_id=turn_id, text=event.text)
                )
            elif isinstance(event, ToolStarted):
                core.bus.emit(
                    "tool.started",
                    ToolStartedEvent(
                        call_id=event.call.id,
                        turn_id=turn_id,
                        tool=event.call.name,
                        arguments=dict(event.call.arguments),
                    ),
                )
            elif isinstance(event, ToolFinished):
                result = event.result
                core.bus.emit(
                    "tool.finished",
                    ToolFinishedEvent(
                        call_id=event.call.id,
                        tool=event.call.name,
                        ok=result.ok,
                        summary=result.content[:200] if result.ok else None,
                        error=None if result.ok else result.content[:200],
                    ),
                )
            elif isinstance(event, TurnDone):
                if event.error:
                    core.bus.emit(
                        "error",
                        ErrorEvent(code="llm_unreachable", message=event.text, recoverable=True),
                    )
                core.bus.emit(
                    "assistant.done", AssistantDoneEvent(turn_id=turn_id, text=event.text)
                )
        if not core.muted:
            core.set_state("idle")


async def _fake_download(core: Core, catalog: FakeCatalog, download_id: str, model_id: str) -> None:
    model = catalog.models[model_id]
    total = model.size_bytes
    steps = 10
    for i in range(1, steps + 1):
        await asyncio.sleep(0.2)
        core.bus.emit(
            "download.progress",
            DownloadProgressEvent(
                download_id=download_id,
                model_id=model_id,
                downloaded_bytes=total * i // steps,
                total_bytes=total,
                done=i == steps,
            ),
        )
    model.installed = True
