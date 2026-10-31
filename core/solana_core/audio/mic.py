"""Microphone capture through sounddevice (PortAudio): 16 kHz mono int16, 20 ms frames.

``sounddevice`` is imported lazily: on Linux it needs the system PortAudio library
(``libportaudio2``), and tests never touch the real microphone.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

import numpy as np
from numpy.typing import NDArray

from solana_core.audio.base import (
    FRAME_BYTES,
    FRAME_MS,
    SAMPLE_RATE,
    AudioDevice,
    AudioSource,
)
from solana_core.audio.ring import RingBuffer

log = logging.getLogger(__name__)

FRAME_SAMPLES = FRAME_BYTES // 2
QUEUE_FRAMES = 10_000 // FRAME_MS  # 10 s of backlog before we start dropping old frames


class AudioUnavailableError(RuntimeError):
    """The microphone cannot be opened. The message is user-facing (Russian)."""


def _sounddevice() -> Any:
    try:
        import sounddevice
    except OSError as e:  # PortAudio library missing
        raise AudioUnavailableError(
            "Не найдена библиотека PortAudio. В Linux установите пакет libportaudio2."
        ) from e
    return sounddevice


class StreamResampler:
    """Streaming linear resampler for devices that cannot record at 16 kHz."""

    def __init__(self, src_rate: int, dst_rate: int = SAMPLE_RATE) -> None:
        self.step = src_rate / dst_rate
        self._pos = 0.0  # position of the next output sample, relative to ``_last``
        self._last = 0.0  # last input sample of the previous chunk, index -1

    def process(self, samples: NDArray[np.int16]) -> NDArray[np.int16]:
        if self.step == 1.0:
            return np.asarray(samples, dtype=np.int16)
        x = np.concatenate(([self._last], samples.astype(np.float64)))
        positions = np.arange(self._pos, len(x) - 1, self.step)
        out: NDArray[np.float64] = np.interp(positions, np.arange(len(x)), x)
        self._pos = (positions[-1] + self.step if len(positions) else self._pos) - (len(x) - 1)
        self._last = float(x[-1])
        return np.clip(out, -32768, 32767).astype(np.int16)


def list_input_devices() -> list[AudioDevice]:
    """Input devices of the default host API (avoids MME/DirectSound/WASAPI duplicates)."""
    sd = _sounddevice()
    default_api = sd.default.hostapi
    default_in = sd.default.device[0]
    devices: list[AudioDevice] = []
    for index, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] < 1 or info["hostapi"] != default_api:
            continue
        devices.append(AudioDevice(info["name"], info["name"], index == default_in))
    return devices


def resolve_device(device: str | None) -> int | None:
    """Device index for a name from settings; ``None`` means the system default.

    Exact name wins, then a case-insensitive substring. Unknown names fall back to default.
    """
    if not device:
        return None
    sd = _sounddevice()
    inputs = [(i, d) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
    for index, info in inputs:
        if info["name"] == device:
            return index
    for index, info in inputs:
        if device.lower() in info["name"].lower():
            return index
    log.warning("input device %r not found, using the default one", device)
    return None


class SoundDeviceSource(AudioSource):
    """Live microphone. Keeps the last 2 s in ``history`` for the pipeline's pre-roll."""

    def __init__(self, device: str | None = None, history_seconds: float = 2.0) -> None:
        self.device = device
        self.history = RingBuffer(history_seconds)
        self.dropped_frames = 0
        self._stream: Any = None
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(QUEUE_FRAMES)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending = np.zeros(0, dtype=np.int16)
        self._resampler: StreamResampler | None = None

    async def list_devices(self) -> list[AudioDevice]:
        return await asyncio.to_thread(list_input_devices)

    async def start(self) -> None:
        if self._stream is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(QUEUE_FRAMES)
        self._stream = await asyncio.to_thread(self._open)

    def _open(self) -> Any:
        sd = _sounddevice()
        index = resolve_device(self.device)
        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                blocksize=FRAME_SAMPLES,
                device=index,
                channels=1,
                dtype="int16",
                callback=self._callback,
            )
            self._resampler = None
        except sd.PortAudioError:
            # Many devices only do 44.1/48 kHz natively; record at their rate and convert.
            rate = int(sd.query_devices(index, "input")["default_samplerate"])
            log.info("device does not support 16 kHz, recording at %d Hz", rate)
            self._resampler = StreamResampler(rate)
            try:
                stream = sd.InputStream(
                    samplerate=rate,
                    blocksize=rate * FRAME_MS // 1000,
                    device=index,
                    channels=1,
                    dtype="int16",
                    callback=self._callback,
                )
            except sd.PortAudioError as e:
                msg = f"Не удалось открыть микрофон: {e}"
                raise AudioUnavailableError(msg) from e
        stream.start()
        return stream

    def _callback(self, indata: np.ndarray, frames: int, time: Any, status: Any) -> None:
        # Runs on the PortAudio thread: cut into exact frames and hand over to the loop.
        samples = indata[:, 0]
        if self._resampler is not None:
            samples = self._resampler.process(samples)
        self._pending = np.concatenate((self._pending, samples))
        while len(self._pending) >= FRAME_SAMPLES:
            frame = self._pending[:FRAME_SAMPLES].tobytes()
            self._pending = self._pending[FRAME_SAMPLES:]
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._put, frame)

    def _put(self, frame: bytes | None) -> None:
        if self._queue.full():
            self._queue.get_nowait()
            self.dropped_frames += 1
        self._queue.put_nowait(frame)

    async def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(stream.close)
        self._put(None)

    async def frames(self) -> AsyncIterator[bytes]:
        while True:
            frame = await self._queue.get()
            if frame is None:
                return
            self.history.write(frame)
            yield frame
