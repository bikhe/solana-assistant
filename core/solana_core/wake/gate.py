"""Run the wake word model only while someone is speaking."""

from __future__ import annotations

from solana_core.audio.base import FRAME_BYTES, FRAME_MS, VoiceActivityDetector
from solana_core.audio.ring import RingBuffer
from solana_core.audio.wav import to_frames
from solana_core.wake.base import WakeDetection, WakeWordDetector


class VadGatedDetector(WakeWordDetector):
    """Wraps a detector with a VAD gate.

    In silence only the VAD runs. When speech starts, the detector is reset and fed the
    last ``preroll_s`` seconds from a ring buffer, so it sees the whole phrase, including
    the part said before the VAD reacted. It keeps running for ``hangover_ms`` after the
    VAD falls silent.
    """

    def __init__(
        self,
        detector: WakeWordDetector,
        vad: VoiceActivityDetector,
        preroll_s: float = 2.5,
        hangover_ms: int = 1000,
    ) -> None:
        self.detector = detector
        self.vad = vad
        self.hangover_frames = hangover_ms // FRAME_MS
        self.active = False
        self.active_frames = 0  # frames the detector has processed, for measurements
        self._ring = RingBuffer(preroll_s)
        self._left = 0

    @property
    def sensitivity(self) -> float:
        return self.detector.sensitivity

    @sensitivity.setter
    def sensitivity(self, value: float) -> None:
        self.detector.sensitivity = value

    def process(self, frame: bytes) -> WakeDetection | None:
        self._ring.write(frame)
        if self.vad.is_speech(frame):
            self._left = self.hangover_frames
        elif self._left > 0:
            self._left -= 1
        was_active, self.active = self.active, self._left > 0
        if not self.active:
            return None
        if was_active:
            self.active_frames += 1
            return self.detector.process(frame)
        # Speech just started: replay the pre-roll (it ends with the current frame).
        self.detector.reset()
        hit: WakeDetection | None = None
        for f in to_frames(self._ring.read(), FRAME_BYTES):
            self.active_frames += 1
            hit = self.detector.process(f) or hit
        return hit

    def reset(self) -> None:
        self.detector.reset()
        self.vad.reset()
        self._ring.clear()
        self._left = 0
        self.active = False
