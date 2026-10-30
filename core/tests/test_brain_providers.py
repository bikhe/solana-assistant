"""Anthropic and OpenAI-compatible providers against recorded streams."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from solana_core.brain.anthropic import AnthropicProvider
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
from solana_core.brain.http import ToolNames, parse_sse
from solana_core.brain.openai_compat import OpenAICompatProvider, ThinkFilter
from tests.llm_replay import Replay

APP_OPEN = ToolSpec(
    "pc.app_open",
    "Открыть приложение",
    {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
)
VOLUME = ToolSpec(
    "pc.volume_set",
    "Громкость",
    {"type": "object", "properties": {"level": {"type": "integer"}}},
)
MEDIA = ToolSpec("pc.media", "Медиа", {"type": "object", "properties": {}})


async def collect(
    provider: LLMProvider, messages: list[Message], tools: list[ToolSpec]
) -> list[LLMEvent]:
    return [e async for e in provider.stream(messages, tools)]


async def test_anthropic_streams_text_and_usage() -> None:
    replay = Replay("anthropic_text.sse")
    llm = AnthropicProvider("sk-test", "claude-sonnet-5-5", client=replay.client())
    events = await collect(llm, [Message("system", "Ты Солана."), Message("user", "привет")], [])
    assert events[:2] == [TextDelta("Привет! "), TextDelta("Чем помочь?")]
    assert events[-1] == Done("end", {"input_tokens": 412, "output_tokens": 9})

    request = replay.requests[0]
    assert request.url == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-test"
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = replay.bodies()[0]
    assert body["system"] == "Ты Солана."
    assert body["stream"] is True
    assert body["messages"] == [{"role": "user", "content": [{"type": "text", "text": "привет"}]}]


async def test_anthropic_tool_use_with_partial_json() -> None:
    replay = Replay("anthropic_tool.sse")
    llm = AnthropicProvider("sk-test", "claude-sonnet-5-5", client=replay.client())
    events = await collect(llm, [Message("user", "открой браузер")], [APP_OPEN])
    assert events == [
        TextDelta("Сейчас открою."),
        ToolCallRequest(ToolCall("toolu_01A", "pc.app_open", {"name": "браузер"})),
        Done("tool_use", {"input_tokens": 655, "output_tokens": 48}),
    ]
    tools = replay.bodies()[0]["tools"]
    assert tools[0]["name"] == "pc__app_open"
    assert tools[0]["input_schema"] == APP_OPEN.parameters


def test_anthropic_history_merges_tool_results() -> None:
    llm = AnthropicProvider("k", "m")
    calls = (ToolCall("a", "pc.app_open", {"name": "x"}), ToolCall("b", "pc.media", {}))
    history = [
        Message("system", "s"),
        Message("user", "сделай две вещи"),
        Message("assistant", "", calls),
        Message("tool", "ok-a", tool_call_id="a"),
        Message("tool", "ok-b", tool_call_id="b"),
    ]
    body = llm.build_request(history, [APP_OPEN, MEDIA], ToolNames([APP_OPEN, MEDIA]))
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert body["messages"][1]["content"][0] == {
        "type": "tool_use",
        "id": "a",
        "name": "pc__app_open",
        "input": {"name": "x"},
    }
    assert [b["tool_use_id"] for b in body["messages"][2]["content"]] == ["a", "b"]


async def test_openai_fragmented_tool_call_and_text() -> None:
    replay = Replay("openai_tool.sse", "openai_text.sse")
    llm = OpenAICompatProvider(
        "openai", "https://api.openai.com/v1", "gpt-5", api_key="sk-o", client=replay.client()
    )
    first = await collect(llm, [Message("user", "громкость тридцать")], [VOLUME])
    assert first == [
        ToolCallRequest(ToolCall("call_abc", "pc.volume_set", {"level": 30})),
        Done("tool_use", {}),
    ]
    history = [
        Message("user", "громкость тридцать"),
        Message("assistant", "", (ToolCall("call_abc", "pc.volume_set", {"level": 30}),)),
        Message("tool", "ok", tool_call_id="call_abc"),
    ]
    second = await collect(llm, history, [VOLUME])
    assert (
        "".join(e.text for e in second if isinstance(e, TextDelta))
        == "Поставила громкость тридцать."
    )
    assert second[-1] == Done(
        "end", {"prompt_tokens": 120, "completion_tokens": 6, "total_tokens": 126}
    )

    assert replay.requests[0].headers["authorization"] == "Bearer sk-o"
    sent = replay.bodies()[1]["messages"]
    assert sent[1]["content"] is None
    assert sent[1]["tool_calls"][0]["function"] == {
        "name": "pc__volume_set",
        "arguments": '{"level": 30}',
    }
    assert sent[2] == {"role": "tool", "tool_call_id": "call_abc", "content": "ok"}


async def test_ollama_qwen3_hides_thinking() -> None:
    replay = Replay("ollama_qwen3_tool.sse")
    llm = OpenAICompatProvider(
        "ollama", "http://127.0.0.1:11434/v1", "qwen3:8b", local=True, client=replay.client()
    )
    events = await collect(llm, [Message("user", "поставь на паузу")], [MEDIA])
    assert events == [
        ToolCallRequest(ToolCall("call_k2v1", "pc.media", {"action": "pause"})),
        Done("tool_use", {}),
    ]
    assert "authorization" not in replay.requests[0].headers


def test_think_filter_across_chunks() -> None:
    f = ThinkFilter()
    out = "".join(f.feed(c) for c in ["<thi", "nk>секрет</th", "ink>\n\nОтвет", " готов <", "b>"])
    assert out + f.flush() == "Ответ готов <b>"


async def test_parse_sse_multiline_and_comments() -> None:
    async def lines() -> AsyncIterator[str]:
        for line in [": comment", "event: a", "data: 1", "data: 2", "", "data: x"]:
            yield line

    events = [e async for e in parse_sse(lines())]
    assert [(e.event, e.data) for e in events] == [("a", "1\n2"), ("message", "x")]


async def test_http_errors() -> None:
    body = {
        "type": "error",
        "error": {"type": "authentication_error", "message": "invalid x-api-key"},
    }
    replay = Replay().then(httpx.Response(401, json=body))
    llm = AnthropicProvider("bad", "m", client=replay.client())
    with pytest.raises(LLMError) as info:
        await collect(llm, [Message("user", "hi")], [])
    assert info.value.status == 401
    assert not info.value.unreachable
    assert "invalid x-api-key" in str(info.value)

    replay = Replay().then(httpx.Response(529, json={"error": {"message": "Overloaded"}}))
    llm = AnthropicProvider("k", "m", client=replay.client())
    with pytest.raises(LLMError) as info:
        await collect(llm, [Message("user", "hi")], [])
    assert info.value.unreachable


async def test_connection_refused_is_unreachable() -> None:
    replay = Replay().then(httpx.ConnectError("Connection refused"))
    llm = OpenAICompatProvider(
        "ollama", "http://127.0.0.1:11434/v1", "qwen3:8b", local=True, client=replay.client()
    )
    with pytest.raises(LLMError) as info:
        await collect(llm, [Message("user", "hi")], [])
    assert info.value.unreachable


async def test_missing_key() -> None:
    assert not await AnthropicProvider(None, "m").available()
    with pytest.raises(LLMError):
        await collect(AnthropicProvider(None, "m"), [Message("user", "hi")], [])
    cloud = OpenAICompatProvider("openai", "https://api.openai.com/v1", "gpt-5")
    assert not await cloud.available()


async def test_local_available_probe() -> None:
    replay = Replay().then(httpx.Response(200, json={"data": []}))
    llm = OpenAICompatProvider(
        "ollama", "http://127.0.0.1:11434/v1", "q", local=True, client=replay.client()
    )
    assert await llm.available()
    assert await llm.available()  # cached, no second request
    assert len(replay.requests) == 1
    assert replay.requests[0].url == "http://127.0.0.1:11434/v1/models"


def test_tool_names_round_trip() -> None:
    names = ToolNames([APP_OPEN, ToolSpec("mcp.files/read", "", {})])
    assert ToolNames.wire("mcp.files/read") == "mcp__files_read"
    assert names.ours("mcp__files_read") == "mcp.files/read"
    assert names.ours("unknown") == "unknown"
