"""MCP: manager with the fake connector, the real SDK against tests/fixtures/mcp_server.py,
the JSON-RPC methods and a chat turn that calls an MCP tool."""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from websockets.asyncio.client import connect

from solana_core.brain.base import FakeLLM, TextDelta, ToolCall, ToolCallRequest
from solana_core.config import ConfigStore, MemorySecretStore
from solana_core.config.models import McpServerEntry
from solana_core.mcp import FakeConnector, McpError, McpManager, RemoteTool, sdk_connector
from solana_core.mcp.config import McpConfigError, expand_args
from solana_core.mcp.manager import describe_error
from solana_core.protocol.generated import McpServerConfig
from solana_core.server.core import Core
from solana_core.server.handlers import build_dispatcher
from solana_core.server.ws import CoreServer
from solana_core.tools import ToolContext, ToolRegistry
from tests.conftest import TOKEN, Client

SERVER = Path(__file__).parent / "fixtures" / "mcp_server.py"
STDIO = McpServerConfig(command=sys.executable, args=[str(SERVER)])


@pytest.fixture
def connector() -> FakeConnector:
    return FakeConnector({"files": [RemoteTool("read", "Прочитать файл")]})


@pytest.fixture
async def manager(config: ConfigStore, connector: FakeConnector) -> AsyncIterator[McpManager]:
    mgr = McpManager(config, ToolRegistry(), connector, retry_s=0.01, max_retry_s=0.05)
    mgr.start()
    yield mgr
    await mgr.close()


def registry(mgr: McpManager) -> ToolRegistry:
    return mgr._tools


# Manager


async def test_add_connects_and_registers_tools(manager: McpManager, config: ConfigStore) -> None:
    info = manager.add("files", McpServerConfig(command="npx", args=["server"]))
    assert info.enabled and info.status in ("connecting", "disconnected")
    await manager.wait_for("files", "connected")
    tool = registry(manager).get("mcp.files.read")
    assert tool is not None and tool.risk == "confirm" and tool.source == "mcp"
    assert "[MCP files]" in tool.description
    info = manager.info("files")
    assert info.status == "connected" and [t.name for t in info.tools] == ["mcp.files.read"]
    # Saved in the settings file in the Claude Desktop shape.
    saved = ConfigStore(config.path).settings.mcp.servers["files"]
    assert saved.command == "npx" and saved.args == ["server"] and saved.enabled


async def test_tool_call_goes_to_the_server(manager: McpManager, connector: FakeConnector) -> None:
    manager.add("files", McpServerConfig(command="x"))
    await manager.wait_for("files", "connected")
    tool = registry(manager).get("mcp.files.read")
    assert tool is not None
    result = await tool.run({"path": "/tmp/a"}, ToolContext())
    assert result.ok and connector.opened["files"].calls == [("read", {"path": "/tmp/a"})]


async def test_reconnects_after_crash_and_keeps_user_choices(
    manager: McpManager, connector: FakeConnector
) -> None:
    manager.add("files", McpServerConfig(command="x"))
    await manager.wait_for("files", "connected")
    registry(manager).set_enabled("mcp.files.read", False)
    connector.opened["files"].drop("boom")
    await manager.wait_for("files", "error", "connecting")
    await manager.wait_for("files", "connected")
    assert connector.attempts["files"] == 2
    assert "mcp.files.read" in registry(manager)
    assert not registry(manager).is_enabled("mcp.files.read")  # still disabled


async def test_tool_list_change_is_picked_up(manager: McpManager, connector: FakeConnector) -> None:
    manager.add("files", McpServerConfig(command="x"))
    await manager.wait_for("files", "connected")
    connector.opened["files"].set_tools([RemoteTool("write", "Записать")])
    for _ in range(100):
        if "mcp.files.write" in registry(manager):
            break
        await asyncio.sleep(0.01)
    assert "mcp.files.write" in registry(manager) and "mcp.files.read" not in registry(manager)


async def test_failing_server_reports_error_and_retries(
    manager: McpManager, connector: FakeConnector
) -> None:
    connector.fail["bad"] = "nope"
    manager.add("bad", McpServerConfig(url="https://example.invalid/mcp"))
    await manager.wait_for("bad", "error")
    assert manager.info("bad").error == "nope"
    for _ in range(100):
        if connector.attempts["bad"] >= 3:
            break
        await asyncio.sleep(0.01)
    assert connector.attempts["bad"] >= 3


async def test_disable_and_remove(manager: McpManager, config: ConfigStore) -> None:
    manager.add("files", McpServerConfig(command="x"))
    await manager.wait_for("files", "connected")
    info = manager.set_enabled("files", False)
    assert not info.enabled and info.status == "disconnected" and info.tools == []
    assert "mcp.files.read" not in registry(manager)
    info = manager.set_enabled("files", True)
    await manager.wait_for("files", "connected")
    assert manager.remove("files")
    assert not manager.remove("files")
    assert "mcp.files.read" not in registry(manager)
    assert config.settings.mcp.servers == {}


async def test_settings_change_is_synced(manager: McpManager, config: ConfigStore) -> None:
    config.update({"mcp": {"servers": {"files": {"command": "x"}}}})
    manager.sync()
    await manager.wait_for("files", "connected")
    config.update({"mcp": {"servers": {"files": {"enabled": False}}}})
    manager.sync()
    assert manager.info("files").status == "disconnected"


async def test_add_validates(manager: McpManager) -> None:
    with pytest.raises(McpConfigError):
        manager.add("bad name", McpServerConfig(command="x"))
    with pytest.raises(McpConfigError):
        manager.add("both", McpServerConfig(command="x", url="https://a"))
    with pytest.raises(McpConfigError):
        manager.add("none", McpServerConfig())
    with pytest.raises(McpConfigError):
        manager.add("ftp", McpServerConfig(url="ftp://a"))
    manager.add("ok", McpServerConfig(command="x"))
    with pytest.raises(McpError):
        manager.add("ok", McpServerConfig(command="y"))


def test_expand_args_and_errors() -> None:
    home = str(Path.home())
    assert expand_args(["~", "~/docs", "a~b"]) == [home, home + "/docs", "a~b"]
    error = FileNotFoundError(2, "No such file", "npx")
    assert "Node.js" in describe_error(error)
    group = ExceptionGroup("tg", [TimeoutError()])
    assert describe_error(group) == "Сервер не ответил вовремя"


# Real SDK against the fixture server


async def test_stdio_server_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "заметки.txt").write_text("привет", encoding="utf-8")
    entry = McpServerEntry(command=sys.executable, args=[str(SERVER)])
    async with sdk_connector("test", entry) as conn:
        tools = {t.name: t for t in await conn.list_tools()}
        assert set(tools) >= {"echo", "add", "list_dir", "fail", "crash"}
        assert tools["add"].input_schema["required"] == ["a", "b"]
        added = await conn.call_tool("add", {"a": 2, "b": 3}, 10)
        assert added.ok and added.content == "5"
        listing = await conn.call_tool("list_dir", {"path": str(tmp_path)}, 10)
        assert listing.content == "заметки.txt"
        failed = await conn.call_tool("fail", {"reason": "нельзя"}, 10)
        assert not failed.ok and "нельзя" in failed.content


async def test_manager_reconnects_a_crashed_stdio_server(config: ConfigStore) -> None:
    mgr = McpManager(config, ToolRegistry(), retry_s=0.05)
    mgr.start()
    try:
        mgr.add("test", STDIO)
        await mgr.wait_for("test", "connected", timeout_s=30)
        crash = registry(mgr).get("mcp.test.crash")
        assert crash is not None
        result = None
        try:
            result = await crash.run({}, ToolContext())
        except Exception as exc:
            assert "MCP" in str(exc)
        assert result is None or not result.ok
        await mgr.wait_for("test", "error", "connecting", timeout_s=30)
        await mgr.wait_for("test", "connected", timeout_s=30)
        echo = registry(mgr).get("mcp.test.echo")
        assert echo is not None
        assert (await echo.run({"text": "снова тут"}, ToolContext())).content == "снова тут"
    finally:
        await mgr.close()


async def test_missing_command_is_explained(config: ConfigStore) -> None:
    mgr = McpManager(config, ToolRegistry(), retry_s=10)
    mgr.start()
    try:
        mgr.add("ghost", McpServerConfig(command="solana-no-such-command-xyz"))
        await mgr.wait_for("ghost", "error", timeout_s=30)
        error = mgr.info("ghost").error
        assert error and "solana-no-such-command-xyz" in error
    finally:
        await mgr.close()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(params=["http", "sse"])
def http_server(request: pytest.FixtureRequest) -> Iterator[str]:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(SERVER), request.param, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(200):
            try:
                socket.create_connection(("127.0.0.1", port), 0.1).close()
                break
            except OSError:
                if proc.poll() is not None:
                    raise RuntimeError("test MCP server exited") from None
                import time

                time.sleep(0.05)
        path = "/mcp" if request.param == "http" else "/sse"
        yield f"http://127.0.0.1:{port}{path}"
    finally:
        proc.terminate()
        proc.wait(10)


async def test_http_transports(http_server: str) -> None:
    async with sdk_connector("web", McpServerEntry(url=http_server)) as conn:
        assert "echo" in {t.name for t in await conn.list_tools()}
        result = await conn.call_tool("echo", {"text": "по сети"}, 10)
        assert result.content == "по сети"


# JSON-RPC (fake mode serves demo servers through the same manager)


async def test_rpc_methods(client: Client) -> None:
    listed = (await client.request("mcp.list"))["result"]["servers"]
    assert {s["name"] for s in listed} >= {"filesystem", "home-assistant"}

    added = await client.request(
        "mcp.add", {"name": "docs", "config": {"url": "https://mcp.example.com/mcp"}}
    )
    assert added["result"]["name"] == "docs" and added["result"]["enabled"]
    dup = await client.request("mcp.add", {"name": "docs", "config": {"command": "x"}})
    assert dup["error"]["code"] == -32003
    bad = await client.request("mcp.add", {"name": "a b", "config": {"command": "x"}})
    assert bad["error"]["code"] == -32602

    off = await client.request("mcp.set_enabled", {"name": "docs", "enabled": False})
    assert off["result"]["enabled"] is False
    missing = await client.request("mcp.set_enabled", {"name": "nope", "enabled": True})
    assert missing["error"]["code"] == -32002
    assert (await client.request("mcp.remove", {"name": "docs"}))["result"] == {"ok": True}


async def test_demo_server_tools_show_up(client: Client) -> None:
    for _ in range(200):
        servers = (await client.request("mcp.list"))["result"]["servers"]
        fs = next(s for s in servers if s["name"] == "filesystem")
        if fs["status"] == "connected":
            break
        await asyncio.sleep(0.01)
    assert fs["status"] == "connected"
    assert {t["name"] for t in fs["tools"]} == {
        "mcp.filesystem.read_text_file",
        "mcp.filesystem.list_directory",
    }
    tools = (await client.request("tools.list"))["result"]["tools"]
    assert any(t["name"] == "mcp.filesystem.list_directory" and t["source"] == "mcp" for t in tools)
    ha = next(s for s in servers if s["name"] == "home-assistant")
    assert ha["status"] == "disconnected" and not ha["enabled"]


async def test_chat_uses_mcp_tool_after_confirmation(config: ConfigStore, tmp_path: Path) -> None:
    """The done-criterion of WP7 in miniature: a file question answered through MCP."""
    folder = tmp_path / "отчёты"
    folder.mkdir()
    (folder / "отчёт.docx").write_bytes(b"")
    core = Core(config, MemorySecretStore(), llm=FakeLLM())
    mgr = McpManager(core.config, core.tools)
    server = CoreServer(core, build_dispatcher(core, mcp=mgr), TOKEN)
    await server.start()
    mgr.start()
    try:
        async with connect(f"ws://127.0.0.1:{server.port}/?token={TOKEN}") as ws:
            client = Client(ws)
            added = await client.request(
                "mcp.add", {"name": "test", "config": STDIO.model_dump(exclude_none=True)}
            )
            assert "error" not in added
            await mgr.wait_for("test", "connected", timeout_s=30)
            core.llm = FakeLLM(
                [
                    [ToolCallRequest(ToolCall("c1", "mcp.test.list_dir", {"path": str(folder)}))],
                    [TextDelta("В папке один файл: отчёт.")],
                ]
            )
            await client.request("chat.send", {"text": "что лежит в папке с отчётами?"})
            request = await client.next_event("confirm.request")
            assert request["params"]["tool"] == "mcp.test.list_dir"
            assert request["params"]["risk"] == "confirm"
            await client.request(
                "confirm.reply", {"request_id": request["params"]["request_id"], "approved": True}
            )
            finished = await client.next_event("tool.finished")
            assert finished["params"]["ok"] and finished["params"]["summary"] == "отчёт.docx"
            done = await client.next_event("assistant.done")
            assert done["params"]["text"] == "В папке один файл: отчёт."
    finally:
        await mgr.close()
        await server.close()


# Solana as an MCP server


async def test_solana_serves_its_tools_over_mcp() -> None:
    from mcp import Client

    from solana_core.mcp.server import build_server
    from tests.test_brain_dialog import PcTool

    tools = ToolRegistry()
    tools.register(PcTool("pc.volume_set"))
    tools.register(PcTool("pc.app_close", risk="confirm"))
    tools.register(PcTool("pc.shutdown", risk="dangerous"))
    tools.register(PcTool("pc.hidden"))
    tools.set_enabled("pc.hidden", False)
    async with Client(build_server(tools)) as client:
        listed = {t.name: t for t in (await client.list_tools()).tools}
        assert set(listed) == {"pc.volume_set", "pc.app_close"}
        annotations = listed["pc.app_close"].annotations
        assert annotations is not None and annotations.destructive_hint
        result = await client.call_tool("pc.volume_set", {"level": 30})
        assert not result.is_error
        blocked = await client.call_tool("pc.shutdown", {})
        assert blocked.is_error


async def test_mcp_server_command(tmp_path: Path) -> None:
    """``solana-core --mcp-server`` as Claude Desktop would start it."""
    args = ["-m", "solana_core", "--mcp-server", "--config", str(tmp_path / "c.toml")]
    async with sdk_connector("solana", McpServerEntry(command=sys.executable, args=args)) as conn:
        names = {t.name for t in await conn.list_tools()}
    assert "pc.volume_set" in names and "pc.shutdown" not in names
