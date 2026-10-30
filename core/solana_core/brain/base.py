"""LLM contract: chat messages, streaming events and tool calls."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None  # set when role == "tool"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """What the LLM sees about a tool."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    call: ToolCall


@dataclass(frozen=True, slots=True)
class Done:
    stop_reason: Literal["end", "tool_use", "max_tokens", "error"] = "end"
    usage: dict[str, int] = field(default_factory=dict)


LLMEvent = TextDelta | ToolCallRequest | Done


class LLMProvider(ABC):
    name: str
    local: bool = False

    @abstractmethod
    def stream(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[LLMEvent]:
        """Stream the answer. Ends with exactly one ``Done``."""

    async def available(self) -> bool:
        """Cheap check that the provider can be used now (key set, server reachable)."""
        return True


class FakeLLM(LLMProvider):
    """Plays scripted turns. Each turn is a list of events; ``Done`` is appended if missing."""

    name = "fake"
    local = True

    def __init__(self, turns: Sequence[Sequence[LLMEvent]] | None = None) -> None:
        self._turns = [list(t) for t in (turns or [])]
        self.calls: list[list[Message]] = []

    async def stream(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[LLMEvent]:
        self.calls.append(list(messages))
        if self._turns:
            events = self._turns.pop(0)
        else:
            last = messages[-1].content if messages else ""
            events = [TextDelta(f"Вы сказали: {last}")]
        for event in events:
            yield event
        if not events or not isinstance(events[-1], Done):
            yield Done("tool_use" if any(isinstance(e, ToolCallRequest) for e in events) else "end")
