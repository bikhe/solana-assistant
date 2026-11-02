"""Voices, sentence streaming and playback with instant stop. No models or audio devices."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import types
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from solana_core.config import MemorySecretStore
from solana_core.models import CATALOG, ModelError, ModelManager
from solana_core.protocol import Language
from solana_core.tts import FakeTTS, MultiLanguageTTS, create_tts, speak_stream, split_sentences
from solana_core.tts.base import TTSProvider
from solana_core.tts.numbers import number_to_words, spell_numbers_ru
from solana_core.tts.openai import OpenAITTS
from solana_core.tts.playback import FillCallback, OutputStream, PcmBuffer, SoundDeviceSink


async def deltas(*parts: str, delay: float = 0.0) -> AsyncIterator[str]:
    for part in parts:
        if delay:
            await asyncio.sleep(delay)
        yield part


async def collect(parts: AsyncIterator[str]) -> list[str]:
    return [s async for s in parts]


# Sentence splitting


async def test_split_sentences_streams_whole_sentences() -> None:
    chunks = (
        "Прив",
        "ет! Сейчас ",
        "15 градусов, т.е. ",
        "тепло.",
        " А. С. Пушкин ",
        "жил тут. Это я.",
    )
    assert await collect(split_sentences(deltas(*chunks))) == [
        "Привет!",
        "Сейчас 15 градусов, т.е. тепло.",
        "А. С. Пушкин жил тут.",
        "Это я.",
    ]


async def test_split_sentences_handles_numbers_markdown_and_newlines() -> None:
    text = "Цена **3.5** рубля\n- первый пункт\n- второй?  Да"
    assert await collect(split_sentences(deltas(text))) == [
        "Цена 3.5 рубля",
        "- первый пункт",
        "- второй?",
        "Да",
    ]


async def test_split_sentences_cuts_long_first_phrase() -> None:
    long = "Сначала открой настройки системы, потом выбери раздел звука и там " * 3
    sentences = await collect(split_sentences(deltas(long), first_max_chars=80, max_chars=150))
    assert len(sentences[0]) <= 80 and sentences[0].endswith(",")
    assert all(len(s) <= 150 for s in sentences)
    assert " ".join(sentences) == " ".join(long.split())


class RecordingTTS(TTSProvider):
    name = "recording"

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.started: list[tuple[str, float]] = []

    async def synthesize(self, text: str, language: Language | None = None) -> AsyncIterator[bytes]:
        self.started.append((text, time.monotonic()))
        await asyncio.sleep(self.delay)
        for _ in range(3):
            yield text.encode()[:2] or b"\0\0"


async def test_speak_stream_starts_before_text_ends() -> None:
    tts = RecordingTTS()
    stream = speak_stream(
        tts, deltas("Первое предложение. ", "Второе", " предложение.", delay=0.05)
    )
    first = await anext(stream)
    assert first and [t for t, _ in tts.started] == ["Первое предложение."]
    rest = [c async for c in stream]
    assert len(rest) == 5
    assert [t for t, _ in tts.started] == ["Первое предложение.", "Второе предложение."]


async def test_speak_stream_close_stops_synthesis() -> None:
    tts = RecordingTTS(delay=0.01)
    stream = speak_stream(tts, deltas("Раз. ", "Два. ", "Три. ", "Четыре.", delay=0.02))
    await anext(stream)
    await stream.aclose()  # type: ignore[attr-defined]
    count = len(tts.started)
    await asyncio.sleep(0.15)
    assert len(tts.started) == count < 4


async def test_speak_stream_propagates_errors() -> None:
    class Broken(TTSProvider):
        name = "broken"

        async def synthesize(
            self, text: str, language: Language | None = None
        ) -> AsyncIterator[bytes]:
            raise RuntimeError("no voice")
            yield b""

    with pytest.raises(RuntimeError, match="no voice"):
        [c async for c in speak_stream(Broken(), deltas("Привет."))]


# Russian numbers


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (0, "ноль"),
        (15, "пятнадцать"),
        (21, "двадцать один"),
        (101, "сто один"),
        (2000, "две тысячи"),
        (1_001_512, "один миллион одна тысяча пятьсот двенадцать"),
        (-4, "минус четыре"),
        (11_000, "одиннадцать тысяч"),
    ],
)
def test_number_to_words(n: int, words: str) -> None:
    assert number_to_words(n) == words


def test_spell_numbers_ru() -> None:
    assert spell_numbers_ru("Сейчас 15°, влажность 80%") == (
        "Сейчас пятнадцать градусов, влажность восемьдесят процентов"
    )
    assert spell_numbers_ru("Курс 3,5") == "Курс три и пять"
    assert spell_numbers_ru("mp3 и v4") == "mp3 и v4"


# Providers


async def test_openai_tts_streams_even_pcm() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.read()))
        return httpx.Response(200, stream=httpx.ByteStream(b"\x01\x02\x03\x04\x05"))

    tts = OpenAITTS("sk", voice="coral", transport=httpx.MockTransport(handler))
    audio = b"".join([c async for c in tts.synthesize("Привет")])
    assert audio == b"\x01\x02\x03\x04"
    assert seen[0] == {
        "model": "gpt-4o-mini-tts",
        "input": "Привет",
        "voice": "coral",
        "response_format": "pcm",
    }
    assert [c async for c in tts.synthesize("  ")] == []
    await tts.close()


class ToneTTS(TTSProvider):
    name = "tone"

    def __init__(self, rate: int, value: int) -> None:
        self.sample_rate = rate
        self.value = value

    async def synthesize(self, text: str, language: Language | None = None) -> AsyncIterator[bytes]:
        yield np.full(self.sample_rate // 10, self.value, dtype="<i2").tobytes()


async def test_multi_language_tts_routes_and_resamples() -> None:
    tts = MultiLanguageTTS({"ru": ToneTTS(24_000, 1), "en": ToneTTS(22_050, 2)})
    ru = b"".join([c async for c in tts.synthesize("Привет")])
    en = b"".join([c async for c in tts.synthesize("Hello there")])
    forced = b"".join([c async for c in tts.synthesize("Hello", "ru")])
    assert len(ru) == len(en) == 2400 * 2
    assert set(np.frombuffer(ru, "<i2")) == {1} and set(np.frombuffer(en, "<i2")) == {2}
    assert set(np.frombuffer(forced, "<i2")) == {1}
    only_en = MultiLanguageTTS({"en": ToneTTS(24_000, 2)})
    assert only_en.provider_for("Привет").sample_rate == 24_000


@pytest.fixture
def fake_piper(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    spoken: list[str] = []

    class Voice:
        @staticmethod
        def load(path: str, use_cuda: bool = False) -> Voice:
            return Voice()

        def synthesize(self, text: str) -> list[Any]:
            spoken.append(text)
            pcm = np.ones(2205, dtype="<i2").tobytes()
            return [types.SimpleNamespace(audio_int16_bytes=pcm, sample_rate=22_050)] * 2

    module = types.ModuleType("piper")
    module.PiperVoice = Voice  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "piper", module)
    return spoken


async def test_piper_tts(fake_piper: list[str], tmp_path: Path) -> None:
    from solana_core.tts.piper import PiperTTS

    model = tmp_path / "voice.onnx"
    model.with_name("voice.onnx.json").write_text('{"audio": {"sample_rate": 22050}}')
    tts = PiperTTS(model)
    chunks = [c async for c in tts.synthesize("Hello there.")]
    assert tts.sample_rate == 22_050 and fake_piper == ["Hello there."]
    assert sum(len(c) for c in chunks) == 2205 * 2 * 2
    assert all(len(c) <= 2205 * 2 for c in chunks)


async def test_silero_tts_spells_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class Model:
        def to(self, device: Any) -> None:
            pass

        def apply_tts(self, **kwargs: Any) -> Any:
            calls.append(kwargs)
            return types.SimpleNamespace(numpy=lambda: np.zeros(24_000, dtype=np.float32))

    class Importer:
        def __init__(self, path: str) -> None:
            assert path == "/models/silero.pt"

        def load_pickle(self, package: str, name: str) -> Model:
            return Model()

    torch = types.ModuleType("torch")
    torch.package = types.SimpleNamespace(PackageImporter=Importer)  # type: ignore[attr-defined]
    torch.device = lambda name: name  # type: ignore[attr-defined]
    torch.set_num_threads = lambda n: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", torch)
    from solana_core.tts.silero import SileroTTS

    tts = SileroTTS("/models/silero.pt", speaker="unknown")
    audio = b"".join([c async for c in tts.synthesize("Через 5 минут")])
    assert len(audio) == 24_000 * 2
    assert calls[0]["text"] == "Через пять минут" and calls[0]["speaker"] == "xenia"
    assert next(v.id for v in await tts.voices()) == "xenia"


def test_create_tts(tmp_path: Path, fake_piper: list[str]) -> None:
    mm = ModelManager(tmp_path, CATALOG)
    secrets = MemorySecretStore()
    assert isinstance(create_tts("fake", models=mm, secrets=secrets), FakeTTS)
    assert isinstance(create_tts("openai", models=mm, secrets=secrets), OpenAITTS)
    with pytest.raises(ModelError):
        create_tts("silero", models=mm, secrets=secrets)
    with pytest.raises(ModelError):
        create_tts("piper", models=mm, secrets=secrets)
    with pytest.raises(ValueError):
        create_tts("espeak", models=mm, secrets=secrets)

    folder = mm.path("piper-en_US-amy-medium")
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text("{}")
    (folder / "voice.onnx.json").write_text('{"audio": {"sample_rate": 22050}}')
    tts = create_tts("piper", models=mm, secrets=secrets)
    assert isinstance(tts, MultiLanguageTTS) and list(tts.providers) == ["en"]


# Playback


class ThreadStream(OutputStream):
    """Pulls audio from the sink on a thread, like PortAudio, 10 ms per block."""

    def __init__(self, blocksize: int, fill: FillCallback, finished: Callable[[], None]) -> None:
        self.blocksize, self.fill, self.finished = blocksize, fill, finished
        self.played = bytearray()
        self.aborted = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        out = bytearray(self.blocksize * 2)
        while not self.aborted.is_set():
            more = self.fill(memoryview(out))
            self.played += out
            if not more:
                break
            time.sleep(0.01)
        self.finished()

    def start(self) -> None:
        self._thread.start()

    def abort(self) -> None:
        self.aborted.set()

    def close(self) -> None:
        pass


def thread_sink() -> tuple[SoundDeviceSink, list[ThreadStream]]:
    streams: list[ThreadStream] = []

    def factory(
        rate: int, blocksize: int, device: str | None, fill: FillCallback, done: Callable[[], None]
    ) -> OutputStream:
        stream = ThreadStream(blocksize, fill, done)
        streams.append(stream)
        return stream

    return SoundDeviceSink(block_ms=10, max_buffer_s=0.05, stream_factory=factory), streams


async def tone(chunks: int, value: int = 7) -> AsyncIterator[bytes]:
    for _ in range(chunks):
        yield np.full(160, value, dtype="<i2").tobytes()  # 10 ms at 16 kHz


async def test_sink_plays_everything() -> None:
    sink, streams = thread_sink()
    await asyncio.wait_for(sink.play(tone(10)), 2)
    played = np.frombuffer(bytes(streams[0].played), "<i2")
    assert (played == 7).sum() == 1600
    assert not sink.playing


async def test_sink_stops_instantly() -> None:
    sink, streams = thread_sink()
    task = asyncio.create_task(sink.play(tone(1000)))  # 10 s of audio
    await asyncio.sleep(0.1)
    assert sink.playing
    started = time.monotonic()
    await sink.stop()
    await asyncio.wait_for(task, 1)
    assert time.monotonic() - started < 0.25
    assert streams[0].aborted.is_set()
    assert len(streams[0].played) < 16_000 * 2  # far less than the 10 s queued


async def test_sink_new_play_interrupts_old() -> None:
    sink, streams = thread_sink()
    first = asyncio.create_task(sink.play(tone(1000, 1)))
    await asyncio.sleep(0.05)
    await asyncio.wait_for(sink.play(tone(5, 2)), 2)
    await asyncio.wait_for(first, 1)
    assert len(streams) == 2 and streams[0].aborted.is_set()


def test_pcm_buffer() -> None:
    buf = PcmBuffer()
    buf.write(b"abcd")
    assert buf.read(3) == b"abc" and len(buf) == 1
    buf.clear()
    assert buf.read(4) == b""
