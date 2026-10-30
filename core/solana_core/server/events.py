"""Fan-out of core -> app notifications to every connected client."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from pydantic import BaseModel

from solana_core.protocol import EVENTS


def encode_event(name: str, params: BaseModel) -> str:
    expected = EVENTS.get(name)
    if expected is None:
        raise ValueError(f"{name} is not an event in protocol/ipc.schema.json")
    if not isinstance(params, expected):
        raise TypeError(f"event {name} expects {expected.__name__}, got {type(params).__name__}")
    message: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": name,
        "params": params.model_dump(mode="json", exclude_none=True),
    }
    return json.dumps(message, ensure_ascii=False)


class EventBus:
    def __init__(self, max_queue: int = 1000) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._max_queue = max_queue

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(self._max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subscribers.discard(queue)

    def emit(self, name: str, params: BaseModel) -> None:
        """Validate and queue an event for every subscriber. A full queue drops the event."""
        text = encode_event(name, params)
        for queue in self._subscribers:
            if not queue.full():
                queue.put_nowait(text)
