"""chat.send runs the dialog: tool events, confirmations and persisted tool toggles."""

from __future__ import annotations

import asyncio

from solana_core.brain.base import FakeLLM, TextDelta, ToolCall, ToolCallRequest
from solana_core.config import ConfigStore
from solana_core.server.core import Core
from solana_core.tools import ToolRegistry
from solana_core.tools.base import FakeTool
from tests.conftest import Client
from tests.test_brain_dialog import PcTool


async def test_chat_runs_tool_loop(client: Client, core: Core) -> None:
    core.llm = FakeLLM(
        [
            [ToolCallRequest(ToolCall("c1", "fake.echo", {"text": "эхо"}))],
            [TextDelta("Повторила.")],
        ]
    )
    reply = await client.request("chat.send", {"text": "повтори за мной слово эхо"})
    turn_id = reply["result"]["turn_id"]
    started = await client.next_event("tool.started")
    assert started["params"] == {
        "call_id": "c1",
        "turn_id": turn_id,
        "tool": "fake.echo",
        "arguments": {"text": "эхо"},
    }
    finished = await client.next_event("tool.finished")
    assert finished["params"]["ok"] is True and finished["params"]["summary"] == "эхо"
    done = await client.next_event("assistant.done")
    assert done["params"] == {"turn_id": turn_id, "text": "Повторила."}


async def test_chat_fast_command(client: Client, core: Core) -> None:
    volume = PcTool("pc.volume_change")
    core.tools.register(volume)
    await client.request("chat.send", {"text": "громче"})
    done = await client.next_event("assistant.done")
    assert done["params"]["text"] == "Громче."
    assert volume.calls == [{"delta": 10}]


async def test_chat_language_param(client: Client, core: Core) -> None:
    core.tools.register(PcTool("pc.media"))
    await client.request("chat.send", {"text": "pause", "language": "en"})
    done = await client.next_event("assistant.done")
    assert done["params"]["text"] == "Paused."


async def test_confirm_tool_asks_the_app(client: Client, core: Core) -> None:
    close = PcTool("pc.app_close", risk="confirm")
    core.tools.register(close)
    await client.request("chat.send", {"text": "закрой блокнот"})
    request = await client.next_event("confirm.request")
    assert request["params"]["tool"] == "pc.app_close"
    assert request["params"]["arguments"] == {"name": "блокнот"}
    await client.request(
        "confirm.reply", {"request_id": request["params"]["request_id"], "approved": True}
    )
    done = await client.next_event("assistant.done")
    assert done["params"]["text"] == "Закрыла блокнот."
    assert close.calls == [{"name": "блокнот"}]


async def test_always_allow_skips_confirmation(core: Core) -> None:
    core.config.update({"tools": {"always_allow": ["pc.app_close"]}})
    tool = PcTool("pc.app_close", risk="confirm")
    assert await core.approve_tool(tool, ToolCall("1", tool.name, {}))
    dangerous = PcTool("pc.shutdown", risk="dangerous")
    core.config.update({"tools": {"always_allow": ["pc.shutdown"]}})
    approval = asyncio.create_task(core.approve_tool(dangerous, ToolCall("2", "pc.shutdown", {})))
    await asyncio.sleep(0)
    assert not approval.done()  # dangerous always waits for a click
    approval.cancel()


async def test_tool_toggle_is_saved(client: Client, core: Core, config: ConfigStore) -> None:
    await client.request("tools.set_enabled", {"name": "fake.echo", "enabled": False})
    assert config.settings.tools.disabled == ["fake.echo"]
    reloaded = Core(ConfigStore(config.path), core.secrets)
    reloaded.tools.register(FakeTool())
    assert not reloaded.tools.is_enabled("fake.echo")


def test_registry_keeps_user_choice_across_reconnects() -> None:
    reg = ToolRegistry(disabled=["mcp.files.read"])
    reg.register(PcTool("mcp.files.read"))
    reg.register(PcTool("mcp.files.write"))
    assert not reg.is_enabled("mcp.files.read")
    assert sorted(reg.unregister_prefix("mcp.files.")) == ["mcp.files.read", "mcp.files.write"]
    assert len(reg) == 0
    reg.register(PcTool("mcp.files.read"))
    assert "mcp.files.read" in reg and not reg.is_enabled("mcp.files.read")
    reg.register(PcTool("mcp.files.read"), replace=True)
    assert reg.disabled_names() == ["mcp.files.read"]
