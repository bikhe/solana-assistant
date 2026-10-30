"""In-memory registry of tools. WP3 extends it; WP7 and WP8 add MCP and skill tools."""

from __future__ import annotations

from solana_core.brain.base import ToolSpec
from solana_core.protocol.generated import ToolInfo
from solana_core.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._disabled: set[str] = set()

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
        self._disabled.discard(name)

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
