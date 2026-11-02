"""GigaAM v3 (Sber, MIT): a fast Russian-only recognizer, run through ONNX Runtime by onnx-asr.

Install with ``uv sync --extra gigaam``.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from solana_core.audio.base import SAMPLE_RATE
from solana_core.protocol import Language
from solana_core.stt.audio import pcm16_to_float32
from solana_core.stt.base import Transcript
from solana_core.stt.streaming import ChunkedStreamingSTT


class GigaAMSTT(ChunkedStreamingSTT):
    name = "gigaam"
    partial_interval_s = 0.5  # CTC decoding is cheap

    def __init__(
        self,
        model_path: Path | str,
        *,
        model_name: str = "gigaam-v3-ctc",
        quantization: str | None = "int8",
    ) -> None:
        self.model_path = str(model_path)
        self.model_name = model_name
        self.quantization = quantization
        self._model: Any = None
        self._lock = threading.Lock()

    async def load(self) -> None:
        await asyncio.to_thread(self._ensure_model)

    async def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript:
        # Russian only: an English request still returns the best Russian reading.
        return await asyncio.to_thread(self._transcribe, audio)

    def _ensure_model(self) -> Any:
        with self._lock:
            if self._model is None:
                import onnx_asr

                self._model = onnx_asr.load_model(
                    self.model_name, self.model_path, quantization=self.quantization
                )
            return self._model

    def _transcribe(self, audio: bytes) -> Transcript:
        model = self._ensure_model()
        if not audio:
            return Transcript("", "ru")
        with self._lock:
            text = model.recognize(pcm16_to_float32(audio), sample_rate=SAMPLE_RATE)
        return Transcript(str(text).strip(), "ru")
