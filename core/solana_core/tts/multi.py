"""One voice per language: Silero speaks Russian, Piper speaks English."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping

from solana_core.protocol import Language
from solana_core.stt.audio import guess_language, resample_pcm16
from solana_core.tts.base import TTSProvider, Voice


class MultiLanguageTTS(TTSProvider):
    name = "multi"

    def __init__(
        self,
        providers: Mapping[Language, TTSProvider],
        *,
        default: Language = "ru",
        sample_rate: int = 24_000,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self.providers = dict(providers)
        self.default: Language = default if default in self.providers else next(iter(providers))
        self.sample_rate = sample_rate

    def provider_for(self, text: str, language: Language | None = None) -> TTSProvider:
        lang = language or guess_language(text) or self.default
        return self.providers.get(lang) or self.providers[self.default]

    async def synthesize(self, text: str, language: Language | None = None) -> AsyncIterator[bytes]:
        tts = self.provider_for(text, language)
        async for chunk in tts.synthesize(text, language):
            yield resample_pcm16(chunk, tts.sample_rate, self.sample_rate)

    async def voices(self) -> list[Voice]:
        return [v for tts in self.providers.values() for v in await tts.voices()]
