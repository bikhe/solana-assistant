"""Server entries in the ``mcpServers`` format of Claude Desktop.

Importing a Claude Desktop config happens in the app: it reads the file and calls ``mcp.add``.
"""

from __future__ import annotations

import re
from pathlib import Path

from solana_core.config.models import McpServerEntry
from solana_core.protocol.generated import McpServerConfig

# Server names become part of tool names (``mcp.<server>.<tool>``), so keep them plain.
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class McpConfigError(ValueError):
    """A server entry or a config file that cannot be used."""


def check_name(name: str) -> str:
    if not _NAME.match(name):
        raise McpConfigError(
            f"Имя сервера может содержать только латиницу, цифры, - и _ (до 40 символов): {name!r}"
        )
    return name


def entry_from_config(config: McpServerConfig, *, enabled: bool = True) -> McpServerEntry:
    entry = McpServerEntry(
        command=config.command,
        args=list(config.args or []),
        env=dict(config.env or {}),
        url=config.url,
        headers=dict(config.headers or {}),
        enabled=enabled,
    )
    check_entry(entry)
    return entry


def config_from_entry(entry: McpServerEntry) -> McpServerConfig:
    if entry.url:
        return McpServerConfig(url=entry.url, headers=entry.headers or None)
    return McpServerConfig(command=entry.command, args=entry.args or None, env=entry.env or None)


def check_entry(entry: McpServerEntry) -> None:
    if bool(entry.command) == bool(entry.url):
        raise McpConfigError("Укажите либо команду запуска, либо URL сервера")
    if entry.url and not entry.url.startswith(("http://", "https://")):
        raise McpConfigError(f"URL сервера должен начинаться с http:// или https://: {entry.url}")


def expand_args(args: list[str]) -> list[str]:
    """``~`` in stdio arguments means the home folder, as most users expect from a shell."""
    home = str(Path.home())
    out = []
    for arg in args:
        if arg == "~":
            out.append(home)
        elif arg.startswith(("~/", "~\\")):
            out.append(home + arg[1:])
        else:
            out.append(arg)
    return out
