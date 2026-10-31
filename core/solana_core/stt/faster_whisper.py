"""Local Whisper on CTranslate2 (faster-whisper): int8 on the CPU, float16 with CUDA.

Install with ``uv sync --extra faster-whisper``.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from solana_core.protocol import Language
from solana_core.stt.audio import normalize_language, pcm16_to_float32
from solana_core.stt.base import Transcript
from solana_core.stt.streaming import ChunkedStreamingSTT

_OURS: tuple[Language, ...] = ("ru", "en")


class FasterWhisperSTT(ChunkedStreamingSTT):
    name = "faster-whisper"

    def __init__(
        self,
        model_path: Path | str,
        *,
        device: str = "cpu",
        compute_type: str | None = None,
        cpu_threads: int = 0,
        beam_size: int = 1,
    ) -> None:
        self.model_path = str(model_path)
        self.device = device
        self.compute_type = compute_type or ("float16" if device == "cuda" else "int8")
        self.cpu_threads = cpu_threads
        self.beam_size = beam_size
        self._model: Any = None
        self._lock = threading.Lock()  # one decode at a time, even if a caller is cancelled

    async def load(self) -> None:
        await asyncio.to_thread(self._ensure_model)

    async def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript:
        return await asyncio.to_thread(self._transcribe, audio, language)

    def _ensure_model(self) -> Any:
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self.model_path,
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=self.cpu_threads,
                )
            return self._model

    def _transcribe(self, audio: bytes, language: Language | None) -> Transcript:
        model = self._ensure_model()
        samples = pcm16_to_float32(audio)
        with self._lock:
            text, info = self._decode(model, samples, language)
            detected = language or normalize_language(info.language)
            if detected is None:
                # Whisper heard another language: keep to ours and decode again.
                probs = dict(info.all_language_probs or [])
                detected = max(_OURS, key=lambda lang: probs.get(lang, 0.0))
                text, _ = self._decode(model, samples, detected)
        return Transcript(text, detected)

    def _decode(self, model: Any, samples: Any, language: Language | None) -> tuple[str, Any]:
        segments, info = model.transcribe(
            samples,
            language=language,
            beam_size=self.beam_size,
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=False,
        )
        return "".join(s.text for s in segments).strip(), info
