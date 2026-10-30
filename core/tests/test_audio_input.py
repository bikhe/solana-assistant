"""WP1 audio input: ring buffer, WAV helpers, resampling, VAD and the microphone source."""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from solana_core.audio import mic
from solana_core.audio.base import FRAME_BYTES, SAMPLE_RATE
from solana_core.audio.mic import SoundDeviceSource, StreamResampler
from solana_core.audio.ring import RingBuffer
from solana_core.audio.vad import EnergyVAD, SileroVAD
from solana_core.audio.wav import read_wav, resample, rms, to_frames, write_wav
from tests.audio_fixtures import burst, noise, phrase_wav, silence


def pcm(values: list[int]) -> bytes:
    return np.array(values, dtype=np.int16).tobytes()


def test_ring_buffer_keeps_the_latest_audio() -> None:
    ring = RingBuffer(seconds=1.0, sample_rate=4)  # 4 samples
    ring.write(pcm([1, 2, 3]))
    assert ring.read() == pcm([1, 2, 3])
    ring.write(pcm([4, 5]))
    assert len(ring) == 4
    assert ring.read() == pcm([2, 3, 4, 5])
    assert ring.read(seconds=0.5) == pcm([4, 5])
    ring.write(pcm([6, 7, 8, 9, 10, 11]))
    assert ring.read() == pcm([8, 9, 10, 11])
    ring.clear()
    assert ring.read() == b""


def test_ring_buffer_default_holds_two_seconds() -> None:
    ring = RingBuffer()
    for _ in range(150):  # 3 s of frames
        ring.write(bytes(FRAME_BYTES))
    assert len(ring) == 2 * SAMPLE_RATE


def test_wav_round_trip_and_frames(tmp_path: Path) -> None:
    samples = burst(0.5)
    write_wav(tmp_path / "a.wav", samples)
    assert np.array_equal(read_wav(tmp_path / "a.wav"), samples)
    frames = to_frames(samples[:500])
    assert [len(f) for f in frames] == [FRAME_BYTES, FRAME_BYTES]
    assert frames[1][360:] == bytes(FRAME_BYTES - 360)  # padded with silence


def test_read_wav_converts_stereo_48k_and_24_bit(tmp_path: Path) -> None:
    t = np.arange(48_000) / 48_000
    tone = (np.sin(2 * np.pi * 440 * t) * 10_000).astype(np.int32)
    path = tmp_path / "stereo24.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(3)
        wav.setframerate(48_000)
        stereo = np.repeat(tone << 8, 2)
        raw = np.stack([(stereo >> s) & 0xFF for s in (0, 8, 16)], axis=1).astype(np.uint8)
        wav.writeframes(raw.tobytes())
    out = read_wav(path)
    assert len(out) == SAMPLE_RATE
    expected = resample(tone, 48_000)
    assert np.max(np.abs(out.astype(int) - expected.astype(int))) <= 2


def test_stream_resampler_matches_offline_resampling() -> None:
    t = np.arange(48_000) / 48_000
    tone = (np.sin(2 * np.pi * 300 * t) * 8000).astype(np.int16)
    resampler = StreamResampler(48_000)
    chunks = [resampler.process(tone[i : i + 441]) for i in range(0, len(tone), 441)]
    streamed = np.concatenate(chunks)
    assert abs(len(streamed) - SAMPLE_RATE) <= 1
    offline = resample(tone, 48_000)
    n = min(len(streamed), len(offline)) - 1
    # The stream is shifted by one input sample (it starts from a zero), nothing more.
    assert np.max(np.abs(streamed[1:n].astype(int) - offline[1:n].astype(int))) < 400


def test_energy_vad_on_wav_fixture(tmp_path: Path) -> None:
    frames = to_frames(read_wav(phrase_wav(tmp_path / "phrase.wav")))
    vad = EnergyVAD(threshold=300, hangover_ms=200)
    speech = [vad.is_speech(f) for f in frames]
    first, last = speech.index(True), len(speech) - 1 - speech[::-1].index(True)
    assert first == 50  # speech starts at 1 s
    assert last == 99 + 10  # ends at 2 s plus 200 ms hangover
    assert rms(frames[0]) < 50


class FakeSilero:
    """Stands in for the Silero ONNX model: probability grows with loudness."""

    def __init__(self) -> None:
        self.inputs: list[dict[str, Any]] = []

    def __call__(self, feed: dict[str, Any]) -> list[Any]:
        self.inputs.append(feed)
        level = float(np.sqrt(np.mean((feed["input"][0, 64:] * 32768) ** 2)))
        prob = min(level / 1000.0, 1.0)
        return [np.array([[prob]], dtype=np.float32), feed["state"] + 1]


def test_silero_vad_windows_context_and_quiet_skip(tmp_path: Path) -> None:
    model = FakeSilero()
    vad = SileroVAD(model, threshold=0.5, min_rms=60)
    frames = to_frames(read_wav(phrase_wav(tmp_path / "phrase.wav")))
    quiet = [vad.is_speech(f) for f in frames[:50]]
    assert not any(quiet)
    assert vad.model_calls == 0  # silence never reaches the model
    loud = [vad.is_speech(f) for f in frames[50:100]]
    assert sum(loud) > 40
    assert all(feed["input"].shape == (1, 576) for feed in model.inputs)
    assert model.inputs[-1]["sr"] == SAMPLE_RATE
    assert float(model.inputs[-1]["state"][0, 0, 0]) == len(model.inputs) - 1  # state carried
    tail = [vad.is_speech(f) for f in frames[100:]]
    assert not tail[-1]
    vad.reset()
    assert vad.probability == 0.0


def test_silero_vad_hysteresis() -> None:
    probs = iter([0.6, 0.4, 0.3, 0.6, 0.2])

    def model(feed: dict[str, Any]) -> list[Any]:
        return [np.array([[next(probs)]]), feed["state"]]

    vad = SileroVAD(model, threshold=0.5, min_rms=0)
    window = burst(0.032)[:512].tobytes()
    # 0.4 stays above threshold - 0.15, 0.3 drops below it.
    assert [vad.is_speech(window) for _ in range(5)] == [True, True, False, True, False]


class FakeSoundDevice:
    """The few parts of the ``sounddevice`` module the source uses."""

    class PortAudioError(Exception):
        pass

    def __init__(self, native_rate: int | None = None) -> None:
        self.native_rate = native_rate
        self.default = SimpleNamespace(hostapi=0, device=(1, 3))
        self.streams: list[FakeStream] = []

    def query_devices(self, index: int | None = None, kind: str | None = None) -> Any:
        devices = [
            {"name": "Speakers", "max_input_channels": 0, "hostapi": 0},
            {"name": "Microphone (USB)", "max_input_channels": 1, "hostapi": 0},
            {"name": "Microphone (USB)", "max_input_channels": 1, "hostapi": 1},
            {"name": "Headset Mic", "max_input_channels": 2, "hostapi": 0},
        ]
        if index is None and kind is None:
            return devices
        index = self.default.device[0] if index is None else index
        return {**devices[index], "default_samplerate": self.native_rate or SAMPLE_RATE}

    def InputStream(self, **kwargs: Any) -> FakeStream:
        if self.native_rate and kwargs["samplerate"] != self.native_rate:
            raise self.PortAudioError("Invalid sample rate")
        stream = FakeStream(kwargs)
        self.streams.append(stream)
        return stream


class FakeStream:
    def __init__(self, kwargs: dict[str, Any]) -> None:
        self.kwargs = kwargs
        self.started = self.closed = False

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True

    def feed(self, samples: np.ndarray) -> None:
        self.kwargs["callback"](samples.reshape(-1, 1), len(samples), None, None)


@pytest.fixture
def fake_sd(monkeypatch: pytest.MonkeyPatch) -> FakeSoundDevice:
    sd = FakeSoundDevice()
    monkeypatch.setattr(mic, "_sounddevice", lambda: sd)
    return sd


async def collect(source: SoundDeviceSource, count: int) -> list[bytes]:
    out: list[bytes] = []
    async for frame in source.frames():
        out.append(frame)
        if len(out) == count:
            break
    return out


def test_device_listing_and_resolution(fake_sd: FakeSoundDevice) -> None:
    devices = mic.list_input_devices()
    assert [(d.id, d.is_default) for d in devices] == [
        ("Microphone (USB)", True),
        ("Headset Mic", False),
    ]
    assert mic.resolve_device(None) is None
    assert mic.resolve_device("Headset Mic") == 3
    assert mic.resolve_device("usb") == 1
    assert mic.resolve_device("Nope") is None


async def test_microphone_frames_and_history(fake_sd: FakeSoundDevice) -> None:
    source = SoundDeviceSource("Headset")
    await source.start()
    stream = fake_sd.streams[0]
    assert stream.started and stream.kwargs["device"] == 3
    assert stream.kwargs["samplerate"] == SAMPLE_RATE and stream.kwargs["dtype"] == "int16"
    audio = burst(0.1)  # 1600 samples, delivered in odd-sized blocks
    for i in range(0, len(audio), 700):
        stream.feed(audio[i : i + 700])
    frames = await asyncio.wait_for(collect(source, 5), 1)
    assert b"".join(frames) == audio.tobytes()
    assert source.history.read() == audio.tobytes()
    await source.stop()
    assert stream.closed
    assert [f async for f in source.frames()] == []


async def test_microphone_falls_back_to_native_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    sd = FakeSoundDevice(native_rate=48_000)
    monkeypatch.setattr(mic, "_sounddevice", lambda: sd)
    source = SoundDeviceSource()
    await source.start()
    stream = sd.streams[0]
    assert stream.kwargs["samplerate"] == 48_000
    stream.feed(np.resize(burst(0.01), 48_000))  # 1 s at 48 kHz
    frames = await asyncio.wait_for(collect(source, 49), 1)
    assert all(len(f) == FRAME_BYTES for f in frames)
    await source.stop()


async def test_microphone_drops_oldest_frames_when_nobody_reads(
    fake_sd: FakeSoundDevice,
) -> None:
    source = SoundDeviceSource()
    await source.start()
    fake_sd.streams[0].feed(np.concatenate([silence(10.0), noise(1.0, level=1000)]))
    await asyncio.sleep(0)
    assert source.dropped_frames == 50
    await source.stop()
