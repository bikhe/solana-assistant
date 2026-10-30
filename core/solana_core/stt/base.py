"""Speech-to-text contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from solana_core.protocol import Language


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: Language | None = None
    final: bool = True


class STTProvider(ABC):
    name: str

    @abstractmethod
    async def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript:
        """Recognize a whole utterance (16 kHz mono int16 PCM)."""

    async def stream(
        self, frames: AsyncIterator[bytes], language: Language | None = None
    ) -> AsyncIterator[Transcript]:
        """Yield partial transcripts while audio arrives, then the final one.

        The default buffers everything and yields only the final result.
        """
        audio = b"".join([frame async for frame in frames])
        yield await self.transcribe(audio, language)


class FakeSTT(STTProvider):
    name = "fake"

    def __init__(self, text: str = "какая сегодня погода", language: Language = "ru") -> None:
        self.text = text
        self.language: Language = language

    async def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript:
        return Transcript(self.text, language or self.language)

    async def stream(
        self, frames: AsyncIterator[bytes], language: Language | None = None
    ) -> AsyncIterator[Transcript]:
        async for _ in frames:
            pass
        words = self.text.split()
        for i in range(1, len(words)):
            yield Transcript(" ".join(words[:i]), language or self.language, final=False)
        yield Transcript(self.text, language or self.language)
