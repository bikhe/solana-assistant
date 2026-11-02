"""Test doubles for the voice pipeline that work on real audio, without models.

A scenario is a WAV file made of tones: a 3 kHz beep stands for the wake word and each
"word" is a voice-like burst with its own pitch. ``ToneWakeDetector`` and ``ToneSTT``
recognize them by frequency, so the pipeline runs on audio exactly as it would on a mic.
Source and sink are paced at ``speed`` times real time, so playback and listening overlap
the way they do live (barge-in), only faster.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import numpy as np

from solana_core.audio.base import (
    FRAME_BYTES,
    FRAME_MS,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    AudioSink,
    AudioSource,
)
from solana_core.audio.wav import Pcm, read_wav, to_frames, write_wav
from solana_core.protocol import Language
from solana_core.stt.base import STTProvider, Transcript
from solana_core.wake.base import WakeDetection, WakeWordDetector
from tests.audio_fixtures import noise

WAKE_HZ = 3000.0


def tone(seconds: float, hz: float = WAKE_HZ, level: float = 8000.0) -> Pcm:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (np.sin(2 * np.pi * hz * t) * level).astype(np.int16)


def voice(seconds: float, f0: float, level: float = 6000.0) -> Pcm:
    """A vowel-like burst: harmonics of ``f0`` with a slow amplitude wobble."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    wave = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 6))
    envelope = 0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)
    return (wave * envelope * level / 2).astype(np.int16)


class Script:
    """Builds a scenario recording piece by piece."""

    def __init__(self) -> None:
        self.parts: list[Pcm] = []
        self._seed = 0

    @property
    def seconds(self) -> float:
        return sum(len(p) for p in self.parts) / SAMPLE_RATE

    def pause(self, seconds: float) -> Script:
        self._seed += 1
        self.parts.append(noise(seconds, seed=self._seed))
        return self

    def zeros(self, seconds: float) -> Script:
        self.parts.append(np.zeros(int(seconds * SAMPLE_RATE), dtype=np.int16))
        return self

    def wake(self) -> Script:
        self.parts.append(tone(0.5))
        return self

    def say(self, f0: float, seconds: float = 0.8) -> Script:
        self.parts.append(voice(seconds, f0))
        return self

    def save(self, path: Path) -> Path:
        write_wav(path, np.concatenate(self.parts))
        return path


def _goertzel_ratio(samples: np.ndarray, hz: float) -> float:
    """Share of the frame's energy at ``hz``."""
    x = samples.astype(np.float64)
    energy = float(np.dot(x, x))
    if energy == 0:
        return 0.0
    n = len(x)
    t = np.arange(n)
    re = float(np.dot(x, np.cos(2 * np.pi * hz * t / SAMPLE_RATE)))
    im = float(np.dot(x, np.sin(2 * np.pi * hz * t / SAMPLE_RATE)))
    return 2 * (re * re + im * im) / (n * energy)


class ToneWakeDetector(WakeWordDetector):
    """Fires when a 3 kHz beep of at least ``min_ms`` ends, like a model firing after the
    wake word has been said."""

    def __init__(self, min_ms: int = 200) -> None:
        self.min_frames = min_ms // FRAME_MS
        self.detections = 0
        self._run = 0

    def process(self, frame: bytes) -> WakeDetection | None:
        samples = np.frombuffer(frame, dtype=np.int16)
        if _goertzel_ratio(samples, WAKE_HZ) > 0.5:
            self._run += 1
            return None
        fired = self._run >= self.min_frames
        self._run = 0
        if fired:
            self.detections += 1
            return WakeDetection("эй_солана", 0.99)
        return None

    def reset(self) -> None:
        self._run = 0


class ToneSTT(STTProvider):
    """Maps the pitch of the loudest voice burst to a phrase. The wake beep is ignored."""

    name = "tone"

    def __init__(self, words: Mapping[float, str], language: Language = "ru") -> None:
        self.words = dict(words)
        self.language: Language = language
        self.calls = 0

    def pitch(self, audio: bytes) -> float | None:
        samples = np.frombuffer(audio, dtype=np.int16).astype(np.float64)
        if len(samples) < SAMPLE_RATE // 10:
            return None
        spectrum = np.abs(np.fft.rfft(samples))
        freqs = np.fft.rfftfreq(len(samples), 1 / SAMPLE_RATE)
        band = (freqs > 80) & (freqs < 1000)
        if not band.any() or spectrum[band].max() < 1e5 * len(samples) / SAMPLE_RATE:
            return None
        return float(freqs[band][np.argmax(spectrum[band])])

    async def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript:
        self.calls += 1
        pitch = self.pitch(audio)
        text = ""
        if pitch is not None:
            best = min(self.words, key=lambda f: abs(f - pitch))
            if abs(best - pitch) <= 8:
                text = self.words[best]
        return Transcript(text, language or self.language)

    async def stream(
        self, frames: AsyncIterator[bytes], language: Language | None = None
    ) -> AsyncIterator[Transcript]:
        audio = bytearray()
        partial_sent = False
        async for frame in frames:
            audio += frame
            if not partial_sent and len(audio) >= SAMPLE_RATE * SAMPLE_WIDTH // 2:
                partial = await self.transcribe(bytes(audio), language)
                if partial.text:
                    partial_sent = True
                    yield Transcript(partial.text.split()[0], partial.language, final=False)
        yield await self.transcribe(bytes(audio), language)


class _Pacer:
    def __init__(self, speed: float) -> None:
        self.speed = speed
        self._start: float | None = None
        self._audio_s = 0.0

    def restart(self) -> None:
        self._start = None
        self._audio_s = 0.0

    async def advance(self, seconds: float) -> None:
        loop = asyncio.get_running_loop()
        if self._start is None:
            self._start = loop.time()
        self._audio_s += seconds
        target = self._start + self._audio_s / self.speed
        await asyncio.sleep(max(0.0, target - loop.time()))


class PacedSource(AudioSource):
    """Plays a WAV file as a microphone, ``speed`` times faster than real time."""

    def __init__(self, path: Path, speed: float = 8.0) -> None:
        self.frames_list = to_frames(read_wav(path).tobytes(), FRAME_BYTES)
        self._pacer = _Pacer(speed)
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def frames(self) -> AsyncIterator[bytes]:
        for frame in self.frames_list:
            if not self._running:
                return
            await self._pacer.advance(FRAME_MS / 1000)
            yield frame


class PacedSink(AudioSink):
    """Takes as long to play as the audio lasts (divided by ``speed``) and can be stopped."""

    def __init__(self, speed: float = 8.0) -> None:
        self.speed = speed
        self.played = bytearray()
        self.stops = 0
        self.plays = 0
        self._stopped = asyncio.Event()

    @property
    def played_s(self) -> float:
        return len(self.played) / (SAMPLE_RATE * SAMPLE_WIDTH)

    async def play(self, chunks: AsyncIterator[bytes], sample_rate: int = SAMPLE_RATE) -> None:
        self.plays += 1
        self._stopped = stopped = asyncio.Event()
        pacer = _Pacer(self.speed)
        async for chunk in chunks:
            if stopped.is_set():
                return
            self.played += chunk
            await pacer.advance(len(chunk) / (sample_rate * SAMPLE_WIDTH))

    async def stop(self) -> None:
        self.stops += 1
        self._stopped.set()
