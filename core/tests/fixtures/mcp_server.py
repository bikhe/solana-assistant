"""A tiny MCP server for tests: ``python mcp_server.py [stdio | http PORT | sse PORT]``.

Tools: ``echo``, ``add``, ``list_dir`` (a small filesystem-like tool), ``fail`` (returns a
tool error) and ``crash`` (kills the process, to test reconnection).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

server = MCPServer("solana-test")


@server.tool()
def echo(text: str) -> str:
    """Return the text unchanged."""
    return text


@server.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@server.tool()
def list_dir(path: str) -> str:
    """List the names in a folder, one per line."""
    return "\n".join(sorted(p.name for p in Path(path).iterdir()))


@server.tool()
def fail(reason: str) -> str:
    """Always fail with the given reason."""
    raise ToolError(reason)


@server.tool()
def crash() -> str:
    """Exit the server process at once."""
    os._exit(3)


def main(argv: list[str]) -> None:
    mode = argv[1] if len(argv) > 1 else "stdio"
    if mode == "stdio":
        server.run()
    elif mode == "http":
        server.run("streamable-http", host="127.0.0.1", port=int(argv[2]))
    elif mode == "sse":
        server.run("sse", host="127.0.0.1", port=int(argv[2]))
    else:
        raise SystemExit(f"unknown mode: {mode}")


if __name__ == "__main__":
    main(sys.argv)
