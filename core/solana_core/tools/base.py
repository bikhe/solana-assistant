"""Tool contract shared by built-in, PC, MCP and skill tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from solana_core.protocol import Language, Risk

ToolSource = Literal["builtin", "mcp", "skill"]


class ToolError(Exception):
    """Expected failure the assistant can tell the user about, e.g. "app not found"."""


@dataclass(slots=True)
class ToolContext:
    """What a tool may know about the current call."""

    language: Language = "ru"
    turn_id: str | None = None
    call_id: str | None = None


@dataclass(slots=True)
class ToolResult:
    """Tool output. ``content`` goes back to the LLM as data, never as instructions."""

    content: str
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """One action the assistant can take.

    ``parameters`` is a JSON Schema object describing the arguments of ``run``.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    risk: ClassVar[Risk] = "safe"
    source: ClassVar[ToolSource] = "builtin"

    @abstractmethod
    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


class FakeTool(Tool):
    """Echoes its ``text`` argument and remembers every call."""

    name = "fake.echo"
    description = "Возвращает переданный текст. Только для тестов."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        self.calls.append(args)
        return ToolResult(str(args.get("text", "")))
