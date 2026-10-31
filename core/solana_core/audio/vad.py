"""Voice activity detection: a free energy gate and Silero VAD (MIT, ONNX)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from solana_core.audio.base import FRAME_MS, SAMPLE_RATE, VoiceActivityDetector
from solana_core.audio.onnx import OnnxModel, Runner
from solana_core.audio.wav import rms


class EnergyVAD(VoiceActivityDetector):
    """Speech is anything louder than ``threshold`` (int16 RMS), held for ``hangover_ms``.

    Needs no model. Used as a cheap pre-gate in front of Silero and in tests.
    """

    def __init__(self, threshold: float = 300.0, hangover_ms: int = 200) -> None:
        self.threshold = threshold
        self._hangover = hangover_ms // FRAME_MS
        self._left = 0

    def is_speech(self, frame: bytes) -> bool:
        if rms(frame) >= self.threshold:
            self._left = self._hangover
            return True
        if self._left > 0:
            self._left -= 1
            return True
        return False

    def reset(self) -> None:
        self._left = 0


class SileroVAD(VoiceActivityDetector):
    """Silero VAD v5 on 32 ms windows with hysteresis.

    Frames of any length are buffered into 512-sample windows. Windows quieter than
    ``min_rms`` skip the model entirely, so silence costs next to nothing.
    """

    WINDOW = 512
    CONTEXT = 64

    def __init__(
        self,
        model: Path | str | Runner,
        threshold: float = 0.5,
        min_rms: float = 60.0,
    ) -> None:
        self._run: Runner = OnnxModel(model) if isinstance(model, Path | str) else model
        self.threshold = threshold
        self.neg_threshold = max(threshold - 0.15, 0.01)
        self.min_rms = min_rms
        self.probability = 0.0
        self.model_calls = 0
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(self.CONTEXT, dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.int16)
        self._speaking = False
        self.probability = 0.0

    def _window(self, window: np.ndarray) -> float:
        if rms(window) < self.min_rms:
            self._context = window[-self.CONTEXT :].astype(np.float32) / 32768.0
            return 0.0
        x = window.astype(np.float32) / 32768.0
        feed = {
            "input": np.concatenate((self._context, x))[None, :],
            "state": self._state,
            "sr": np.array(SAMPLE_RATE, dtype=np.int64),
        }
        out, self._state = self._run(feed)[:2]
        self._context = x[-self.CONTEXT :]
        self.model_calls += 1
        return float(np.asarray(out).reshape(-1)[0])

    def is_speech(self, frame: bytes) -> bool:
        self._pending = np.concatenate((self._pending, np.frombuffer(frame, dtype=np.int16)))
        while len(self._pending) >= self.WINDOW:
            window, self._pending = self._pending[: self.WINDOW], self._pending[self.WINDOW :]
            self.probability = self._window(window)
            if self.probability >= self.threshold:
                self._speaking = True
            elif self.probability < self.neg_threshold:
                self._speaking = False
        return self._speaking
