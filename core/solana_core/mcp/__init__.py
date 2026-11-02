"""MCP client: keeps MCP servers connected and adapts their tools to ``Tool``."""

from solana_core.mcp.connection import (
    Connector,
    FakeConnection,
    FakeConnector,
    McpConnection,
    RemoteTool,
    sdk_connector,
)
from solana_core.mcp.manager import McpError, McpManager, McpNotFound, tool_prefix

__all__ = [
    "Connector",
    "FakeConnection",
    "FakeConnector",
    "McpConnection",
    "McpError",
    "McpManager",
    "McpNotFound",
    "RemoteTool",
    "sdk_connector",
    "tool_prefix",
]
