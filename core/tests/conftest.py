from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.client import ClientConnection, connect

from solana_core.brain.base import FakeLLM
from solana_core.config import ConfigStore, MemorySecretStore
from solana_core.server.core import Core
from solana_core.server.handlers import build_dispatcher
from solana_core.server.ws import CoreServer
from solana_core.tools.base import FakeTool

TOKEN = "test-token"


class Client:
    """Tiny JSON-RPC client that keeps events and responses apart."""

    def __init__(self, ws: ClientConnection) -> None:
        self.ws = ws
        self.events: list[dict[str, Any]] = []
        self._next_id = 0

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        await self.ws.send(json.dumps(message))
        while True:
            reply = json.loads(await self.ws.recv())
            if reply.get("id") == request_id:
                return dict(reply)
            self.events.append(reply)

    async def next_event(self, name: str) -> dict[str, Any]:
        for i, event in enumerate(self.events):
            if event["method"] == name:
                return self.events.pop(i)
        while True:
            message = json.loads(await self.ws.recv())
            if message.get("method") == name:
                return dict(message)
            self.events.append(message)


@pytest.fixture
def config(tmp_path: Path) -> ConfigStore:
    return ConfigStore(tmp_path / "config.toml")


@pytest.fixture
def core(config: ConfigStore) -> Core:
    c = Core(config, MemorySecretStore(), llm=FakeLLM(), fake=True)
    c.tools.register(FakeTool())
    return c


@pytest.fixture
async def server(core: Core) -> AsyncIterator[CoreServer]:
    srv = CoreServer(core, build_dispatcher(core), TOKEN)
    await srv.start()
    yield srv
    await srv.close()


ClientFactory = Callable[[], Awaitable[Client]]


@pytest.fixture
async def client(server: CoreServer) -> AsyncIterator[Client]:
    async with connect(f"ws://127.0.0.1:{server.port}/?token={TOKEN}") as ws:
        yield Client(ws)
