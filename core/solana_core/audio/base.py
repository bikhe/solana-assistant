"""Audio contracts: input stream, voice activity detection and playback.

Audio everywhere in the core is 16 kHz, mono, signed 16-bit little-endian PCM.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass

SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2  # bytes, int16
CHANNELS = 1
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * SAMPLE_WIDTH


@dataclass(frozen=True, slots=True)
class AudioDevice:
    id: str
    name: str
    is_default: bool = False


class AudioSource(ABC):
    """A live stream of PCM frames, usually the microphone."""

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def frames(self) -> AsyncIterator[bytes]:
        """Yield frames of ``FRAME_BYTES`` until stopped."""

    async def list_devices(self) -> list[AudioDevice]:
        return []


class VoiceActivityDetector(ABC):
    """Decides whether a frame contains speech."""

    @abstractmethod
    def is_speech(self, frame: bytes) -> bool: ...

    def reset(self) -> None:  # noqa: B027 - optional hook
        """Forget internal state between utterances."""


class AudioSink(ABC):
    """Plays PCM audio and can stop instantly (barge-in)."""

    @abstractmethod
    async def play(self, chunks: AsyncIterator[bytes], sample_rate: int = SAMPLE_RATE) -> None:
        """Play chunks until they end or ``stop()`` is called."""

    @abstractmethod
    async def stop(self) -> None: ...


class FakeAudioSource(AudioSource):
    """Replays given frames, e.g. read from a WAV fixture."""

    def __init__(self, frames: Iterable[bytes], realtime: bool = False) -> None:
        self._frames = list(frames)
        self._realtime = realtime
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def frames(self) -> AsyncIterator[bytes]:
        for frame in self._frames:
            if not self._running:
                return
            if self._realtime:
                await asyncio.sleep(FRAME_MS / 1000)
            yield frame


class FakeVAD(VoiceActivityDetector):
    """Speech is any frame whose first byte is not zero. Silence fixtures are all zeros."""

    def is_speech(self, frame: bytes) -> bool:
        return any(frame)


class FakeAudioSink(AudioSink):
    """Collects played audio in memory."""

    def __init__(self) -> None:
        self.played: list[bytes] = []
        self.stopped = False

    async def play(self, chunks: AsyncIterator[bytes], sample_rate: int = SAMPLE_RATE) -> None:
        self.stopped = False
        async for chunk in chunks:
            if self.stopped:
                return
            self.played.append(chunk)

    async def stop(self) -> None:
        self.stopped = True
