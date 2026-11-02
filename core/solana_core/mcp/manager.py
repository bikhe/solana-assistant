"""Keeps the configured MCP servers connected and their tools in the ``ToolRegistry``."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal

from solana_core.config import ConfigStore
from solana_core.config.models import McpServerEntry, McpSettings
from solana_core.mcp.config import check_name, config_from_entry, entry_from_config
from solana_core.mcp.connection import Connector, McpConnection, RemoteTool, sdk_connector
from solana_core.protocol.generated import McpServerConfig, McpServerInfo
from solana_core.tools import Tool, ToolContext, ToolRegistry, ToolResult

log = logging.getLogger(__name__)

PREFIX = "mcp."

McpServerStatus = Literal["connected", "connecting", "disconnected", "error"]


def tool_prefix(server: str) -> str:
    return f"{PREFIX}{server}."


class McpTool(Tool):
    """Adapter from a remote MCP tool to ``Tool``, named ``mcp.<server>.<tool>``."""

    source = "mcp"

    def __init__(
        self, server: str, remote: RemoteTool, conn: McpConnection, timeout_s: float
    ) -> None:
        schema = remote.input_schema if remote.input_schema.get("type") == "object" else {}
        self.name = tool_prefix(server) + remote.name  # type: ignore[misc]
        self.description = f"[MCP {server}] {remote.description}"[:1024]  # type: ignore[misc]
        self.parameters = {"type": "object", "properties": {}, **schema}  # type: ignore[misc]
        self.risk = "confirm"  # type: ignore[misc]  # a server's own hints are not trusted
        self.remote_name = remote.name
        self.conn = conn
        self.timeout_s = timeout_s

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return await self.conn.call_tool(self.remote_name, args, self.timeout_s)


class McpError(Exception):
    """A request the user can fix, e.g. a duplicate or unknown server name."""


class McpNotFound(McpError):
    pass


@dataclass(slots=True)
class _Server:
    name: str
    entry: McpServerEntry
    status: McpServerStatus = "disconnected"
    error: str | None = None
    task: asyncio.Task[None] | None = None


class McpManager:
    """Owns one supervisor task per enabled server.

    A supervisor connects, registers the server's tools as ``mcp.<server>.<tool>``,
    re-reads them when the server says they changed, and reconnects with backoff when
    the server crashes. The settings file (``mcp.servers``) is the source of truth.
    """

    def __init__(
        self,
        config: ConfigStore,
        tools: ToolRegistry,
        connector: Connector = sdk_connector,
        *,
        call_timeout_s: float = 60.0,
        retry_s: float = 1.0,
        max_retry_s: float = 60.0,
    ) -> None:
        self._config = config
        self._tools = tools
        self._connector = connector
        self._call_timeout_s = call_timeout_s
        self._retry_s = retry_s
        self._max_retry_s = max_retry_s
        self._servers: dict[str, _Server] = {}
        self._started = False
        self._tick = asyncio.Event()  # replaced on every status change

    # Lifecycle

    def start(self) -> None:
        """Connect every enabled server. Idempotent; needs a running event loop."""
        if not self._started:
            self._started = True
            self.sync()

    def sync(self) -> None:
        """Make the running servers match the settings, e.g. after ``settings.set``."""
        if not self._started:
            return
        wanted = self._config.settings.mcp.servers
        for name in list(self._servers):
            if name not in wanted:
                self._stop(self._servers.pop(name))
        for name, entry in wanted.items():
            srv = self._servers.get(name)
            if srv is None:
                srv = self._servers[name] = _Server(name, entry)
            elif srv.entry != entry:
                self._stop(srv)
                srv.entry = entry
            if entry.enabled and srv.task is None:
                srv.task = asyncio.create_task(self._supervise(srv), name=f"mcp:{name}")
            elif not entry.enabled:
                self._stop(srv)

    async def close(self) -> None:
        tasks = [srv.task for srv in self._servers.values() if srv.task]
        for srv in self._servers.values():
            self._stop(srv)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._started = False

    def _stop(self, srv: _Server) -> None:
        if srv.task is not None:
            srv.task.cancel()
            srv.task = None
        self._tools.unregister_prefix(tool_prefix(srv.name))
        self._set(srv, "disconnected")

    async def _supervise(self, srv: _Server) -> None:
        delay = self._retry_s
        prefix = tool_prefix(srv.name)
        while True:
            self._set(srv, "connecting")
            try:
                async with self._connector(srv.name, srv.entry) as conn:
                    while True:
                        self._register(srv.name, await conn.list_tools(), conn)
                        self._set(srv, "connected")
                        delay = self._retry_s
                        await conn.wait_changed()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._set(srv, "error", describe_error(exc))
                log.warning("MCP server %s: %s", srv.name, srv.error)
            finally:
                self._tools.unregister_prefix(prefix)
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._max_retry_s)

    def _register(self, server: str, remote: list[RemoteTool], conn: McpConnection) -> None:
        self._tools.unregister_prefix(tool_prefix(server))
        for item in remote:
            tool = McpTool(server, item, conn, self._call_timeout_s)
            self._tools.register(tool, replace=True)

    # Requests from the app

    def infos(self) -> list[McpServerInfo]:
        return [self.info(name) for name in self._config.settings.mcp.servers]

    def info(self, name: str) -> McpServerInfo:
        entry = self._config.settings.mcp.servers.get(name)
        if entry is None:
            raise McpNotFound(f"Unknown MCP server: {name}")
        srv = self._servers.get(name)
        prefix = tool_prefix(name)
        return McpServerInfo(
            name=name,
            config=config_from_entry(entry),
            enabled=entry.enabled,
            status=srv.status if srv else "disconnected",
            error=srv.error if srv else None,
            tools=[
                self._tools.info(t.name) for t in self._tools.all() if t.name.startswith(prefix)
            ],
        )

    def add(self, name: str, config: McpServerConfig) -> McpServerInfo:
        check_name(name)
        servers = dict(self._config.settings.mcp.servers)
        if name in servers:
            raise McpError(f"MCP server already exists: {name}")
        servers[name] = entry_from_config(config)
        self._save(servers)
        return self.info(name)

    def remove(self, name: str) -> bool:
        servers = dict(self._config.settings.mcp.servers)
        if servers.pop(name, None) is None:
            return False
        self._save(servers)
        return True

    def set_enabled(self, name: str, enabled: bool) -> McpServerInfo:
        servers = dict(self._config.settings.mcp.servers)
        entry = servers.get(name)
        if entry is None:
            raise McpNotFound(f"Unknown MCP server: {name}")
        servers[name] = entry.model_copy(update={"enabled": enabled})
        self._save(servers)
        return self.info(name)

    def _save(self, servers: dict[str, McpServerEntry]) -> None:
        settings = self._config.settings
        self._config.save(settings.model_copy(update={"mcp": McpSettings(servers=servers)}))
        self.sync()

    def _set(self, srv: _Server, status: McpServerStatus, error: str | None = None) -> None:
        srv.status, srv.error = status, error
        self._tick.set()
        self._tick = asyncio.Event()

    async def wait_for(self, name: str, *statuses: McpServerStatus, timeout_s: float = 10) -> None:
        """Wait until a server reaches one of ``statuses``; used by tests."""
        async with asyncio.timeout(timeout_s):
            while (srv := self._servers.get(name)) is None or srv.status not in statuses:
                await self._tick.wait()


def describe_error(exc: BaseException) -> str:
    """A short, human-readable reason, digging through anyio exception groups."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    if isinstance(exc, FileNotFoundError):
        missing = exc.filename or str(exc)
        hint = _INSTALL_HINTS.get(str(missing).rsplit("/", 1)[-1].lower().removesuffix(".cmd"))
        return f"Команда не найдена: {missing}." + (f" {hint}" if hint else "")
    if isinstance(exc, TimeoutError):
        return "Сервер не ответил вовремя"
    import httpx2

    if isinstance(exc, httpx2.HTTPStatusError):
        exc_code = exc.response.status_code
        if exc_code in (401, 403):
            return f"Сервер требует авторизацию (HTTP {exc_code})"
        return f"Сервер ответил ошибкой HTTP {exc_code}"
    if isinstance(exc, httpx2.HTTPError):
        return f"Нет связи с сервером: {exc}"
    text = str(exc) or type(exc).__name__
    return text[:300]


_INSTALL_HINTS = {
    "npx": "Установите Node.js: https://nodejs.org",
    "node": "Установите Node.js: https://nodejs.org",
    "uvx": "Установите uv: https://docs.astral.sh/uv/",
    "uv": "Установите uv: https://docs.astral.sh/uv/",
    "docker": "Установите Docker: https://docs.docker.com/get-docker/",
}
