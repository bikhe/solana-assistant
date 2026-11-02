"""One live connection to an MCP server, behind an interface with a fake for tests."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, TextIO

from solana_core import __version__
from solana_core.config.models import McpServerEntry
from solana_core.mcp.config import expand_args
from solana_core.tools.base import ToolError, ToolResult

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RemoteTool:
    """A tool as the server describes it."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})


class McpConnection(ABC):
    """An initialized session. Lives inside the ``Connector`` context that opened it."""

    @abstractmethod
    async def list_tools(self) -> list[RemoteTool]: ...

    @abstractmethod
    async def call_tool(self, name: str, args: dict[str, Any], timeout_s: float) -> ToolResult:
        """Raise ``ToolError`` for transport failures; a tool error is ``ok=False``."""

    @abstractmethod
    async def wait_changed(self) -> None:
        """Return when the tool list changed. Raise when the connection is lost."""


# Opens a connection for a server entry; leaving the context closes it.
Connector = Callable[[str, McpServerEntry], AbstractAsyncContextManager[McpConnection]]


# Fake


class FakeConnection(McpConnection):
    """Serves fixed tools; ``call_tool`` echoes the arguments. ``drop()`` simulates a crash."""

    def __init__(self, tools: list[RemoteTool]) -> None:
        self.tools = tools
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._changed = asyncio.Event()
        self._lost: Exception | None = None

    async def list_tools(self) -> list[RemoteTool]:
        return list(self.tools)

    async def call_tool(self, name: str, args: dict[str, Any], timeout_s: float) -> ToolResult:
        if self._lost:
            raise ToolError("MCP-сервер недоступен")
        self.calls.append((name, args))
        return ToolResult(f"{name}: {args}")

    async def wait_changed(self) -> None:
        await self._changed.wait()
        self._changed.clear()
        if self._lost:
            raise self._lost

    def set_tools(self, tools: list[RemoteTool]) -> None:
        self.tools = tools
        self._changed.set()

    def drop(self, error: str = "server exited") -> None:
        self._lost = ConnectionError(error)
        self._changed.set()


class FakeConnector:
    """Connector for tests and --fake mode. ``tools`` by server name; ``fail`` makes it raise."""

    def __init__(
        self,
        tools: dict[str, list[RemoteTool]] | None = None,
        *,
        default: list[RemoteTool] | None = None,
    ) -> None:
        self.tools = tools or {}
        self.default = default if default is not None else [RemoteTool("echo", "Повторить текст")]
        self.fail: dict[str, str] = {}
        self.opened: dict[str, FakeConnection] = {}
        self.attempts: dict[str, int] = {}

    @contextlib.asynccontextmanager
    async def __call__(self, name: str, entry: McpServerEntry) -> AsyncIterator[McpConnection]:
        self.attempts[name] = self.attempts.get(name, 0) + 1
        if name in self.fail:
            raise ConnectionError(self.fail[name])
        conn = FakeConnection(self.tools.get(name, self.default))
        self.opened[name] = conn
        yield conn


# Real, on the official MCP Python SDK (v2 ``mcp.Client``)


class SdkConnection(McpConnection):
    PING_EVERY_S = 15.0

    def __init__(self) -> None:
        self.client: Any = None  # mcp.Client, set once the handshake is done
        self.changed = asyncio.Event()
        self.lost: BaseException | None = None

    async def list_tools(self) -> list[RemoteTool]:
        tools: list[RemoteTool] = []
        cursor: str | None = None
        for _ in range(100):  # a server that pages forever must not hang us
            page = await self.client.list_tools(cursor=cursor, cache_mode="refresh")
            for t in page.tools:
                description = t.description or t.title or t.name
                tools.append(RemoteTool(t.name, description, dict(t.input_schema or {})))
            cursor = page.next_cursor
            if not cursor:
                break
        return tools

    async def call_tool(self, name: str, args: dict[str, Any], timeout_s: float) -> ToolResult:
        try:
            result = await self.client.call_tool(name, args, read_timeout_seconds=timeout_s)
        except Exception as exc:  # MCPError, anyio stream errors, timeouts
            if _is_disconnect(exc):
                self.lost = exc
                self.changed.set()
            raise ToolError(f"MCP: {exc}") from exc
        return to_result(result)

    async def wait_changed(self) -> None:
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.changed.wait(), self.PING_EVERY_S)
            if self.lost:
                raise self.lost
            if self.changed.is_set():
                self.changed.clear()
                return
            # Quiet for a while: make sure the server is still alive.
            await asyncio.wait_for(self.client.send_ping(), 10)

    async def on_message(self, message: Any) -> None:
        from mcp import types

        if isinstance(message, types.ToolListChangedNotification):
            self.changed.set()
        elif isinstance(message, Exception):
            log.debug("MCP transport error: %s", message)
            if _is_disconnect(message):
                self.lost = message
                self.changed.set()


def _is_disconnect(exc: BaseException) -> bool:
    import anyio
    from mcp import MCPError
    from mcp.types import CONNECTION_CLOSED

    if isinstance(exc, MCPError):
        return exc.error.code == CONNECTION_CLOSED and "closed" in exc.error.message.lower()
    return isinstance(
        exc,
        anyio.ClosedResourceError | anyio.BrokenResourceError | anyio.EndOfStream | ConnectionError,
    )


def to_result(result: Any) -> ToolResult:
    """Flatten MCP content blocks into text for the LLM."""
    parts: list[str] = []
    for block in result.content or []:
        kind = getattr(block, "type", "")
        if kind == "text":
            parts.append(block.text)
        elif kind == "image":
            parts.append("[изображение]")
        elif kind == "audio":
            parts.append("[аудио]")
        elif kind == "resource":
            resource = block.resource
            parts.append(getattr(resource, "text", None) or f"[ресурс {resource.uri}]")
        elif kind == "resource_link":
            parts.append(f"[ссылка {block.uri}]")
    structured = result.structured_content
    if not parts and structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False))
    data = {"structured": structured} if structured is not None else {}
    return ToolResult("\n".join(parts) or "Готово", ok=not result.is_error, data=data)


# The first ``npx -y`` / ``uvx`` start downloads the server, which takes a while on Windows.
CONNECT_TIMEOUT_S = 180.0


def transport_for(entry: McpServerEntry, errlog: TextIO | None = None) -> Any:
    """What ``mcp.Client`` connects to: stdio parameters, Streamable HTTP or legacy SSE."""
    from mcp import StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    if entry.url:
        headers = entry.headers or None
        if entry.url.rstrip("/").endswith("/sse"):
            return sse_client(entry.url, headers)
        http = create_mcp_http_client(headers=headers)
        return streamable_http_client(entry.url, http_client=http)
    assert entry.command
    params = StdioServerParameters(
        command=entry.command,
        args=expand_args(entry.args),
        # The full environment, so servers find node, npx and uvx on the user's PATH.
        env={**os.environ, **entry.env},
    )
    return stdio_client(params, errlog) if errlog else params


@contextlib.asynccontextmanager
async def sdk_connector(
    name: str, entry: McpServerEntry, *, errlog: TextIO | None = None
) -> AsyncIterator[McpConnection]:
    """``errlog`` receives a stdio server's stderr (default: ours)."""
    from mcp import Client, types

    conn = SdkConnection()
    client = Client(
        transport_for(entry, errlog),
        message_handler=conn.on_message,
        client_info=types.Implementation(name="solana", version=__version__),
    )
    async with contextlib.AsyncExitStack() as stack:
        async with asyncio.timeout(CONNECT_TIMEOUT_S):
            await stack.enter_async_context(client)
        conn.client = client
        yield conn
