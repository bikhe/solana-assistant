"""The fakes behave as their contracts promise, so other packages can rely on them."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from solana_core.audio.base import FRAME_BYTES, FakeAudioSink, FakeAudioSource, FakeVAD
from solana_core.brain.base import Done, FakeLLM, Message, TextDelta, ToolCall, ToolCallRequest
from solana_core.pc.base import FakePcBackend, NotSupportedError, PcBackend, get_pc_backend
from solana_core.stt.base import FakeSTT
from solana_core.tools import ToolContext, ToolRegistry
from solana_core.tools.base import FakeTool
from solana_core.tts.base import FakeTTS
from solana_core.wake.base import FakeWakeWordDetector

SILENCE = bytes(FRAME_BYTES)
SPEECH = b"\x01" * FRAME_BYTES


async def test_audio_source_vad_and_wake() -> None:
    source = FakeAudioSource([SILENCE, SPEECH, SPEECH])
    await source.start()
    frames = [f async for f in source.frames()]
    vad = FakeVAD()
    assert [vad.is_speech(f) for f in frames] == [False, True, True]
    wake = FakeWakeWordDetector(fire_after=3)
    hits = [wake.process(f) for f in frames]
    assert hits[:2] == [None, None]
    assert hits[2] is not None and hits[2].keyword == "эй_солана"


async def test_stt_streams_partials_then_final() -> None:
    async def frames() -> AsyncIterator[bytes]:
        yield SPEECH

    results = [t async for t in FakeSTT("открой браузер").stream(frames())]
    assert [t.final for t in results] == [False, True]
    assert results[-1].text == "открой браузер"


async def test_tts_and_sink() -> None:
    tts, sink = FakeTTS(), FakeAudioSink()
    await sink.play(tts.synthesize("да"))
    assert tts.spoken == ["да"]
    assert len(sink.played) == 2


async def test_llm_script_and_echo() -> None:
    call = ToolCall("1", "fake.echo", {"text": "hi"})
    llm = FakeLLM([[ToolCallRequest(call)]])
    first = [e async for e in llm.stream([Message("user", "x")])]
    assert first == [ToolCallRequest(call), Done("tool_use")]
    second = [e async for e in llm.stream([Message("user", "привет")])]
    assert second == [TextDelta("Вы сказали: привет"), Done("end")]


async def test_tool_registry() -> None:
    registry = ToolRegistry()
    tool = FakeTool()
    registry.register(tool)
    with pytest.raises(ValueError):
        registry.register(FakeTool())
    assert [s.name for s in registry.specs()] == ["fake.echo"]
    result = await tool.run({"text": "ok"}, ToolContext())
    assert result.content == "ok"
    registry.set_enabled("fake.echo", False)
    assert registry.get("fake.echo") is None
    assert registry.specs() == []
    assert registry.info("fake.echo").enabled is False


async def test_pc_backend_reports_unsupported() -> None:
    with pytest.raises(NotSupportedError) as info:
        await PcBackend().set_volume(10)
    assert info.value.operation == "set_volume"
    assert isinstance(get_pc_backend(), PcBackend)


async def test_fake_pc_backend() -> None:
    pc = FakePcBackend()
    await pc.set_volume(150)
    assert await pc.get_volume() == 100
    await pc.open_app("browser")
    assert [w.app for w in await pc.list_windows()] == ["browser"]
    assert ("open_app", ("browser",)) in pc.calls
    with pytest.raises(NotSupportedError):
        await pc.shutdown()
