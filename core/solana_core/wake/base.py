"""Wake word contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WakeDetection:
    keyword: str
    score: float


class WakeWordDetector(ABC):
    """Consumes 16 kHz mono int16 frames and reports a detection when the wake word is heard."""

    sensitivity: float = 0.5

    @abstractmethod
    def process(self, frame: bytes) -> WakeDetection | None: ...

    def reset(self) -> None:  # noqa: B027 - optional hook
        """Clear internal buffers, e.g. after a detection."""


class FakeWakeWordDetector(WakeWordDetector):
    """Fires once after ``fire_after`` frames, then every ``fire_after`` frames again."""

    def __init__(self, fire_after: int = 10, keyword: str = "эй_солана") -> None:
        self.fire_after = fire_after
        self.keyword = keyword
        self._count = 0

    def process(self, frame: bytes) -> WakeDetection | None:
        self._count += 1
        if self._count >= self.fire_after:
            self._count = 0
            return WakeDetection(self.keyword, 1.0)
        return None

    def reset(self) -> None:
        self._count = 0
