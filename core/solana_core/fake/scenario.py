"""Endless demo loop of events: wake word, transcript, answer, tool confirmation."""

from __future__ import annotations

import asyncio
import uuid

from solana_core.protocol.generated import (
    AssistantDeltaEvent,
    AssistantDoneEvent,
    ToolFinishedEvent,
    ToolStartedEvent,
    TranscriptEvent,
)
from solana_core.server.core import Core

PHRASES = [
    ("какая сегодня погода", "Сегодня в Москве плюс пять, облачно. Возьмите зонт на вечер."),
    ("включи музыку погромче", "Сделала громче, сейчас семьдесят процентов."),
]


class FakeScenario:
    """Plays the scripted loop. ``speed`` > 1 makes it faster (tests use a large value)."""

    def __init__(self, core: Core, speed: float = 1.0) -> None:
        self.core = core
        self.speed = speed
        self.cycles = 0

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds / self.speed)

    async def run(self) -> None:
        while True:
            await self._sleep(2.0)
            if self.core.muted or self.core.turn_lock.locked():
                continue
            async with self.core.turn_lock:
                await self.cycle()

    async def cycle(self) -> None:
        core = self.core
        question, answer = PHRASES[self.cycles % len(PHRASES)]
        with_tool = self.cycles % 2 == 1
        self.cycles += 1

        core.set_state("wake", "wake_word")
        await self._sleep(0.5)
        core.set_state("listening")
        utterance_id = uuid.uuid4().hex
        words = question.split()
        for i in range(1, len(words)):
            core.bus.emit(
                "transcript.partial",
                TranscriptEvent(utterance_id=utterance_id, text=" ".join(words[:i]), language="ru"),
            )
            await self._sleep(0.3)
        core.bus.emit(
            "transcript.final",
            TranscriptEvent(utterance_id=utterance_id, text=question, language="ru"),
        )
        core.set_state("thinking")
        await self._sleep(0.8)

        turn_id = uuid.uuid4().hex
        if with_tool and not await self._tool_step(turn_id):
            answer = "Хорошо, оставила как было."

        core.set_state("speaking")
        for word in answer.split(" "):
            core.bus.emit("assistant.delta", AssistantDeltaEvent(turn_id=turn_id, text=word + " "))
            await self._sleep(0.15)
        core.bus.emit("assistant.done", AssistantDoneEvent(turn_id=turn_id, text=answer))
        await self._sleep(0.5)
        core.set_state("idle")

    async def _tool_step(self, turn_id: str) -> bool:
        core = self.core
        call_id = uuid.uuid4().hex
        args: dict[str, object] = {"percent": 70}
        approved = await core.confirm(
            "pc.set_volume",
            "confirm",
            "Сделать громкость 70%?",
            args,
            timeout_s=8.0 / self.speed,
        )
        if not approved:
            return False
        core.bus.emit(
            "tool.started",
            ToolStartedEvent(
                call_id=call_id, turn_id=turn_id, tool="pc.set_volume", arguments=args
            ),
        )
        await self._sleep(0.3)
        core.bus.emit(
            "tool.finished",
            ToolFinishedEvent(
                call_id=call_id, tool="pc.set_volume", ok=True, summary="Громкость 70%"
            ),
        )
        return True
