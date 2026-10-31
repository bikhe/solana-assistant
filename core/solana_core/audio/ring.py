"""A fixed-size ring buffer of recent PCM audio, so the start of a phrase is never lost."""

from __future__ import annotations

import numpy as np

from solana_core.audio.base import SAMPLE_RATE


class RingBuffer:
    """Keeps the last ``seconds`` of 16 kHz mono int16 audio."""

    def __init__(self, seconds: float = 2.0, sample_rate: int = SAMPLE_RATE) -> None:
        self.capacity = int(seconds * sample_rate)
        self.sample_rate = sample_rate
        self._data = np.zeros(self.capacity, dtype=np.int16)
        self._end = 0  # write position
        self._size = 0

    def __len__(self) -> int:
        """Number of samples currently held."""
        return self._size

    def write(self, pcm: bytes) -> None:
        samples = np.frombuffer(pcm, dtype=np.int16)
        if len(samples) >= self.capacity:
            self._data[:] = samples[-self.capacity :]
            self._end = 0
            self._size = self.capacity
            return
        first = min(len(samples), self.capacity - self._end)
        self._data[self._end : self._end + first] = samples[:first]
        rest = len(samples) - first
        if rest:
            self._data[:rest] = samples[first:]
        self._end = (self._end + len(samples)) % self.capacity
        self._size = min(self._size + len(samples), self.capacity)

    def read(self, seconds: float | None = None) -> bytes:
        """Return the last ``seconds`` (everything by default), oldest sample first."""
        count = self._size if seconds is None else min(self._size, int(seconds * self.sample_rate))
        start = (self._end - count) % self.capacity
        if start + count <= self.capacity:
            return self._data[start : start + count].tobytes()
        return np.concatenate((self._data[start:], self._data[: self._end])).tobytes()

    def clear(self) -> None:
        self._end = 0
        self._size = 0
