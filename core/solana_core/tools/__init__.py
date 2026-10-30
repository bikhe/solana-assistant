"""Tools the assistant can call. MCP and skill tools are adapted to the same ``Tool`` shape."""

from solana_core.tools.base import Tool, ToolContext, ToolError, ToolResult
from solana_core.tools.registry import ToolRegistry

__all__ = ["Tool", "ToolContext", "ToolError", "ToolRegistry", "ToolResult"]
