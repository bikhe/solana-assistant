"""In-memory registry of tools: built-in and PC tools, MCP (WP7) and skill (WP8) tools."""

from __future__ import annotations

from collections.abc import Iterable

from solana_core.brain.base import ToolSpec
from solana_core.protocol.generated import ToolInfo
from solana_core.tools.base import Tool


class ToolRegistry:
    """Tools by name, each enabled or disabled.

    The disabled set is the user's choice and outlives registration: a tool disabled in
    settings stays disabled when its MCP server connects later or reconnects.
    """

    def __init__(self, disabled: Iterable[str] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        self._disabled: set[str] = set(disabled)

    def register(self, tool: Tool, *, replace: bool = False) -> None:
        if tool.name in self._tools and not replace:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def unregister_prefix(self, prefix: str) -> list[str]:
        """Remove every tool whose name starts with ``prefix`` (e.g. ``"mcp.files."``)."""
        names = [name for name in self._tools if name.startswith(prefix)]
        for name in names:
            del self._tools[name]
        return names

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def get(self, name: str) -> Tool | None:
        """Return an enabled tool by name."""
        if name in self._disabled:
            return None
        return self._tools.get(name)

    def set_enabled(self, name: str, enabled: bool) -> None:
        if name not in self._tools:
            raise KeyError(name)
        if enabled:
            self._disabled.discard(name)
        else:
            self._disabled.add(name)

    def is_enabled(self, name: str) -> bool:
        return name in self._tools and name not in self._disabled

    def set_disabled(self, names: Iterable[str]) -> None:
        """Replace the whole disabled set, e.g. after ``tools.disabled`` changed in settings."""
        self._disabled = set(names)

    def disabled_names(self) -> list[str]:
        """Everything the user disabled, registered or not; this is what settings store."""
        return sorted(self._disabled)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def enabled(self) -> list[Tool]:
        return [t for name, t in self._tools.items() if name not in self._disabled]

    def specs(self) -> list[ToolSpec]:
        """Schemas of enabled tools, ready for ``LLMProvider.stream``."""
        return [ToolSpec(t.name, t.description, t.parameters) for t in self.enabled()]

    def info(self, name: str) -> ToolInfo:
        tool = self._tools[name]
        return ToolInfo(
            name=tool.name,
            description=tool.description,
            risk=tool.risk,
            source=tool.source,
            enabled=self.is_enabled(name),
        )

    def infos(self) -> list[ToolInfo]:
        return [self.info(name) for name in self._tools]
