"""Real third-party MCP servers that need no account or key: the presets in the MCP tab.

They download packages and use the network, so they run only on CI (``CI`` is set by
GitHub Actions) or with ``SOLANA_MCP_LIVE=1``. Outages on the far side skip, not fail.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import httpx2
import pytest

from solana_core.config.models import McpServerEntry
from solana_core.mcp import sdk_connector
from solana_core.mcp.manager import describe_error

pytestmark = pytest.mark.skipif(
    not (os.environ.get("CI") or os.environ.get("SOLANA_MCP_LIVE")),
    reason="live MCP servers run on CI or with SOLANA_MCP_LIVE=1",
)


def need(command: str) -> None:
    if shutil.which(command) is None:
        pytest.skip(f"{command} is not installed")


async def test_filesystem_server(tmp_path: Path) -> None:
    """@modelcontextprotocol/server-filesystem: the server named in WP7's done-criterion."""
    need("npx")
    (tmp_path / "список покупок.txt").write_text("молоко\nхлеб", encoding="utf-8")
    entry = McpServerEntry(
        command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", str(tmp_path)]
    )
    async with sdk_connector("filesystem", entry) as conn:
        names = {t.name for t in await conn.list_tools()}
        assert {"list_directory", "read_text_file"} <= names
        listing = await conn.call_tool("list_directory", {"path": str(tmp_path)}, 60)
        assert listing.ok and "список покупок.txt" in listing.content
        text = await conn.call_tool(
            "read_text_file", {"path": str(tmp_path / "список покупок.txt")}, 60
        )
        assert "молоко" in text.content


@pytest.mark.parametrize(
    ("package", "tool"), [("mcp-server-time", "get_current_time"), ("mcp-server-fetch", "fetch")]
)
async def test_uvx_servers(package: str, tool: str) -> None:
    need("uvx")
    async with sdk_connector(package, McpServerEntry(command="uvx", args=[package])) as conn:
        assert tool in {t.name for t in await conn.list_tools()}


async def test_time_server_answers() -> None:
    need("uvx")
    entry = McpServerEntry(command="uvx", args=["mcp-server-time"])
    async with sdk_connector("time", entry) as conn:
        result = await conn.call_tool("get_current_time", {"timezone": "Europe/Moscow"}, 60)
        assert result.ok and "Europe/Moscow" in result.content


@pytest.mark.parametrize(
    "url",
    [
        "https://mcp.deepwiki.com/mcp",
        "https://mcp.context7.com/mcp",
        "https://learn.microsoft.com/api/mcp",
    ],
)
async def test_remote_servers_without_auth(url: str) -> None:
    try:
        async with sdk_connector("remote", McpServerEntry(url=url)) as conn:
            names = {t.name for t in await conn.list_tools()}
    except Exception as exc:
        reason = describe_error(exc)
        leaf: BaseException = exc
        while isinstance(leaf, BaseExceptionGroup) and leaf.exceptions:
            leaf = leaf.exceptions[0]
        if isinstance(leaf, httpx2.TransportError | TimeoutError):
            pytest.skip(f"{url} is unreachable: {reason}")
        raise AssertionError(f"{url}: {reason}") from exc
    assert names, f"{url} has no tools"
