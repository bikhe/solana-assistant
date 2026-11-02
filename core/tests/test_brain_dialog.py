"""Scenario tests: the dialog loop with fake PC tools, on scripted and recorded model turns."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest

from solana_core.brain.anthropic import AnthropicProvider
from solana_core.brain.base import Done, FakeLLM, TextDelta, ToolCall, ToolCallRequest
from solana_core.brain.dialog import (
    Dialog,
    DialogEvent,
    ToolFinished,
    ToolStarted,
    TurnDone,
)
from solana_core.brain.errors import LLMError
from solana_core.brain.openai_compat import OpenAICompatProvider
from solana_core.pc.base import NotSupportedError
from solana_core.protocol import Risk
from solana_core.tools import Tool, ToolContext, ToolError, ToolRegistry, ToolResult
from tests.llm_replay import Replay


class PcTool(Tool):
    """Fake PC tool: remembers calls, answers ``ok``."""

    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    def __init__(self, name: str, risk: Risk = "safe", fail: Exception | None = None) -> None:
        self.name = name  # type: ignore[misc]
        self.description = f"fake {name}"  # type: ignore[misc]
        self.risk = risk  # type: ignore[misc]
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        self.calls.append(args)
        if self.fail:
            raise self.fail
        return ToolResult("ok")


def registry(*tools: Tool) -> ToolRegistry:
    reg = ToolRegistry()
    for tool in tools:
        reg.register(tool)
    return reg


async def run(dialog: Dialog, text: str, **kwargs: Any) -> list[DialogEvent]:
    return [e async for e in dialog.turn(text, **kwargs)]


def spoken(events: list[DialogEvent]) -> str:
    return "".join(e.text for e in events if isinstance(e, TextDelta))


def done(events: list[DialogEvent]) -> TurnDone:
    last = events[-1]
    assert isinstance(last, TurnDone)
    return last


async def test_recorded_claude_opens_browser() -> None:
    app_open = PcTool("pc.app_open")
    replay = Replay("anthropic_tool.sse", "anthropic_after_tool.sse")
    llm = AnthropicProvider("sk-test", "claude-sonnet-5-5", client=replay.client())
    dialog = Dialog(llm, registry(app_open))

    events = await run(dialog, "Мне нужен браузер, открой его")

    assert app_open.calls == [{"name": "браузер"}]
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["TextDelta", "ToolStarted", "ToolFinished", "TextDelta", "TurnDone"]
    assert done(events).text == "Сейчас открою. Открыла браузер."
    assert not done(events).fast

    first, second = replay.bodies()
    assert "Солана" in first["system"]
    assert [t["name"] for t in first["tools"]] == ["pc__app_open"]
    result_turn = second["messages"][-1]
    assert result_turn["role"] == "user"
    assert result_turn["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "toolu_01A",
        "content": "ok",
    }
    assert [m.role for m in dialog.history] == ["user", "assistant", "tool", "assistant"]


async def test_recorded_ollama_pauses_music() -> None:
    media = PcTool("pc.media")
    replay = Replay("ollama_qwen3_tool.sse", "openai_pause_done.sse")
    llm = OpenAICompatProvider(
        "ollama", "http://127.0.0.1:11434/v1", "qwen3:8b", local=True, client=replay.client()
    )
    dialog = Dialog(llm, registry(media))
    events = await run(dialog, "поставь музыку на паузу, а то она мешает разговаривать")
    assert media.calls == [{"action": "pause"}]
    assert "Пользователь хочет" not in spoken(events)  # reasoning is never spoken
    assert done(events).text == "Поставила на паузу."


async def test_fast_command_skips_llm() -> None:
    volume = PcTool("pc.volume_change")
    llm = FakeLLM()
    dialog = Dialog(llm, registry(volume))
    events = await run(dialog, "Солана, громче!")
    assert volume.calls == [{"delta": 10}]
    assert llm.calls == []
    assert done(events) == TurnDone("Громче.", fast=True)
    assert isinstance(events[0], ToolStarted) and events[0].call.id.startswith("fast_")
    assert [m.content for m in dialog.history] == ["Солана, громче!", "Громче."]


async def test_fast_command_in_english() -> None:
    dialog = Dialog(FakeLLM(), registry(PcTool("pc.media")))
    assert done(await run(dialog, "pause", language="en")).text == "Paused."


async def test_fast_command_without_tool_goes_to_llm() -> None:
    llm = FakeLLM()
    dialog = Dialog(llm, ToolRegistry())
    events = await run(dialog, "громче")
    assert len(llm.calls) == 1
    assert done(events).text == "Вы сказали: громче"


async def test_disabled_tool_is_not_used_by_fast_path() -> None:
    reg = registry(PcTool("pc.volume_change"))
    reg.set_enabled("pc.volume_change", False)
    llm = FakeLLM()
    await run(Dialog(llm, reg), "громче")
    assert len(llm.calls) == 1


async def test_fast_command_failure_speaks_tool_message() -> None:
    tool = PcTool("pc.media", fail=ToolError("Сейчас ничего не играет."))
    events = await run(Dialog(FakeLLM(), registry(tool)), "пауза")
    assert done(events).text == "Сейчас ничего не играет."


async def test_confirm_tool_declined() -> None:
    close = PcTool("pc.app_close", risk="confirm")
    asked: list[str] = []

    async def deny(tool: Tool, call: ToolCall) -> bool:
        asked.append(tool.name)
        return False

    dialog = Dialog(FakeLLM(), registry(close), approve=deny)
    events = await run(dialog, "закрой блокнот")
    assert asked == ["pc.app_close"]
    assert close.calls == []
    finished = next(e for e in events if isinstance(e, ToolFinished))
    assert not finished.result.ok
    assert done(events).text == "Хорошо, не буду."


async def test_default_policy_runs_only_safe_tools() -> None:
    shutdown = PcTool("pc.shutdown", risk="dangerous")
    llm = FakeLLM(
        [
            [ToolCallRequest(ToolCall("1", "pc.shutdown", {}))],
            [TextDelta("Не могу без разрешения.")],
        ]
    )
    dialog = Dialog(llm, registry(shutdown))
    await run(dialog, "выключи компьютер")
    assert shutdown.calls == []
    tool_message = llm.calls[1][-1]
    assert tool_message.role == "tool" and "отклонил" in tool_message.content


async def test_two_tools_in_one_step_then_answer() -> None:
    a, b = PcTool("pc.app_open"), PcTool("pc.volume_set")
    llm = FakeLLM(
        [
            [
                ToolCallRequest(ToolCall("1", "pc.app_open", {"name": "музыка"})),
                ToolCallRequest(ToolCall("2", "pc.volume_set", {"level": 40})),
            ],
            [TextDelta("Включила музыку на сорок процентов.")],
        ]
    )
    dialog = Dialog(llm, registry(a, b))
    events = await run(dialog, "включи музыку и сделай звук на сорок")
    assert a.calls and b.calls
    assert [m.role for m in llm.calls[1][-3:]] == ["assistant", "tool", "tool"]
    assert done(events).text == "Включила музыку на сорок процентов."


async def test_step_limit() -> None:
    echo = PcTool("pc.loop")
    turns = [[ToolCallRequest(ToolCall(str(i), "pc.loop", {}))] for i in range(10)]
    dialog = Dialog(FakeLLM(turns), registry(echo), max_steps=3)
    events = await run(dialog, "сделай что-нибудь бесконечное")
    assert len(echo.calls) == 3
    assert "шагов" in done(events).text


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ToolError("Приложение не найдено"), "Приложение не найдено"),
        (NotSupportedError("open_app"), "не поддерживается"),
        (RuntimeError("boom"), "Ошибка инструмента: boom"),
    ],
)
async def test_tool_errors_go_back_to_llm(error: Exception, expected: str) -> None:
    tool = PcTool("pc.app_open", fail=error)
    llm = FakeLLM(
        [[ToolCallRequest(ToolCall("1", "pc.app_open", {"name": "x"}))], [TextDelta("Не вышло.")]]
    )
    events = await run(Dialog(llm, registry(tool)), "мне нужно приложение x")
    finished = next(e for e in events if isinstance(e, ToolFinished))
    assert not finished.result.ok
    assert expected in llm.calls[1][-1].content


async def test_unknown_tool() -> None:
    llm = FakeLLM([[ToolCallRequest(ToolCall("1", "nope", {}))], [TextDelta("Не умею.")]])
    await run(Dialog(llm, ToolRegistry()), "сделай невозможное")
    assert "недоступен" in llm.calls[1][-1].content


class Broken(FakeLLM):
    def __init__(self, error: LLMError, prefix: str = "") -> None:
        super().__init__()
        self.error = error
        self.prefix = prefix

    async def stream(self, messages, tools=()):  # type: ignore[no-untyped-def]
        if self.prefix:
            yield TextDelta(self.prefix)
        raise self.error


async def test_llm_unreachable() -> None:
    dialog = Dialog(Broken(LLMError("refused", unreachable=True)), ToolRegistry())
    events = await run(dialog, "расскажи анекдот")
    assert done(events).error == "refused"
    assert "Не могу связаться" in done(events).text
    assert [m.role for m in dialog.history] == ["user", "assistant"]


async def test_llm_fails_mid_answer() -> None:
    dialog = Dialog(Broken(LLMError("HTTP 500"), prefix="Жил-был"), ToolRegistry())
    events = await run(dialog, "расскажи сказку")
    assert spoken(events).startswith("Жил-был")
    assert "пошло не так" in done(events).text


async def test_history_is_sent_and_windowed() -> None:
    llm = FakeLLM()
    dialog = Dialog(llm, ToolRegistry(), history_turns=2)
    for i in range(4):
        await run(dialog, f"вопрос номер {i} без быстрых команд")
    sent = llm.calls[-1]
    assert sent[0].role == "system"
    users = [m.content for m in sent if m.role == "user"]
    assert users == [
        "вопрос номер 1 без быстрых команд",
        "вопрос номер 2 без быстрых команд",
        "вопрос номер 3 без быстрых команд",
    ]


async def test_history_char_budget_keeps_whole_turns() -> None:
    dialog = Dialog(FakeLLM(), ToolRegistry(), history_chars=100)
    await run(dialog, "а" * 80)
    await run(dialog, "б" * 10)
    window = dialog.window()
    assert window[0].role == "user" and window[0].content == "б" * 10


async def test_idle_reset() -> None:
    now = [0.0]
    dialog = Dialog(FakeLLM(), ToolRegistry(), idle_reset_s=60, clock=lambda: now[0])
    await run(dialog, "первый вопрос")
    now[0] = 30
    await run(dialog, "второй вопрос")
    assert len(dialog.history) == 4
    now[0] = 200
    await run(dialog, "третий вопрос")
    assert dialog.history[0].content == "третий вопрос"


async def test_barge_in_leaves_history_valid() -> None:
    started = asyncio.Event()

    class Slow(Tool):
        name = "pc.slow"
        description = "slow"

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            started.set()
            await asyncio.sleep(10)
            return ToolResult("ok")

    llm = FakeLLM([[TextDelta("Секунду."), ToolCallRequest(ToolCall("1", "pc.slow", {}))]])
    dialog = Dialog(llm, registry(Slow()))

    async def consume() -> None:
        async for _ in dialog.turn("сделай медленную вещь"):
            pass

    task = asyncio.create_task(consume())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [(m.role, m.content, m.tool_calls) for m in dialog.history] == [
        ("user", "сделай медленную вещь", ()),
        ("assistant", "Секунду.", ()),
    ]


async def test_prompt_extra_and_language() -> None:
    llm = FakeLLM()
    dialog = Dialog(llm, ToolRegistry(), prompt_extra=lambda: "Скилл: таймеры.")
    await run(dialog, "hello there my friend", language="en")
    system = llm.calls[0][0].content
    assert system.startswith("You are Solana")
    assert system.endswith("Скилл: таймеры.")


async def test_done_is_last_and_single() -> None:
    llm = FakeLLM([[TextDelta("Да."), Done()]])
    events = await run(Dialog(llm, ToolRegistry()), "ты здесь, Солана, ответь мне")
    assert sum(isinstance(e, TurnDone) for e in events) == 1


async def test_tool_disabled_while_confirmation_pending() -> None:
    close = PcTool("pc.app_close", risk="confirm")
    reg = registry(close)

    async def approve_after_disable(tool: Tool, call: ToolCall) -> bool:
        reg.set_enabled("pc.app_close", False)  # user flips the switch while the card is open
        return True

    events = await run(Dialog(FakeLLM(), reg, approve=approve_after_disable), "закрой блокнот")
    assert close.calls == []
    finished = next(e for e in events if isinstance(e, ToolFinished))
    assert not finished.result.ok


async def test_error_after_tool_keeps_the_finished_step() -> None:
    app_open = PcTool("pc.app_open")

    class ToolThenFail(FakeLLM):
        async def stream(self, messages, tools=()):  # type: ignore[no-untyped-def]
            self.calls.append(list(messages))
            if len(self.calls) == 1:
                yield TextDelta("Открываю.")
                yield ToolCallRequest(ToolCall("1", "pc.app_open", {"name": "браузер"}))
                yield Done("tool_use")
            else:
                yield TextDelta("Откры")
                raise LLMError("HTTP 500")

    dialog = Dialog(ToolThenFail(), registry(app_open))
    events = await run(dialog, "мне нужен браузер, открой его")
    assert done(events).error_code == "llm_error"
    assert done(events).text.startswith("Открываю. Откры")
    roles = [m.role for m in dialog.history]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert dialog.history[1].tool_calls and dialog.history[2].tool_call_id == "1"
    assert dialog.history[3].content.startswith("Откры")


async def test_barge_in_on_fast_command_is_recorded() -> None:
    started = asyncio.Event()

    class SlowVolume(Tool):
        name = "pc.volume_change"
        description = "slow"

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            started.set()
            await asyncio.sleep(10)
            return ToolResult("ok")

    dialog = Dialog(FakeLLM(), registry(SlowVolume()))

    async def consume() -> None:
        async for _ in dialog.turn("громче"):
            pass

    task = asyncio.create_task(consume())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [m.content for m in dialog.history] == ["громче"]
