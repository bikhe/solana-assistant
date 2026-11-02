"""Piper voices (ONNX). English by default, Russian voices work too.

``piper-tts`` is GPL-3.0 because it links espeak-ng, so it stays an optional extra:
``uv sync --extra piper``.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from solana_core.protocol import Language
from solana_core.stt.audio import resample_pcm16, slice_pcm16
from solana_core.tts.base import TTSProvider


class PiperTTS(TTSProvider):
    name = "piper"

    def __init__(self, model_path: Path | str, *, use_cuda: bool = False) -> None:
        """``model_path`` is the ``.onnx`` voice with its ``.onnx.json`` next to it."""
        self.model_path = str(model_path)
        self.use_cuda = use_cuda
        config = json.loads(Path(self.model_path + ".json").read_text("utf-8"))
        self.voice_rate = int(config["audio"]["sample_rate"])
        self.sample_rate = self.voice_rate
        self._voice: Any = None
        self._lock = threading.Lock()

    async def load(self) -> None:
        await asyncio.to_thread(self._ensure_voice)

    async def synthesize(self, text: str, language: Language | None = None) -> AsyncIterator[bytes]:
        if not text.strip():
            return
        audio = await asyncio.to_thread(self._synthesize, text)
        for chunk in slice_pcm16(audio, self.sample_rate):
            yield chunk

    def _ensure_voice(self) -> Any:
        with self._lock:
            if self._voice is None:
                from piper import PiperVoice

                self._voice = PiperVoice.load(self.model_path, use_cuda=self.use_cuda)
            return self._voice

    def _synthesize(self, text: str) -> bytes:
        voice = self._ensure_voice()
        with self._lock:
            parts = [
                resample_pcm16(c.audio_int16_bytes, c.sample_rate, self.sample_rate)
                for c in voice.synthesize(text)
            ]
        return b"".join(parts)
