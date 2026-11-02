"""openWakeWord-compatible runtime on plain onnxruntime.

The pipeline is the one from openWakeWord (Apache-2.0): audio -> mel spectrogram ->
Google speech embedding (96 values every 80 ms) -> a tiny per-keyword classifier over
the last 16 embeddings. We run it ourselves instead of depending on the ``openwakeword``
package, which pulls tflite-runtime, scipy and scikit-learn.

Only the two shared feature models are downloaded from openWakeWord releases. The
keyword models (``эй_солана`` and others) are trained with the scripts in ``models/``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from solana_core.audio.onnx import Array, OnnxModel
from solana_core.wake.base import WakeDetection, WakeWordDetector

CHUNK = 1280  # samples per step: 80 ms at 16 kHz
MEL_CONTEXT = 480  # extra samples the mel model needs to produce 8 frames per chunk
MEL_FRAMES_PER_CHUNK = 8
MEL_WINDOW = 76  # mel frames per embedding
EMBEDDING_SIZE = 96
DEFAULT_WINDOW = 16  # embeddings per keyword prediction (~1.3 s)
REFRACTORY_STEPS = 15  # ~1.2 s without detections after a hit

# Model call signatures, so tests can pass numpy functions instead of ONNX sessions.
MelFn = Callable[[Array], Array]  # (1, samples) float32 -> (frames, 32)
EmbedFn = Callable[[Array], Array]  # (n, 76, 32, 1) -> (n, 96)
ScoreFn = Callable[[Array], float]  # (1, window, 96) -> score in [0, 1]


def threshold_for(sensitivity: float) -> float:
    """Higher sensitivity means a lower score is enough to wake up."""
    return min(max(1.0 - sensitivity, 0.05), 0.95)


@dataclass(slots=True)
class KeywordModel:
    keyword: str
    score: ScoreFn
    window: int = DEFAULT_WINDOW

    @classmethod
    def from_file(cls, path: Path | str, keyword: str | None = None) -> KeywordModel:
        model = OnnxModel(path)
        name = model.input_names[0]
        window = model.input_shapes[0][1]

        def score(x: Array) -> float:
            return float(np.asarray(model({name: x})[0]).reshape(-1)[0])

        return cls(keyword or Path(path).stem, score, window if isinstance(window, int) else 16)


class FeatureExtractor:
    """Turns a stream of int16 samples into openWakeWord embeddings, 80 ms at a time."""

    def __init__(self, mel: MelFn, embed: EmbedFn, max_embeddings: int = 64) -> None:
        self.mel = mel
        self.embed = embed
        self.max_embeddings = max_embeddings
        self.reset()

    @classmethod
    def from_files(cls, melspectrogram: Path | str, embedding: Path | str) -> FeatureExtractor:
        mel_model = OnnxModel(melspectrogram)
        emb_model = OnnxModel(embedding)
        mel_input = mel_model.input_names[0]
        emb_input = emb_model.input_names[0]

        def mel(x: Array) -> Array:
            out = np.asarray(mel_model({mel_input: x})[0], dtype=np.float32)
            return np.squeeze(out, axis=(0, 1)) if out.ndim == 4 else out

        def embed(x: Array) -> Array:
            out = np.asarray(emb_model({emb_input: x})[0], dtype=np.float32)
            return out.reshape(len(x), EMBEDDING_SIZE)

        return cls(mel, embed)

    def reset(self) -> None:
        self._raw = np.zeros(0, dtype=np.int16)  # last CHUNK + MEL_CONTEXT samples
        self._pending = np.zeros(0, dtype=np.int16)
        self._mel = np.zeros((0, 32), dtype=np.float32)
        self.embeddings = np.zeros((0, EMBEDDING_SIZE), dtype=np.float32)

    def push(self, samples: NDArray[np.int16]) -> int:
        """Add audio; returns how many new embeddings were produced."""
        self._pending = np.concatenate((self._pending, samples))
        produced = 0
        while len(self._pending) >= CHUNK:
            chunk, self._pending = self._pending[:CHUNK], self._pending[CHUNK:]
            produced += self._step(chunk)
        return produced

    def _step(self, chunk: NDArray[np.int16]) -> int:
        self._raw = np.concatenate((self._raw, chunk))[-(CHUNK + MEL_CONTEXT) :]
        if len(self._raw) < CHUNK + MEL_CONTEXT:
            return 0
        spec = self.mel(self._raw.astype(np.float32)[None, :]) / 10.0 + 2.0
        self._mel = np.concatenate((self._mel, spec))[-MEL_WINDOW:]
        if len(self._mel) < MEL_WINDOW:
            return 0
        emb = self.embed(self._mel[None, :, :, None])
        self.embeddings = np.concatenate((self.embeddings, emb))[-self.max_embeddings :]
        return 1


def clip_embeddings(
    extractor: FeatureExtractor, samples: NDArray[np.int16], window: int = DEFAULT_WINDOW
) -> Array | None:
    """Embeddings of the last ``window`` steps of a clip, for training and offline scoring.

    ``None`` if the clip is too short (needs about ``window * 80 ms + 1 s``).
    """
    extractor.reset()
    extractor.push(samples)
    if len(extractor.embeddings) < window:
        return None
    return extractor.embeddings[-window:].copy()


class OpenWakeWordDetector(WakeWordDetector):
    """Runs one or more keyword models over shared features.

    ``process`` takes 20 ms frames; a prediction happens every 80 ms. After a hit the
    detector stays quiet for ~1.2 s so one phrase gives one detection.
    """

    def __init__(
        self,
        features: FeatureExtractor,
        keywords: Iterable[KeywordModel],
        sensitivity: float = 0.5,
    ) -> None:
        self.features = features
        self.keywords = list(keywords)
        if not self.keywords:
            raise ValueError("at least one keyword model is required")
        self.sensitivity = sensitivity
        self.last_scores: dict[str, float] = {}
        self._quiet = 0

    @property
    def threshold(self) -> float:
        return threshold_for(self.sensitivity)

    def process(self, frame: bytes) -> WakeDetection | None:
        steps = self.features.push(np.frombuffer(frame, dtype=np.int16))
        hit: WakeDetection | None = None
        for _ in range(steps):
            if self._quiet > 0:
                self._quiet -= 1
                continue
            best = self._predict()
            if best is not None and hit is None:
                hit = best
                self._quiet = REFRACTORY_STEPS
        return hit

    def _predict(self) -> WakeDetection | None:
        best: WakeDetection | None = None
        emb = self.features.embeddings
        for model in self.keywords:
            if len(emb) < model.window:
                continue
            score = model.score(emb[-model.window :][None, :, :])
            self.last_scores[model.keyword] = score
            if score >= self.threshold and (best is None or score > best.score):
                best = WakeDetection(model.keyword, score)
        return best

    def reset(self) -> None:
        self.features.reset()
        self.last_scores.clear()
        self._quiet = 0
