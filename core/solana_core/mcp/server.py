"""Solana as an MCP server: ``solana-core --mcp-server`` serves its own tools over stdio.

Claude Desktop, Claude Code and other MCP clients can then control the PC through Solana.
Only tools that are enabled, built in (not proxied from other MCP servers) and not
``dangerous`` are offered: the client asks its user before each call, but shutdown and
similar actions stay behind a click in Solana itself.
"""

from __future__ import annotations

import logging
from typing import Any

from solana_core import __version__
from solana_core.tools import Tool, ToolContext, ToolError, ToolRegistry

log = logging.getLogger(__name__)


def exposed_tools(tools: ToolRegistry) -> list[Tool]:
    return [t for t in tools.enabled() if t.risk != "dangerous" and t.source != "mcp"]


def build_server(tools: ToolRegistry) -> Any:
    """A low-level ``mcp.server.lowlevel.Server`` over ``tools``."""
    from mcp import types
    from mcp.server.lowlevel import Server

    def find(name: str) -> Tool | None:
        return next((t for t in exposed_tools(tools) if t.name == name), None)

    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=t.name,
                    description=t.description,
                    input_schema=t.parameters,
                    annotations=types.ToolAnnotations(destructive_hint=t.risk == "confirm"),
                )
                for t in exposed_tools(tools)
            ]
        )

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        tool = find(params.name)
        if tool is None:
            text, ok = f"Инструмент недоступен: {params.name}", False
        else:
            try:
                result = await tool.run(params.arguments or {}, ToolContext())
                text, ok = result.content, result.ok
            except ToolError as exc:
                text, ok = str(exc), False
            except Exception as exc:
                log.exception("tool %s failed", params.name)
                text, ok = f"Ошибка инструмента: {exc}", False
        return types.CallToolResult(content=[types.TextContent(text=text)], is_error=not ok)

    return Server(
        "solana",
        version=__version__,
        instructions="Инструменты голосового ассистента Solana для управления этим компьютером.",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def serve_stdio(tools: ToolRegistry) -> None:
    from mcp.server.stdio import stdio_server

    server = build_server(tools)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
