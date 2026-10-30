"""One conversation with Solana: persona prompt, history window, fast commands and the
tool-calling loop. Used by text chat now and by the voice pipeline (WP6) later."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from solana_core.brain import fast
from solana_core.brain.base import LLMProvider, Message, TextDelta, ToolCall, ToolCallRequest
from solana_core.brain.errors import LLMError
from solana_core.brain.prompts import system_prompt
from solana_core.pc.base import NotSupportedError
from solana_core.protocol import Language
from solana_core.tools import Tool, ToolContext, ToolError, ToolRegistry, ToolResult

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolStarted:
    call: ToolCall


@dataclass(frozen=True, slots=True)
class ToolFinished:
    call: ToolCall
    result: ToolResult


@dataclass(frozen=True, slots=True)
class TurnDone:
    text: str  # everything said in this turn
    fast: bool = False  # answered by a fast command, without the LLM
    error: str | None = None  # technical reason when the turn failed


DialogEvent = TextDelta | ToolStarted | ToolFinished | TurnDone

# Decides whether a tool call may run. WP9 provides the real policy with confirmations.
Approver = Callable[[Tool, ToolCall], Awaitable[bool]]


async def allow_safe(tool: Tool, call: ToolCall) -> bool:
    return tool.risk == "safe"


_TEXT: dict[str, dict[Language, str]] = {
    "unavailable": {
        "ru": "Не могу связаться с моделью. Проверь настройки или сеть.",
        "en": "I can't reach the model. Check the settings or the network.",
    },
    "failed": {
        "ru": "Что-то пошло не так, попробуй ещё раз.",
        "en": "Something went wrong, please try again.",
    },
    "too_many_steps": {
        "ru": "Не получилось сделать это за несколько шагов, давай попробуем проще.",
        "en": "I couldn't finish that in a few steps, let's try something simpler.",
    },
    "declined": {"ru": "Хорошо, не буду.", "en": "Okay, I won't."},
    "tool_missing": {
        "ru": "Инструмент {name} недоступен.",
        "en": "The tool {name} is not available.",
    },
    "tool_declined": {
        "ru": "Пользователь отклонил это действие.",
        "en": "The user declined this action.",
    },
    "not_supported": {
        "ru": "Это не поддерживается на этом компьютере.",
        "en": "This is not supported on this computer.",
    },
    "tool_error": {"ru": "Ошибка инструмента: {error}", "en": "Tool error: {error}"},
}


def _t(key: str, language: Language, **kwargs: str) -> str:
    return _TEXT[key][language].format(**kwargs)


class Dialog:
    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        *,
        approve: Approver = allow_safe,
        max_steps: int = 6,
        history_turns: int = 10,
        history_chars: int = 16_000,
        idle_reset_s: float | None = 15 * 60,
        fast_commands: bool = True,
        prompt_extra: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.approve = approve
        self.max_steps = max_steps
        self.history_turns = history_turns
        self.history_chars = history_chars
        self.idle_reset_s = idle_reset_s
        self.fast_commands = fast_commands
        self.prompt_extra = prompt_extra  # skills (WP8) and memory (WP10) hook in here
        self._clock = clock
        self._last_turn: float | None = None
        self.history: list[Message] = []

    def reset(self) -> None:
        self.history.clear()

    def window(self) -> list[Message]:
        """The last ``history_turns`` turns, cut further to ``history_chars`` characters.
        Always starts at a user message, so no tool result loses its call."""
        starts = [i for i, m in enumerate(self.history) if m.role == "user"]
        if not starts:
            return []
        starts = starts[-self.history_turns :]
        size = sum(len(m.content) for m in self.history[starts[0] :])
        while len(starts) > 1 and size > self.history_chars:
            size -= sum(len(m.content) for m in self.history[starts[0] : starts[1]])
            starts.pop(0)
        return self.history[starts[0] :]

    async def turn(
        self, text: str, *, language: Language = "ru", turn_id: str | None = None
    ) -> AsyncIterator[DialogEvent]:
        """Answer one user phrase. Streams text and tool events, ends with ``TurnDone``."""
        now = self._clock()
        idle = now - self._last_turn if self._last_turn is not None else 0.0
        if self.idle_reset_s is not None and idle > self.idle_reset_s:
            self.reset()
        self._last_turn = now

        user = Message("user", text)
        match = fast.parse(text) if self.fast_commands else None
        if match and self.tools.get(match.tool):
            async for event in self._fast_turn(user, match, language, turn_id):
                yield event
            return

        async for event in self._llm_turn(user, language, turn_id):
            yield event

    async def _fast_turn(
        self, user: Message, match: fast.FastMatch, language: Language, turn_id: str | None
    ) -> AsyncIterator[DialogEvent]:
        call = ToolCall(f"fast_{uuid.uuid4().hex[:12]}", match.tool, match.arguments)
        yield ToolStarted(call)
        result = await self._execute(call, language, turn_id)
        yield ToolFinished(call, result)
        if result.ok:
            answer = match.reply_for(language)
        elif result.data.get("declined"):
            answer = _t("declined", language)
        else:
            answer = result.content
        yield TextDelta(answer)
        self.history += [user, Message("assistant", answer)]
        yield TurnDone(answer, fast=True)

    async def _llm_turn(
        self, user: Message, language: Language, turn_id: str | None
    ) -> AsyncIterator[DialogEvent]:
        extra = self.prompt_extra() if self.prompt_extra else ""
        system = Message("system", system_prompt(language, extra=extra))
        added: list[Message] = [user]
        spoken: list[str] = []
        error: str | None = None
        finished = False
        try:
            for _ in range(self.max_steps):
                text, calls = "", []
                async for event in self.llm.stream(
                    [system, *self.window(), *added], self.tools.specs()
                ):
                    if isinstance(event, TextDelta) and event.text:
                        text += event.text
                        yield event
                    elif isinstance(event, ToolCallRequest):
                        calls.append(event.call)
                if text.strip():
                    spoken.append(text.strip())
                added.append(Message("assistant", text, tuple(calls)))
                if not calls:
                    break
                for call in calls:
                    yield ToolStarted(call)
                    result = await self._execute(call, language, turn_id)
                    yield ToolFinished(call, result)
                    added.append(Message("tool", result.content, tool_call_id=call.id))
            else:
                note = _t("too_many_steps", language)
                yield TextDelta(note)
                spoken.append(note)
                added.append(Message("assistant", note))
            finished = True
        except LLMError as exc:
            log.warning("LLM failed: %s", exc)
            error = str(exc)
            note = _t("unavailable" if exc.unreachable else "failed", language)
            yield TextDelta(("\n" if spoken else "") + note)
            spoken.append(note)
            # Keep only the question and what was already said; a half-done tool step
            # would leave calls without results, which the APIs reject.
            added = [user, Message("assistant", " ".join(spoken))]
            finished = True
        finally:
            if not finished:  # cancelled mid-turn (barge-in): same cleanup as above
                added = [user, Message("assistant", " ".join(spoken))] if spoken else [user]
            self.history += added
        yield TurnDone(" ".join(spoken), error=error)

    async def _execute(self, call: ToolCall, language: Language, turn_id: str | None) -> ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(_t("tool_missing", language, name=call.name), ok=False)
        if not await self.approve(tool, call):
            return ToolResult(_t("tool_declined", language), ok=False, data={"declined": True})
        try:
            return await tool.run(call.arguments, ToolContext(language, turn_id, call.id))
        except ToolError as exc:
            return ToolResult(str(exc), ok=False)
        except NotSupportedError:
            return ToolResult(_t("not_supported", language), ok=False)
        except Exception as exc:
            log.exception("tool %s crashed", call.name)
            return ToolResult(
                _t("tool_error", language, error=str(exc) or type(exc).__name__), ok=False
            )
