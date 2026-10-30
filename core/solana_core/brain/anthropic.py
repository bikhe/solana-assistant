"""Claude through the Anthropic Messages API (streaming, tool use), over plain httpx."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from solana_core.brain.base import (
    Done,
    LLMEvent,
    LLMProvider,
    Message,
    TextDelta,
    ToolCall,
    ToolCallRequest,
    ToolSpec,
)
from solana_core.brain.errors import LLMError
from solana_core.brain.http import (
    DEFAULT_TIMEOUT,
    RETRYABLE_ERRORS,
    ToolNames,
    check_url,
    parse_arguments,
    post_sse,
)

API_VERSION = "2023-06-01"
DEFAULT_BASE_URL = "https://api.anthropic.com"
_STOP_REASONS: dict[str, Any] = {
    "end_turn": "end",
    "stop_sequence": "end",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
}


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    local = False

    def __init__(
        self,
        api_key: str | None,
        model: str,
        *,
        base_url: str | None = None,
        max_tokens: int = 1024,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.max_tokens = max_tokens
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)

    async def available(self) -> bool:
        return bool(self.api_key)

    async def aclose(self) -> None:
        await self._client.aclose()

    def build_request(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec], names: ToolNames
    ) -> dict[str, Any]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "stream": True,
            "messages": _to_anthropic(messages, names),
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {
                    "name": names.wire(t.name),
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]
        return body

    async def stream(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[LLMEvent]:
        if not self.api_key:
            raise LLMError("Anthropic API key is not set", unreachable=True)
        names = ToolNames(tools)
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        url = f"{self.base_url}/v1/messages"
        check_url(url, self.api_key)
        blocks: dict[int, dict[str, Any]] = {}
        stop: Any = "end"
        usage: dict[str, int] = {}
        finished = False
        body = self.build_request(messages, tools, names)
        try:
            async for sse in post_sse(self._client, url, headers, body):
                if sse.event == "ping":
                    continue
                data = sse.json()
                kind = data.get("type", sse.event)
                if kind == "message_start":
                    usage.update(_ints(data.get("message", {}).get("usage", {})))
                elif kind == "content_block_start":
                    block = dict(data["content_block"])
                    block["_json"] = ""
                    blocks[data["index"]] = block
                elif kind == "content_block_delta":
                    delta = data["delta"]
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield TextDelta(delta["text"])
                    elif delta.get("type") == "input_json_delta":
                        blocks[data["index"]]["_json"] += delta.get("partial_json", "")
                elif kind == "content_block_stop":
                    block = blocks.pop(data["index"], {})
                    if block.get("type") == "tool_use":
                        raw = block["_json"]
                        args = parse_arguments(raw) if raw else block.get("input", {})
                        yield ToolCallRequest(
                            ToolCall(block["id"], names.ours(block["name"]), args)
                        )
                elif kind == "message_delta":
                    reason = data.get("delta", {}).get("stop_reason")
                    stop = _STOP_REASONS.get(reason or "", "end")
                    usage.update(_ints(data.get("usage", {})))
                elif kind == "error":
                    error = data.get("error", {})
                    raise LLMError(
                        f"Anthropic: {error.get('message', 'unknown error')}",
                        unreachable=error.get("type") in RETRYABLE_ERRORS,
                    )
                elif kind == "message_stop":
                    finished = True
                    break
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMError(f"Anthropic: malformed stream event ({exc!r})") from exc
        if not finished:
            raise LLMError("Anthropic: the answer was cut off")
        yield Done(stop, usage)


def _to_anthropic(messages: Sequence[Message], names: ToolNames) -> list[dict[str, Any]]:
    """Our flat history to Anthropic turns. Tool results become ``user`` turns, and
    consecutive turns of the same role merge, since the API wants them alternating."""
    out: list[dict[str, Any]] = []

    def add(role: str, blocks: list[dict[str, Any]]) -> None:
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})

    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            add(
                "user",
                [{"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}],
            )
        elif m.role == "assistant":
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            blocks.extend(
                {"type": "tool_use", "id": c.id, "name": names.wire(c.name), "input": c.arguments}
                for c in m.tool_calls
            )
            if blocks:
                add("assistant", blocks)
        else:
            add("user", [{"type": "text", "text": m.content}])
    return out


def _ints(raw: dict[str, Any]) -> dict[str, int]:
    return {k: v for k, v in raw.items() if isinstance(v, int)}
