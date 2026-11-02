"""End-to-end tests of the voice pipeline on WAV scenarios with a fake LLM.

Each test writes a scenario WAV (wake beep, "words", pauses), plays it through the
pipeline at several times real time and checks the events the app would receive.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import pytest

from solana_core.audio.vad import EnergyVAD
from solana_core.brain.base import FakeLLM, LLMEvent, TextDelta
from solana_core.config import ConfigStore, MemorySecretStore
from solana_core.pipeline import (
    AutoPause,
    EndReason,
    FakePauseProbe,
    PipelineConfig,
    VoicePipeline,
)
from solana_core.server.core import Core
from solana_core.tools.base import Tool, ToolContext, ToolResult
from solana_core.tts.base import FakeTTS
from tests.pipeline_fixtures import PacedSink, PacedSource, Script, ToneSTT, ToneWakeDetector

SPEED = 8.0

WEATHER, CITY, TIME, STOP, CANCEL = 200.0, 300.0, 350.0, 420.0, 470.0
WORDS = {
    WEATHER: "какая погода",
    CITY: "в москве",
    TIME: "который час",
    STOP: "стоп",
    CANCEL: "отмена",
}


@dataclass
class Run:
    core: Core
    pipeline: VoicePipeline
    llm: FakeLLM
    stt: ToneSTT
    tts: FakeTTS
    sink: PacedSink
    events: list[dict[str, Any]] = field(default_factory=list)

    def named(self, name: str) -> list[dict[str, Any]]:
        return [e["params"] for e in self.events if e["method"] == name]

    @property
    def states(self) -> list[str]:
        return [p["state"] for p in self.named("state")]

    def state_reasons(self) -> list[tuple[str, str | None]]:
        return [(p["state"], p.get("reason")) for p in self.named("state")]


def make_run(
    tmp_path: Path,
    script: Script,
    *,
    turns: Sequence[Sequence[LLMEvent]] = (),
    config: PipelineConfig | None = None,
    autopause: AutoPause | None = None,
    words: dict[float, str] | None = None,
    speed: float = SPEED,
) -> Run:
    core = Core(ConfigStore(tmp_path / "config.toml"), MemorySecretStore(), llm=FakeLLM(turns))
    assert isinstance(core.llm, FakeLLM)
    stt = ToneSTT(words or WORDS)
    tts = FakeTTS()
    sink = PacedSink(speed)
    pipeline = VoicePipeline(
        core,
        PacedSource(script.save(tmp_path / "scenario.wav"), speed),
        vad=EnergyVAD(),
        stt=stt,
        tts=tts,
        sink=sink,
        wake=ToneWakeDetector(),
        autopause=autopause,
        config=config or PipelineConfig(mic_muted_after_s=None),
    )
    return Run(core, pipeline, core.llm, stt, tts, sink)


async def play(run: Run) -> Run:
    queue = run.core.bus.subscribe()
    try:
        await asyncio.wait_for(run.pipeline.run(), 60)
        # Let the last session finish (its cleanup runs after the source ends).
        await asyncio.sleep(0)
    finally:
        run.core.bus.unsubscribe(queue)
    while not queue.empty():
        run.events.append(json.loads(queue.get_nowait()))
    return run


def long_answer(sentences: int = 20) -> list[LLMEvent]:
    return [TextDelta("Раз два три. ") for _ in range(sentences)]


async def test_command_is_heard_answered_and_spoken(tmp_path: Path) -> None:
    script = Script().pause(0.5).wake().pause(0.3).say(WEATHER).pause(2.5)
    run = await play(
        make_run(tmp_path, script, turns=[[TextDelta("Сегодня "), TextDelta("солнечно.")]])
    )

    assert run.states == ["wake", "listening", "thinking", "speaking", "idle"]
    assert run.state_reasons()[0] == ("wake", "wake_word")
    assert run.state_reasons()[-1] == ("idle", "done")
    assert [p["text"] for p in run.named("transcript.partial")] == ["какая"]
    final = run.named("transcript.final")
    assert [p["text"] for p in final] == ["какая погода"]
    assert run.named("transcript.partial")[0]["utterance_id"] == final[0]["utterance_id"]
    assert [p["text"] for p in run.named("assistant.delta")] == ["Сегодня ", "солнечно."]
    done = run.named("assistant.done")
    assert done == [{"turn_id": done[0]["turn_id"], "text": "Сегодня солнечно."}]
    assert run.llm.calls[0][-1].content == "какая погода"
    assert run.tts.spoken == ["Сегодня солнечно."]
    assert run.sink.played_s == pytest.approx(len("Сегодня солнечно.") / 100)

    [metrics] = run.pipeline.metrics
    assert metrics.end_reason is EndReason.SILENCE
    assert metrics.first_audio_s is not None and metrics.first_audio_s < 0.5
    assert not metrics.interrupted


async def test_silence_after_wake_word_goes_back_to_idle(tmp_path: Path) -> None:
    run = await play(make_run(tmp_path, Script().wake().pause(7.0)))

    assert run.state_reasons() == [
        ("wake", "wake_word"),
        ("listening", None),
        ("idle", "no_speech"),
    ]
    assert run.stt.calls == 0  # nothing was sent to the recognizer
    assert run.llm.calls == []


async def test_end_of_speech_follows_the_setting(tmp_path: Path) -> None:
    # A 1.5 s pause inside the phrase: with 2 s of end silence it stays one phrase.
    script = Script().wake().say(WEATHER, 0.4).pause(1.5).say(WEATHER, 0.4).pause(3.0)
    run = make_run(tmp_path, script)
    run.core.config.update({"voice": {"end_of_speech_ms": 2000}})
    await play(run)

    assert len(run.named("transcript.final")) == 1
    assert run.states.count("thinking") == 1


async def test_command_is_cut_at_the_length_limit(tmp_path: Path) -> None:
    script = Script().wake().say(WEATHER, 4.0).pause(2.0)
    run = await play(
        make_run(tmp_path, script, config=PipelineConfig(max_command_s=2, mic_muted_after_s=None))
    )

    [metrics] = run.pipeline.metrics
    assert metrics.end_reason is EndReason.MAX_LENGTH
    assert run.states == ["wake", "listening", "thinking", "speaking", "idle"]


async def test_cancel_word_skips_the_llm(tmp_path: Path) -> None:
    run = await play(make_run(tmp_path, Script().wake().say(CANCEL, 0.5).pause(2.0)))

    assert run.state_reasons()[-1] == ("idle", "cancelled")
    assert "thinking" not in run.states
    assert run.llm.calls == []


async def test_wake_word_while_speaking_interrupts_and_listens(tmp_path: Path) -> None:
    script = (
        Script()
        .wake()
        .say(WEATHER)
        .pause(1.6)  # end of phrase after 1 s, then the long answer starts
        .wake()  # barge-in about 0.5 s into the answer
        .pause(0.2)
        .say(TIME)
        .pause(2.5)
    )
    run = await play(make_run(tmp_path, script, turns=[long_answer(), [TextDelta("Пять часов.")]]))

    first, second = run.named("assistant.done")
    assert first["interrupted"] is True
    assert "interrupted" not in second and second["text"] == "Пять часов."
    assert ("wake", "barge_in") in run.state_reasons()
    assert [p["text"] for p in run.named("transcript.final")] == ["какая погода", "который час"]
    assert run.sink.stops >= 1
    assert run.sink.played_s < len("Раз два три. ") * 20 / 100  # the long answer was cut
    assert run.pipeline.metrics[0].interrupted
    assert run.states[-1] == "idle"


async def test_stop_word_while_speaking_stops_the_answer(tmp_path: Path) -> None:
    script = Script().wake().say(WEATHER).pause(1.6).say(STOP, 0.4).pause(2.5)
    run = await play(make_run(tmp_path, script, turns=[long_answer()]))

    [done] = run.named("assistant.done")
    assert done["interrupted"] is True
    assert run.state_reasons()[-1] == ("idle", "stop_word")
    assert len(run.llm.calls) == 1
    assert run.sink.played_s < 1.5


async def test_stop_word_that_we_are_saying_is_echo(tmp_path: Path) -> None:
    answer = [TextDelta("Скажи стоп, и я замолчу. "), *long_answer(8)]
    script = Script().wake().say(WEATHER).pause(1.6).say(STOP, 0.4).pause(2.5)
    run = await play(make_run(tmp_path, script, turns=[answer]))

    [done] = run.named("assistant.done")
    assert "interrupted" not in done
    assert run.state_reasons()[-1] == ("idle", "done")


async def test_question_opens_a_follow_up_window(tmp_path: Path) -> None:
    script = Script().wake().say(WEATHER).pause(1.5).say(CITY).pause(2.5)
    turns = [[TextDelta("Для какого города?")], [TextDelta("В Москве солнечно.")]]
    run = await play(make_run(tmp_path, script, turns=turns))

    assert run.state_reasons() == [
        ("wake", "wake_word"),
        ("listening", None),
        ("thinking", "voice"),
        ("speaking", None),
        ("listening", "follow_up"),
        ("thinking", "voice"),
        ("speaking", None),
        ("idle", "done"),
    ]
    assert [p["text"] for p in run.named("assistant.done")] == [
        "Для какого города?",
        "В Москве солнечно.",
    ]


async def test_follow_up_window_closes_after_silence(tmp_path: Path) -> None:
    script = Script().wake().say(WEATHER).pause(8.0)
    run = make_run(
        tmp_path,
        script,
        turns=[[TextDelta("Что-нибудь ещё?")]],
        config=PipelineConfig(follow_up_s=3, mic_muted_after_s=None),
    )
    await play(run)

    assert run.state_reasons()[-2:] == [("listening", "follow_up"), ("idle", "no_speech")]
    assert len(run.llm.calls) == 1


async def test_muted_pipeline_ignores_the_wake_word(tmp_path: Path) -> None:
    run = make_run(tmp_path, Script().wake().say(WEATHER).pause(2.0))
    run.core.set_state("muted", "user")
    await play(run)

    assert run.events == []
    assert run.llm.calls == []


async def test_muting_while_speaking_cuts_the_answer(tmp_path: Path) -> None:
    run = make_run(tmp_path, Script().wake().say(WEATHER).pause(4.0), turns=[long_answer()])

    async def mute_when_speaking() -> None:
        while run.core.state != "speaking":  # noqa: ASYNC110 - polling the test subject
            await asyncio.sleep(0.005)
        run.core.set_state("muted", "user")

    muter = asyncio.create_task(mute_when_speaking())
    await play(run)
    await muter

    [done] = run.named("assistant.done")
    assert done["interrupted"] is True
    assert run.states[-1] == "muted"
    assert run.sink.played_s < 1.5


async def test_auto_pause_while_screen_is_locked(tmp_path: Path) -> None:
    probe = FakePauseProbe("screen_locked", value=True)
    script = Script().pause(0.5).wake().say(WEATHER).pause(1.5).wake().say(TIME).pause(2.0)
    run = make_run(
        tmp_path,
        script,
        autopause=AutoPause([probe]),
        config=PipelineConfig(pause_poll_s=0.01, mic_muted_after_s=None),
    )

    async def unlock_after_first_command() -> None:
        while run.pipeline.audio_time < 3.0:  # noqa: ASYNC110
            await asyncio.sleep(0.005)
        probe.value = False

    unlocker = asyncio.create_task(unlock_after_first_command())
    await play(run)
    await unlocker

    assert run.state_reasons()[:2] == [("muted", "screen_locked"), ("idle", "resumed")]
    # Only the command said after unlocking was heard.
    assert [p["text"] for p in run.named("transcript.final")] == ["который час"]


async def test_auto_pause_does_not_unmute_what_the_user_muted(tmp_path: Path) -> None:
    probe = FakePauseProbe("call", value=False)
    run = make_run(
        tmp_path,
        Script().pause(1.0),
        autopause=AutoPause([probe]),
        config=PipelineConfig(pause_poll_s=0.01, mic_muted_after_s=None),
    )
    run.core.set_state("muted", "user")

    async def call_comes_and_goes() -> None:
        await asyncio.sleep(0.03)
        probe.value = True
        await asyncio.sleep(0.03)
        probe.value = False

    task = asyncio.create_task(call_comes_and_goes())
    await play(run)
    await task

    assert run.core.state == "muted"
    assert run.events == []


async def test_muted_microphone_pauses_and_resumes(tmp_path: Path) -> None:
    script = Script().zeros(3.0).pause(0.5).wake().say(WEATHER).pause(2.5)
    run = await play(make_run(tmp_path, script, config=PipelineConfig(mic_muted_after_s=2.0)))

    assert run.state_reasons()[:3] == [
        ("muted", "mic_muted"),
        ("idle", "resumed"),
        ("wake", "wake_word"),
    ]
    assert [p["text"] for p in run.named("transcript.final")] == ["какая погода"]


async def test_microphone_failure_is_reported(tmp_path: Path) -> None:
    from solana_core.audio.mic import AudioUnavailableError

    run = make_run(tmp_path, Script().pause(0.1))

    async def broken() -> None:
        raise AudioUnavailableError("нет устройства")

    run.pipeline.source.start = broken  # type: ignore[method-assign]
    await play(run)

    [error] = run.named("error")
    assert error["code"] == "mic_unavailable" and error["recoverable"] is False
    assert "нет устройства" in error["message"]
    assert run.core.state == "error"


class RecordingTool(Tool):
    description = "Записывает вызовы. Только для тестов."
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "additionalProperties": True}

    def __init__(self, name: str, log: list[tuple[str, dict[str, Any]]]) -> None:
        self.name = name  # type: ignore[misc]
        self.log = log

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        self.log.append((self.name, args))
        return ToolResult("ok")


# The manual 20-command scenario from the plan, as a test: fast PC commands, questions for
# the LLM, a cancel and a barge-in, one after another in a single recording.
TWENTY = [
    ("громче", "fast"),
    ("какая погода", "llm"),
    ("пауза", "fast"),
    ("продолжи", "fast"),
    ("тише", "fast"),
    ("расскажи анекдот", "llm"),
    ("следующий трек", "fast"),
    ("открой браузер", "fast"),
    ("отмена", "cancel"),
    ("сколько будет два плюс два", "llm"),
    ("выключи звук", "fast"),
    ("включи звук", "fast"),
    ("предыдущий трек", "fast"),
    ("громкость на пятьдесят", "fast"),
    ("кто написал войну и мир", "llm"),
    ("закрой браузер", "fast"),
    ("найди в интернете рецепт блинов", "fast"),
    ("открой ютуб", "fast"),
    ("какой сегодня день", "llm"),
    ("не надо", "cancel"),
]


async def test_twenty_commands_in_a_row(tmp_path: Path) -> None:
    words = {150.0 + 22.0 * i: text for i, (text, _) in enumerate(TWENTY)}
    script = Script().pause(0.3)
    for pitch in words:
        script.wake().pause(0.1).say(pitch, 0.6).pause(1.8)
    run = make_run(tmp_path, script, words=words, speed=12.0)
    calls: list[tuple[str, dict[str, Any]]] = []
    for name in ("pc.volume_change", "pc.volume_set", "pc.media", "pc.mute", "pc.app_open"):
        run.core.tools.register(RecordingTool(name, calls))
    for name in ("pc.app_close", "pc.web_search", "pc.url_open"):
        run.core.tools.register(RecordingTool(name, calls))
    await play(run)

    heard = [p["text"] for p in run.named("transcript.final")]
    assert heard == [text for text, _ in TWENTY]
    answered = [m.text for m in run.pipeline.metrics]
    assert answered == [text for text, kind in TWENTY if kind != "cancel"]
    assert [m.fast for m in run.pipeline.metrics] == [
        kind == "fast" for _, kind in TWENTY if kind != "cancel"
    ]
    assert len(run.llm.calls) == sum(kind == "llm" for _, kind in TWENTY)
    assert ("pc.volume_set", {"level": 50}) in calls
    assert ("pc.url_open", {"url": "https://youtube.com"}) in calls
    assert ("pc.web_search", {"query": "рецепт блинов"}) in calls
    done = run.named("assistant.done")
    assert len(done) == 18 and not any(d.get("interrupted") for d in done)
    assert all(m.first_audio_s is not None and m.first_audio_s < 1.0 for m in run.pipeline.metrics)
    assert run.states[-1] == "idle"


async def test_push_to_talk_starts_listening_without_wake_word(tmp_path: Path) -> None:
    run = make_run(tmp_path, Script().pause(0.5).say(WEATHER).pause(2.5))

    async def press_hotkey() -> None:
        while run.pipeline.audio_time < 0.2:  # noqa: ASYNC110
            await asyncio.sleep(0.005)
        assert run.pipeline.activate()

    task = asyncio.create_task(press_hotkey())
    await play(run)
    await task

    assert run.state_reasons()[0] == ("wake", "hotkey")
    assert [p["text"] for p in run.named("transcript.final")] == ["какая погода"]


async def test_wake_word_said_as_the_answer_ends_is_heard(tmp_path: Path) -> None:
    # The answer (0.52 s) ends in the middle of the next wake word: the detector has been
    # listening for barge-in, so the end of the turn must not make it forget the start.
    script = Script().wake().say(WEATHER).pause(1.3).wake().pause(0.1).say(TIME).pause(2.5)
    run = await play(make_run(tmp_path, script, turns=[long_answer(4), [TextDelta("Пять.")]]))

    assert [p["text"] for p in run.named("transcript.final")] == ["какая погода", "который час"]
