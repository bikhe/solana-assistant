from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from solana_core.__main__ import READY_PREFIX
from solana_core.fake.scenario import FakeScenario
from solana_core.protocol import METHODS
from solana_core.server.core import Core
from solana_core.server.handlers import build_dispatcher
from solana_core.server.rpc import NOT_IMPLEMENTED
from solana_core.server.ws import CoreServer
from tests.conftest import Client


def test_every_protocol_method_has_a_handler(core: Core) -> None:
    assert build_dispatcher(core).methods == set(METHODS)


async def test_wrong_token_is_rejected(server: CoreServer) -> None:
    for query in ("", "?token=nope"):
        with pytest.raises(InvalidStatus) as info:
            async with connect(f"ws://127.0.0.1:{server.port}/{query}"):
                pass
        assert info.value.response.status_code == 401


async def test_state_event_on_connect_and_ping(client: Client) -> None:
    event = await client.next_event("state")
    assert event["params"] == {"state": "idle"}
    reply = await client.request("ping")
    assert reply["result"]["pong"] is True
    assert reply["result"]["fake"] is True


async def test_mute_broadcasts_state(client: Client) -> None:
    await client.next_event("state")
    reply = await client.request("voice.mute", {"muted": True})
    assert reply["result"] == {"muted": True}
    event = await client.next_event("state")
    assert event["params"]["state"] == "muted"
    assert event["params"]["previous"] == "idle"
    await client.request("voice.mute", {"muted": False})
    assert (await client.next_event("state"))["params"]["state"] == "idle"


async def test_settings_roundtrip(client: Client, core: Core) -> None:
    settings = (await client.request("settings.get"))["result"]["settings"]
    assert settings["general"]["language"] == "ru"
    reply = await client.request("settings.set", {"patch": {"brain": {"mode": "cloud"}}})
    assert reply["result"]["settings"]["brain"]["mode"] == "cloud"
    assert reply["result"]["settings"]["brain"]["local_provider"] == "ollama"
    assert core.config.load().brain.mode == "cloud"
    bad = await client.request("settings.set", {"patch": {"brain": {"mode": "telepathy"}}})
    assert bad["error"]["code"] == -32602


async def test_chat_streams_answer(client: Client) -> None:
    reply = await client.request("chat.send", {"text": "привет"})
    turn_id = reply["result"]["turn_id"]
    delta = await client.next_event("assistant.delta")
    assert delta["params"]["turn_id"] == turn_id
    done = await client.next_event("assistant.done")
    assert done["params"]["text"] == "Вы сказали: привет"


async def test_chat_not_implemented_without_llm(client: Client, core: Core) -> None:
    core.llm = None
    reply = await client.request("chat.send", {"text": "привет"})
    assert reply["error"]["code"] == NOT_IMPLEMENTED


async def test_confirmation_flow(client: Client, core: Core) -> None:
    pending = asyncio.create_task(core.confirm("pc.shutdown", "dangerous", "Выключить?", {}))
    event = await client.next_event("confirm.request")
    assert event["params"]["voice_allowed"] is False
    reply = await client.request(
        "confirm.reply", {"request_id": event["params"]["request_id"], "approved": True}
    )
    assert reply["result"] == {"ok": True}
    assert await pending is True


async def test_confirmation_times_out(core: Core) -> None:
    assert await core.confirm("x", "confirm", "x", {}, timeout_s=0.01) is False


async def test_tools_list_and_toggle(client: Client) -> None:
    tools = (await client.request("tools.list"))["result"]["tools"]
    assert [t["name"] for t in tools] == ["fake.echo"]
    reply = await client.request("tools.set_enabled", {"name": "fake.echo", "enabled": False})
    assert reply["result"]["enabled"] is False
    missing = await client.request("tools.set_enabled", {"name": "nope", "enabled": False})
    assert missing["error"]["code"] == -32002


async def test_fake_catalog(client: Client) -> None:
    servers = (await client.request("mcp.list"))["result"]["servers"]
    assert {s["name"] for s in servers} == {"filesystem", "home-assistant"}
    skills = (await client.request("skills.list"))["result"]["skills"]
    assert skills
    models = (await client.request("models.list"))["result"]["models"]
    assert any(not m["installed"] for m in models)


async def test_fake_scenario_plays_full_cycle(client: Client, core: Core) -> None:
    await client.next_event("state")
    scenario = FakeScenario(core, speed=50)
    task = asyncio.create_task(scenario.cycle())
    states: list[str] = []
    while len(states) < 5:
        states.append((await client.next_event("state"))["params"]["state"])
    assert states == ["wake", "listening", "thinking", "speaking", "idle"]
    await task
    names = {e["method"] for e in client.events}
    assert {"transcript.partial", "transcript.final", "assistant.delta", "assistant.done"} <= names


def test_cli_prints_ready_line_and_serves() -> None:
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "solana_core", "--fake", "--port", "0", "--token", "t0k"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        assert line.startswith(READY_PREFIX)
        info = json.loads(line[len(READY_PREFIX) :])
        assert info["token"] == "t0k"

        async def check() -> None:
            async with connect(f"ws://127.0.0.1:{info['port']}/?token=t0k") as ws:
                event = json.loads(await ws.recv())
                assert event["method"] == "state"

        asyncio.run(check())
    finally:
        proc.terminate()
        proc.wait(10)
