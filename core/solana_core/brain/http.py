"""Shared HTTP plumbing for cloud and local providers: SSE streaming and tool name mapping."""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from solana_core.brain.base import ToolSpec
from solana_core.brain.errors import LLMError

# Connect fast so "no network" falls back to the local model quickly; reading can be slow.
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=5.0)
# Worth retrying on another provider: overload, rate limit, server errors.
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504, 529}
# Upper bound for a whole answer: pings keep the read timeout alive forever otherwise.
MAX_STREAM_S = 180.0
_WIRE_NAME = re.compile(r"[^a-zA-Z0-9_-]")


@dataclass(frozen=True, slots=True)
class SseEvent:
    event: str
    data: str

    def json(self) -> dict[str, Any]:
        value = json.loads(self.data)
        if not isinstance(value, dict):
            raise ValueError("SSE data is not a JSON object")
        return value


async def post_sse(
    client: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, Any]
) -> AsyncIterator[SseEvent]:
    """POST ``body`` and yield server-sent events. Raises ``LLMError`` on failure."""
    try:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code >= 400:
                text = (await response.aread()).decode("utf-8", "replace")
                raise LLMError(
                    f"HTTP {response.status_code}: {_error_text(text)}",
                    unreachable=response.status_code in _RETRYABLE_STATUS,
                    status=response.status_code,
                )
            deadline = time.monotonic() + MAX_STREAM_S
            async for event in parse_sse(response.aiter_lines()):
                if time.monotonic() > deadline:
                    raise LLMError(f"no complete answer in {MAX_STREAM_S:.0f} s")
                yield event
    except httpx.TransportError as exc:
        # Connect errors mean nothing was sent yet; read errors may cut a stream in half,
        # but the dialog only retries when no text reached the user (see router).
        raise LLMError(f"{type(exc).__name__}: {exc}", unreachable=True) from exc


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[SseEvent]:
    """Minimal SSE parser: ``event:`` and ``data:`` fields, events split by blank lines."""
    event, data = "message", list[str]()
    async for raw in lines:
        line = raw.rstrip("\r")
        if not line:
            if data:
                yield SseEvent(event, "\n".join(data))
            event, data = "message", []
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "event":
            event = value
        elif name == "data":
            data.append(value)
    if data:
        yield SseEvent(event, "\n".join(data))


def _error_text(body: str) -> str:
    try:
        payload = json.loads(body)
    except ValueError:
        return body[:300]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])
        if isinstance(error, str):
            return error
    return body[:300]


class ToolNames:
    """APIs allow only ``[a-zA-Z0-9_-]`` in tool names; ours use dots (``pc.volume_set``)."""

    def __init__(self, tools: Sequence[ToolSpec]) -> None:
        self._to_wire: dict[str, str] = {}
        self._to_ours: dict[str, str] = {}
        for tool in tools:
            wire = base = self.base(tool.name)
            n = 2
            while wire in self._to_ours:  # "a.b" and "a/b" would collide
                suffix = f"_{n}"
                wire, n = base[: 64 - len(suffix)] + suffix, n + 1
            self._to_wire[tool.name] = wire
            self._to_ours[wire] = tool.name

    @staticmethod
    def base(name: str) -> str:
        return _WIRE_NAME.sub("_", name.replace(".", "__"))[:64]

    def wire(self, name: str) -> str:
        return self._to_wire.get(name) or self.base(name)

    def ours(self, wire_name: str) -> str:
        return self._to_ours.get(wire_name, wire_name)


def check_url(url: str, key: str | None) -> None:
    """Never send an API key in clear text over the network; loopback servers are fine."""
    parsed = httpx.URL(url)
    if key and parsed.scheme != "https" and parsed.host not in _LOOPBACK:
        raise LLMError(f"refusing to send an API key over {parsed.scheme}:// to {parsed.host}")


_LOOPBACK = {"127.0.0.1", "localhost", "::1"}

# Provider error types inside an SSE stream that are worth retrying elsewhere.
RETRYABLE_ERRORS = {"overloaded_error", "rate_limit_error", "api_error", "server_error"}


def parse_arguments(raw: str) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string; models sometimes send nothing or junk."""
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {"_raw": raw}
    return value if isinstance(value, dict) else {"_value": value}
