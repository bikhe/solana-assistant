"""OpenAI-compatible Chat Completions: OpenAI, OpenRouter, Ollama, LM Studio, llama.cpp server."""

from __future__ import annotations

import json
import time
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

_FINISH_REASONS: dict[str, Any] = {
    "stop": "end",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
}
_AVAILABLE_TTL_S = 10.0


class OpenAICompatProvider(LLMProvider):
    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        local: bool = False,
        max_tokens: int = 1024,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.local = local
        self.max_tokens = max_tokens
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        self._available: tuple[float, bool] | None = None

    async def available(self) -> bool:
        """Cloud: a key is set. Local: the server answers ``GET /models`` (cached briefly)."""
        if not self.local:
            return bool(self.api_key)
        now = time.monotonic()
        if self._available and now - self._available[0] < _AVAILABLE_TTL_S:
            return self._available[1]
        try:
            response = await self._client.get(
                f"{self.base_url}/models", headers=self._headers(), timeout=2.0
            )
            ok = response.status_code < 500
        except httpx.HTTPError:
            ok = False
        self._available = (now, ok)
        return ok

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return headers

    def build_request(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec], names: ToolNames
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "stream": True,
            # OpenAI's newer models reject max_tokens; most other servers only know it.
            "max_completion_tokens" if self.name == "openai" else "max_tokens": self.max_tokens,
            "messages": [_to_openai(m, names) for m in messages],
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": names.wire(t.name),
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        return body

    async def stream(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[LLMEvent]:
        if not self.local and not self.api_key:
            raise LLMError(f"{self.name}: API key is not set", unreachable=True)
        names = ToolNames(tools)
        calls: dict[int, dict[str, str]] = {}
        stop: Any = "end"
        usage: dict[str, int] = {}
        think = ThinkFilter()
        url = f"{self.base_url}/chat/completions"
        check_url(url, self.api_key)
        body = self.build_request(messages, tools, names)
        finished = False
        try:
            async for sse in post_sse(self._client, url, self._headers(), body):
                if sse.data.strip() == "[DONE]":
                    finished = True
                    break
                data = sse.json()
                if "error" in data:
                    error = data["error"]
                    message = error.get("message") if isinstance(error, dict) else error
                    kind = error.get("type") if isinstance(error, dict) else None
                    raise LLMError(f"{self.name}: {message}", unreachable=kind in RETRYABLE_ERRORS)
                if isinstance(data.get("usage"), dict):
                    usage.update({k: v for k, v in data["usage"].items() if isinstance(v, int)})
                for choice in data.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if text := think.feed(delta.get("content") or ""):
                        yield TextDelta(text)
                    for part in delta.get("tool_calls") or []:
                        slot = calls.setdefault(
                            part.get("index", len(calls)), {"id": "", "name": "", "args": ""}
                        )
                        slot["id"] = part.get("id") or slot["id"]
                        function = part.get("function") or {}
                        slot["name"] += function.get("name") or ""
                        arguments = function.get("arguments")
                        # Ollama may send the whole object instead of a JSON string.
                        if isinstance(arguments, dict):
                            arguments = json.dumps(arguments)
                        slot["args"] += arguments or ""
                    if reason := choice.get("finish_reason"):
                        stop = _FINISH_REASONS.get(reason, "end")
                        finished = True  # some local servers never send [DONE]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise LLMError(f"{self.name}: malformed stream event ({exc!r})") from exc
        if not finished:
            raise LLMError(f"{self.name}: the answer was cut off")
        if text := think.flush():
            yield TextDelta(text)
        for index in sorted(calls):
            slot = calls[index]
            call_id = slot["id"] or f"call_{index}"
            yield ToolCallRequest(
                ToolCall(call_id, names.ours(slot["name"]), parse_arguments(slot["args"]))
            )
        if calls:
            stop = "tool_use"
        yield Done(stop, usage)


def _to_openai(m: Message, names: ToolNames) -> dict[str, Any]:
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {
                    "name": names.wire(c.name),
                    "arguments": json.dumps(c.arguments, ensure_ascii=False),
                },
            }
            for c in m.tool_calls
        ]
        if not m.content:
            out["content"] = None
    return out


class ThinkFilter:
    """Drops ``<think>…</think>`` that reasoning models (Qwen3, DeepSeek-R1) put in content.
    The assistant must not read its reasoning aloud. Works on streamed chunks."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False
        self._started = False

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        out = []
        while self._buffer:
            tag = self.CLOSE if self._inside else self.OPEN
            index = self._buffer.find(tag)
            if index >= 0:
                if not self._inside:
                    out.append(self._buffer[:index])
                self._buffer = self._buffer[index + len(tag) :]
                self._inside = not self._inside
                continue
            # Keep a possible partial tag at the end for the next chunk.
            keep = _partial_suffix(self._buffer, tag)
            if not self._inside:
                out.append(self._buffer[: len(self._buffer) - keep])
            self._buffer = self._buffer[len(self._buffer) - keep :]
            break
        text = "".join(out)
        if not self._started:  # no leading blank lines left over after </think>
            text = text.lstrip()
            self._started = bool(text)
        return text

    def flush(self) -> str:
        rest, self._buffer = ("" if self._inside else self._buffer), ""
        return rest


def _partial_suffix(text: str, tag: str) -> int:
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if text.endswith(tag[:size]):
            return size
    return 0
