"""Silero TTS v4 for Russian, run with PyTorch on the CPU.

The weights are CC BY-NC-SA 4.0: the user downloads them at runtime, we never bundle them.
Install with ``uv sync --extra silero``.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from solana_core.protocol import Language
from solana_core.stt.audio import float32_to_pcm16, slice_pcm16
from solana_core.tts.base import TTSProvider, Voice
from solana_core.tts.numbers import spell_numbers_ru

SPEAKERS = {
    "xenia": "Ксения",
    "baya": "Бая",
    "kseniya": "Ксюша",
    "aidar": "Айдар",
    "eugene": "Евгений",
}


class SileroTTS(TTSProvider):
    name = "silero"

    def __init__(
        self,
        model_path: Path | str,
        *,
        speaker: str | None = None,
        sample_rate: int = 24_000,
        threads: int = 4,
    ) -> None:
        self.model_path = str(model_path)
        self.speaker = speaker if speaker in SPEAKERS else "xenia"
        self.sample_rate = sample_rate
        self.threads = threads
        self._model: Any = None
        self._lock = threading.Lock()

    async def load(self) -> None:
        await asyncio.to_thread(self._ensure_model)

    async def voices(self) -> list[Voice]:
        return [Voice(id, name, "ru") for id, name in SPEAKERS.items()]

    async def synthesize(self, text: str, language: Language | None = None) -> AsyncIterator[bytes]:
        text = spell_numbers_ru(text).strip()
        if not text:
            return
        audio = await asyncio.to_thread(self._synthesize, text)
        for chunk in slice_pcm16(audio, self.sample_rate):
            yield chunk

    def _ensure_model(self) -> Any:
        with self._lock:
            if self._model is None:
                import torch

                torch.set_num_threads(self.threads)
                importer = torch.package.PackageImporter(self.model_path)
                model = importer.load_pickle("tts_models", "model")
                model.to(torch.device("cpu"))
                self._model = model
            return self._model

    def _synthesize(self, text: str) -> bytes:
        model = self._ensure_model()
        with self._lock:
            audio = model.apply_tts(
                text=text,
                speaker=self.speaker,
                sample_rate=self.sample_rate,
                put_accent=True,
                put_yo=True,
            )
        return float32_to_pcm16(audio.numpy())
