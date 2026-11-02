"""End of phrase detection. Counts audio frames, not wall time, so it behaves the same on a
slow machine and in tests that feed a WAV file faster than real time."""

from __future__ import annotations

from enum import StrEnum

from solana_core.audio.base import FRAME_MS


class EndReason(StrEnum):
    SILENCE = "silence"  # the user paused long enough
    MAX_LENGTH = "max_length"  # the phrase hit the length limit
    NO_SPEECH = "no_speech"  # nobody started speaking in time


def frames_for(ms: float) -> int:
    return max(1, round(ms / FRAME_MS))


class Endpointer:
    """Fed one VAD decision per frame; says when the phrase is over.

    ``start_timeout_ms`` is how long to wait for speech to begin, ``end_silence_ms`` how
    much silence ends it, and ``max_speech_ms`` caps the phrase from its first speech frame.
    ``min_speech_ms`` of speech in a row is needed to count as a start, so a click or a
    cough does not open a phrase that then ends in silence.
    """

    def __init__(
        self,
        *,
        end_silence_ms: float = 1000,
        max_speech_ms: float = 15_000,
        start_timeout_ms: float = 5000,
        min_speech_ms: float = 60,
    ) -> None:
        self.end_silence = frames_for(end_silence_ms)
        self.max_speech = frames_for(max_speech_ms)
        self.start_timeout = frames_for(start_timeout_ms)
        self.min_speech = frames_for(min_speech_ms)
        self.started = False
        self.frames = 0  # frames seen
        self.speech_frames = 0  # frames since speech started
        self._run = 0  # consecutive speech frames before the start
        self._silence = 0

    def push(self, is_speech: bool) -> EndReason | None:
        self.frames += 1
        if not self.started:
            self._run = self._run + 1 if is_speech else 0
            if self._run >= self.min_speech:
                self.started = True
                self.speech_frames = self._run
            elif self.frames >= self.start_timeout:
                return EndReason.NO_SPEECH
            return None
        self.speech_frames += 1
        self._silence = 0 if is_speech else self._silence + 1
        if self._silence >= self.end_silence:
            return EndReason.SILENCE
        if self.speech_frames >= self.max_speech:
            return EndReason.MAX_LENGTH
        return None
