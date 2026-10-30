"""Text-to-speech contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from solana_core.protocol import Language


@dataclass(frozen=True, slots=True)
class Voice:
    id: str
    name: str
    language: Language


class TTSProvider(ABC):
    name: str
    sample_rate: int = 16_000

    @abstractmethod
    def synthesize(self, text: str, language: Language | None = None) -> AsyncIterator[bytes]:
        """Yield mono int16 PCM chunks at ``sample_rate`` as soon as they are ready."""

    async def voices(self) -> list[Voice]:
        return []


class FakeTTS(TTSProvider):
    """Produces 10 ms of silence per character."""

    name = "fake"

    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def synthesize(self, text: str, language: Language | None = None) -> AsyncIterator[bytes]:
        self.spoken.append(text)
        for _ in text:
            yield bytes(self.sample_rate // 100 * 2)
