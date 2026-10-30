"""Cloud recognition through any OpenAI-compatible ``/audio/transcriptions`` endpoint
(OpenAI, Groq, a local speaches server, ...)."""

from __future__ import annotations

from typing import Any

import httpx

from solana_core.protocol import Language
from solana_core.stt.audio import guess_language, normalize_language, pcm16_to_wav
from solana_core.stt.base import STTProvider, Transcript

OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_SECRET = "openai"  # keyring entry with the API key


class OpenAISTT(STTProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = OPENAI_BASE_URL,
        model: str = "gpt-4o-mini-transcribe",
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(timeout_s),
            transport=transport,
        )

    async def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript:
        data = {"model": self.model, "response_format": "json"}
        if language:
            data["language"] = language
        response = await self._client.post(
            "/audio/transcriptions",
            files={"file": ("audio.wav", pcm16_to_wav(audio), "audio/wav")},
            data=data,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        text = str(body.get("text", "")).strip()
        detected = language or normalize_language(body.get("language")) or guess_language(text)
        return Transcript(text, detected)

    async def close(self) -> None:
        await self._client.aclose()
