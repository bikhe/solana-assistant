"""WebSocket transport: token check, request handling and event push."""

from __future__ import annotations

import asyncio
import hmac
import logging
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from solana_core.server.core import Core
from solana_core.server.events import encode_event
from solana_core.server.rpc import Dispatcher

log = logging.getLogger(__name__)


class CoreServer:
    """Listens on ``ws://host:port/?token=<token>``. Browsers can't set headers on
    WebSocket requests, so the token travels in the query string."""

    def __init__(self, core: Core, dispatcher: Dispatcher, token: str) -> None:
        self.core = core
        self.dispatcher = dispatcher
        self.token = token
        self._server: Server | None = None

    @property
    def port(self) -> int:
        assert self._server is not None, "server is not started"
        port: int = next(iter(self._server.sockets)).getsockname()[1]
        return port

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._server = await serve(
            self._handle, host, port, process_request=self._check_token, max_size=8 * 2**20
        )

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def _check_token(self, connection: ServerConnection, request: Request) -> Response | None:
        query = parse_qs(urlsplit(request.path).query)
        given = query.get("token", [""])[0]
        if not hmac.compare_digest(given.encode(), self.token.encode()):
            log.warning("rejected connection with a wrong token")
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized\n")
        return None

    async def _handle(self, ws: ServerConnection) -> None:
        queue = self.core.bus.subscribe()
        log.info("app connected")
        await ws.send(encode_event("state", self.core.state_event()))
        pump = asyncio.create_task(self._pump(ws, queue))
        try:
            async for raw in ws:
                response = await self.dispatcher.handle_raw(raw)
                if response is not None:
                    await ws.send(response)
        except ConnectionClosed:
            pass
        finally:
            pump.cancel()
            self.core.bus.unsubscribe(queue)
            log.info("app disconnected")

    @staticmethod
    async def _pump(ws: ServerConnection, queue: asyncio.Queue[str]) -> None:
        try:
            while True:
                await ws.send(await queue.get())
        except ConnectionClosed:
            pass
