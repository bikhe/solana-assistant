"""Recognizers on WAV fixtures. Engines are replaced by small fakes: no models, no network."""

from __future__ import annotations

import asyncio
import sys
import types
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, ClassVar

import httpx
import numpy as np
import pytest

from solana_core.audio.base import FRAME_BYTES
from solana_core.config import MemorySecretStore
from solana_core.models import CATALOG, Hardware, ModelError, ModelManager
from solana_core.protocol import Language
from solana_core.stt import FakeSTT, create_stt
from solana_core.stt.audio import (
    duration_s,
    float32_to_pcm16,
    guess_language,
    normalize_language,
    pcm16_to_float32,
    pcm16_to_wav,
    read_wav,
    resample_pcm16,
)
from solana_core.stt.base import Transcript
from solana_core.stt.openai import OpenAISTT
from solana_core.stt.streaming import ChunkedStreamingSTT
from solana_core.stt.whisper_cpp import WhisperCppError, WhisperCppSTT

FIXTURE = Path(__file__).parent / "fixtures" / "utterance_16k.wav"


@pytest.fixture
def utterance() -> bytes:
    pcm, rate = read_wav(str(FIXTURE))
    assert rate == 16_000
    return pcm


def frames_of(pcm: bytes) -> list[bytes]:
    return [pcm[i : i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)]


async def feed(frames: list[bytes], delay: float = 0.0) -> AsyncIterator[bytes]:
    for frame in frames:
        if delay:
            await asyncio.sleep(delay)
        yield frame


def test_pcm_helpers(utterance: bytes) -> None:
    assert duration_s(utterance) == pytest.approx(1.0)
    samples = pcm16_to_float32(utterance)
    assert samples.dtype == np.float32 and float(np.abs(samples).max()) <= 1.0
    back = np.frombuffer(float32_to_pcm16(samples), dtype="<i2").astype(int)
    assert np.abs(back - np.frombuffer(utterance, dtype="<i2")).max() <= 1
    pcm, rate = read_wav(pcm16_to_wav(utterance))
    assert (pcm, rate) == (utterance, 16_000)
    up = resample_pcm16(utterance, 16_000, 24_000)
    assert len(up) == len(utterance) * 3 // 2


def test_language_helpers() -> None:
    assert normalize_language("Russian") == "ru"
    assert normalize_language("en-US") == "en"
    assert normalize_language("de") is None
    assert guess_language("Включи музыку") == "ru"
    assert guess_language("play some music") == "en"
    assert guess_language("Открой YouTube") == "ru"
    assert guess_language("123") is None


class SlowSTT(ChunkedStreamingSTT):
    """Returns how many seconds of audio it saw, after a delay."""

    name = "slow"
    partial_interval_s = 0.2
    min_partial_s = 0.2

    def __init__(self, delay: float, final_delay: float = 0.0) -> None:
        self.delay = delay
        self.final_delay = final_delay
        self.calls = 0

    async def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript:
        self.calls += 1
        await asyncio.sleep(self.delay if duration_s(audio) < 1.0 else self.final_delay)
        return Transcript(f"{duration_s(audio):.1f}", language or "ru")


async def test_chunked_streaming_yields_partials_then_final(utterance: bytes) -> None:
    stt = SlowSTT(delay=0.001)
    results = [t async for t in stt.stream(feed(frames_of(utterance), delay=0.002))]
    assert results[-1] == Transcript("1.0", "ru", final=True)
    partials = results[:-1]
    assert partials and all(not t.final for t in partials)
    assert len({t.text for t in partials}) == len(partials)


async def test_chunked_streaming_skips_partials_on_slow_machine(utterance: bytes) -> None:
    stt = SlowSTT(delay=10)
    results = [t async for t in stt.stream(feed(frames_of(utterance), delay=0.001))]
    # The one partial never finished: it was cancelled and only the final result came out.
    assert [t.final for t in results] == [True]
    assert stt.calls == 2


async def test_fake_stt_contract() -> None:
    results = [t async for t in FakeSTT("открой браузер").stream(feed([b"\x01" * 4]))]
    assert results[-1].text == "открой браузер"


# faster-whisper


class FakeWhisperModel:
    instances: ClassVar[list[FakeWhisperModel]] = []

    def __init__(self, path: str, **kwargs: Any) -> None:
        self.path, self.kwargs = path, kwargs
        self.calls: list[str | None] = []
        FakeWhisperModel.instances.append(self)

    def transcribe(self, audio: Any, language: str | None = None, **_: Any) -> Any:
        self.calls.append(language)
        info = types.SimpleNamespace(
            language="uk" if language is None else language,
            all_language_probs=[("uk", 0.5), ("ru", 0.4), ("en", 0.1)],
        )
        text = {"ru": " привет", "en": " hello"}.get(language or "", " привіт")
        segments: Iterator[Any] = iter(
            [types.SimpleNamespace(text=text), types.SimpleNamespace(text=" мир")]
        )
        return segments, info


@pytest.fixture
def fake_faster_whisper(monkeypatch: pytest.MonkeyPatch) -> type[FakeWhisperModel]:
    FakeWhisperModel.instances = []
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return FakeWhisperModel


async def test_faster_whisper_keeps_to_ru_and_en(
    fake_faster_whisper: type[FakeWhisperModel], utterance: bytes
) -> None:
    from solana_core.stt.faster_whisper import FasterWhisperSTT

    stt = FasterWhisperSTT("/models/fw", cpu_threads=2)
    result = await stt.transcribe(utterance)
    model = fake_faster_whisper.instances[0]
    assert model.kwargs == {"device": "cpu", "compute_type": "int8", "cpu_threads": 2}
    # Detected Ukrainian, so it decoded again as the likelier of ru/en.
    assert model.calls == [None, "ru"]
    assert result == Transcript("привет мир", "ru")

    assert (await stt.transcribe(utterance, "en")).text == "hello мир"
    assert len(fake_faster_whisper.instances) == 1


# GigaAM


async def test_gigaam_is_russian(monkeypatch: pytest.MonkeyPatch, utterance: bytes) -> None:
    loaded: dict[str, Any] = {}

    class Model:
        def recognize(self, waveform: Any, sample_rate: int) -> str:
            assert waveform.dtype == np.float32 and sample_rate == 16_000
            return " включи свет "

    def load_model(name: str, path: str, quantization: str | None = None) -> Model:
        loaded.update(name=name, path=path, quantization=quantization)
        return Model()

    module = types.ModuleType("onnx_asr")
    module.load_model = load_model  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnx_asr", module)
    from solana_core.stt.gigaam import GigaAMSTT

    stt = GigaAMSTT("/models/giga")
    assert await stt.transcribe(utterance, "en") == Transcript("включи свет", "ru")
    assert loaded == {"name": "gigaam-v3-ctc", "path": "/models/giga", "quantization": "int8"}
    assert await stt.transcribe(b"") == Transcript("", "ru")


# HTTP engines


def multipart_fields(request: httpx.Request) -> bytes:
    return request.read()


async def test_openai_stt(utterance: bytes) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": " Привет, Солана "})

    stt = OpenAISTT("sk-test", transport=httpx.MockTransport(handler))
    result = await stt.transcribe(utterance)
    await stt.close()
    assert result == Transcript("Привет, Солана", "ru")
    request = seen[0]
    assert request.url == "https://api.openai.com/v1/audio/transcriptions"
    assert request.headers["Authorization"] == "Bearer sk-test"
    body = request.read()
    assert b"gpt-4o-mini-transcribe" in body and b"RIFF" in body
    assert b'name="language"' not in body


async def test_whisper_cpp_server(utterance: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/inference"
        body = request.read()
        assert b"verbose_json" in body and b"RIFF" in body
        lang = b"en" if b"\r\n\r\nen\r\n" in body else b"auto"
        if lang == b"en":
            return httpx.Response(200, json={"text": "turn it up"})
        return httpx.Response(200, json={"text": " сделай погромче", "language": "russian"})

    stt = WhisperCppSTT(base_url="http://127.0.0.1:9", transport=httpx.MockTransport(handler))
    assert await stt.transcribe(utterance) == Transcript("сделай погромче", "ru")
    assert await stt.transcribe(utterance, "en") == Transcript("turn it up", "en")
    await stt.close()


async def test_whisper_cpp_reports_server_error(utterance: bytes) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"error": "bad audio"}))
    stt = WhisperCppSTT(base_url="http://127.0.0.1:9", transport=transport)
    with pytest.raises(WhisperCppError, match="bad audio"):
        await stt.transcribe(utterance)


async def test_whisper_cpp_needs_binary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("solana_core.stt.whisper_cpp.find_whisper_server", lambda: None)
    stt = WhisperCppSTT(tmp_path / "model.bin")
    with pytest.raises(WhisperCppError, match="not found"):
        await stt.load()
    with pytest.raises(ValueError):
        WhisperCppSTT()


# Factory


def installed_manager(tmp_path: Path, *model_ids: str) -> ModelManager:
    mm = ModelManager(tmp_path, CATALOG)
    for model_id in model_ids:
        folder = mm.path(model_id)
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text('{"sha256": {}}')
    return mm


def test_create_stt(tmp_path: Path, fake_faster_whisper: type[FakeWhisperModel]) -> None:
    secrets = MemorySecretStore()
    secrets.set("openai", "sk")
    hw = Hardware(8, 16)
    mm = installed_manager(tmp_path, "faster-whisper-small", "whisper-cpp-small")

    assert isinstance(create_stt("fake", models=mm, secrets=secrets), FakeSTT)
    assert isinstance(create_stt("openai", models=mm, secrets=secrets), OpenAISTT)
    stt = create_stt("faster-whisper", models=mm, secrets=secrets, hardware=hw)
    assert stt.name == "faster-whisper"
    assert create_stt("whisper.cpp", models=mm, secrets=secrets, hardware=hw).name == "whisper.cpp"

    with pytest.raises(ModelError, match="не скачана"):
        create_stt("gigaam", models=mm, secrets=secrets, hardware=hw)
    with pytest.raises(ModelError, match="не подходит"):
        create_stt("gigaam", models=mm, secrets=secrets, model_id="faster-whisper-small")
    with pytest.raises(ValueError):
        create_stt("vosk", models=mm, secrets=secrets)
