"""Speaker output that can be cut off mid-word (barge-in).

Audio goes through a small buffer (``max_buffer_s``) into a PortAudio callback stream.
``stop()`` drops the buffer and aborts the stream, so the sound ends within one device
block instead of after the queued audio.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

from solana_core.audio.base import SAMPLE_RATE, SAMPLE_WIDTH, AudioDevice, AudioSink

# Fills the output buffer; returns False once playback is complete.
FillCallback = Callable[[memoryview], bool]


class OutputStream(Protocol):
    def start(self) -> None: ...
    def abort(self) -> None: ...
    def close(self) -> None: ...


StreamFactory = Callable[[int, int, str | None, FillCallback, Callable[[], None]], OutputStream]


class PcmBuffer:
    """Byte FIFO shared by the event loop (writer) and the audio thread (reader)."""

    def __init__(self) -> None:
        self._data = bytearray()
        self._lock = threading.Lock()
        self.eof = False

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def write(self, data: bytes) -> None:
        with self._lock:
            self._data += data

    def read(self, n: int) -> bytes:
        with self._lock:
            out = bytes(self._data[:n])
            del self._data[:n]
            return out

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class SoundDeviceSink(AudioSink):
    def __init__(
        self,
        device: str | None = None,
        *,
        block_ms: int = 20,
        max_buffer_s: float = 0.3,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        self.device = device
        self.block_ms = block_ms
        self.max_buffer_s = max_buffer_s
        self._factory = stream_factory or _sounddevice_stream
        self._stream: OutputStream | None = None
        self._buffer: PcmBuffer | None = None
        self._stopped = asyncio.Event()
        self._lock = asyncio.Lock()

    @property
    def playing(self) -> bool:
        return self._stream is not None

    async def play(self, chunks: AsyncIterator[bytes], sample_rate: int = SAMPLE_RATE) -> None:
        await self.stop()
        async with self._lock:
            self._stopped = stopped = asyncio.Event()
            loop = asyncio.get_running_loop()
            finished = asyncio.Event()
            buffer = self._buffer = PcmBuffer()

            def fill(out: memoryview) -> bool:
                data = buffer.read(len(out))
                out[: len(data)] = data
                out[len(data) :] = bytes(len(out) - len(data))
                return not (buffer.eof and not data)

            def on_finished() -> None:
                with contextlib.suppress(RuntimeError):  # the loop may be gone at shutdown
                    loop.call_soon_threadsafe(finished.set)

            blocksize = sample_rate * self.block_ms // 1000
            limit = int(sample_rate * SAMPLE_WIDTH * self.max_buffer_s)
            stream = self._stream = self._factory(
                sample_rate, blocksize, self.device, fill, on_finished
            )
            stream.start()
            try:
                async for chunk in chunks:
                    if stopped.is_set():
                        break
                    buffer.write(chunk)
                    # The audio thread drains the buffer; polling keeps it lock-free.
                    while len(buffer) > limit and not stopped.is_set():  # noqa: ASYNC110
                        await asyncio.sleep(self.block_ms / 2000)
                buffer.eof = True
                if not stopped.is_set():
                    await _first(finished.wait(), stopped.wait())
            finally:
                buffer.eof = True
                buffer.clear()
                with contextlib.suppress(Exception):
                    stream.abort()
                    stream.close()
                self._stream = self._buffer = None
                if aclose := getattr(chunks, "aclose", None):
                    with contextlib.suppress(Exception):
                        await aclose()

    async def stop(self) -> None:
        """Silence now. Safe to call when nothing is playing."""
        self._stopped.set()
        if self._buffer is not None:
            self._buffer.clear()
        if self._stream is not None:
            with contextlib.suppress(Exception):
                self._stream.abort()

    async def list_devices(self) -> list[AudioDevice]:
        import sounddevice as sd

        default_out = sd.default.device[1]
        return [
            AudioDevice(str(i), str(d["name"]), i == default_out)
            for i, d in enumerate(sd.query_devices())
            if d["max_output_channels"] > 0
        ]


async def _first(*aws: Any) -> None:
    tasks = [asyncio.ensure_future(a) for a in aws]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()


def _sounddevice_stream(
    sample_rate: int,
    blocksize: int,
    device: str | None,
    fill: FillCallback,
    on_finished: Callable[[], None],
) -> OutputStream:
    import sounddevice as sd

    def callback(outdata: Any, frames: int, time: Any, status: Any) -> None:
        if not fill(memoryview(outdata).cast("B")):
            raise sd.CallbackStop

    stream: OutputStream = sd.RawOutputStream(
        samplerate=sample_rate,
        blocksize=blocksize,
        device=int(device) if device and device.isdigit() else device,
        channels=1,
        dtype="int16",
        callback=callback,
        finished_callback=on_finished,
    )
    return stream
