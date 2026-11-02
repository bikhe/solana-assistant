"""Cloud speech through an OpenAI-compatible ``/audio/speech`` endpoint, streamed as raw PCM."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from solana_core.protocol import Language
from solana_core.tts.base import TTSProvider, Voice

OPENAI_BASE_URL = "https://api.openai.com/v1"
VOICES = ("alloy", "ash", "coral", "echo", "nova", "sage", "shimmer")


class OpenAITTS(TTSProvider):
    name = "openai"
    sample_rate = 24_000  # "pcm" responses are 24 kHz mono int16

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = OPENAI_BASE_URL,
        model: str = "gpt-4o-mini-tts",
        voice: str | None = None,
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model = model
        self.voice = voice or "nova"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(timeout_s),
            transport=transport,
        )

    async def voices(self) -> list[Voice]:
        return [Voice(v, v.title(), lang) for v in VOICES for lang in ("ru", "en")]

    async def synthesize(self, text: str, language: Language | None = None) -> AsyncIterator[bytes]:
        if not text.strip():
            return
        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": "pcm",
        }
        async with self._client.stream("POST", "/audio/speech", json=payload) as response:
            response.raise_for_status()
            carry = b""
            async for data in response.aiter_bytes():
                data = carry + data
                even = len(data) // 2 * 2
                carry = data[even:]
                if even:
                    yield data[:even]

    async def close(self) -> None:
        await self._client.aclose()
