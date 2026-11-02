"""The voice loop: wake word -> listen -> recognize -> answer -> speak, with barge-in, a
follow-up window and auto-pause.

One task reads the microphone and never waits on anything slow: it routes each frame by
the current mode. Everything slow (recognition, the dialog turn, playback) runs in a
session task, which the frame loop can cancel at once when the user interrupts.

    idle --wake word--> listening --end of phrase--> thinking --first audio--> speaking
      ^                    |  no speech / cancel                                  |
      |                    v                                                      |
      +--------------------+<-------- done (answer without a question) ----------+
                           ^                                                      |
                           +---- follow-up window (answer ends with "?") --------+
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import Enum, auto

from solana_core.audio.base import (
    FRAME_BYTES,
    FRAME_MS,
    AudioSink,
    AudioSource,
    VoiceActivityDetector,
)
from solana_core.audio.mic import AudioUnavailableError
from solana_core.audio.ring import RingBuffer
from solana_core.brain.base import TextDelta
from solana_core.brain.dialog import ToolFinished, ToolStarted, TurnDone
from solana_core.pipeline.autopause import MIC_MUTED, AutoPause
from solana_core.pipeline.commands import (
    is_cancel,
    is_question,
    is_stop,
    normalize,
    strip_wake_word,
)
from solana_core.pipeline.endpoint import Endpointer, EndReason, frames_for
from solana_core.protocol import AssistantState, Language
from solana_core.protocol.generated import (
    AssistantDeltaEvent,
    AssistantDoneEvent,
    ErrorEvent,
    ToolFinishedEvent,
    ToolStartedEvent,
    TranscriptEvent,
)
from solana_core.server.core import Core
from solana_core.stt.base import STTProvider, Transcript
from solana_core.tts.base import TTSProvider
from solana_core.tts.sentences import speak_stream
from solana_core.wake.base import WakeWordDetector

log = logging.getLogger(__name__)

_TEXT: dict[str, dict[Language, str]] = {
    "mic": {
        "ru": "Не получается слушать микрофон: {error}",
        "en": "Can't listen to the microphone: {error}",
    },
    "stt": {
        "ru": "Не получилось распознать речь, попробуй ещё раз.",
        "en": "I couldn't recognize that, please try again.",
    },
    "output": {
        "ru": "Не получается воспроизвести звук.",
        "en": "Can't play the sound.",
    },
    "no_llm": {
        "ru": "Модель не настроена, ответить не могу.",
        "en": "No model is set up, so I can't answer.",
    },
    "failed": {
        "ru": "Голосовой режим дал сбой, попробуй ещё раз.",
        "en": "Voice mode failed, please try again.",
    },
}


@dataclass(slots=True)
class PipelineConfig:
    """Timings of the voice loop. ``end_of_speech_ms`` comes from the settings."""

    max_command_s: float = 15.0  # the longest phrase, from its first word
    listen_timeout_s: float = 6.0  # how long to wait for a command after the wake word
    follow_up_s: float = 5.0  # how long to listen without the wake word after a question
    preroll_ms: int = 200  # audio before the wake detection that goes to the recognizer
    barge_in: bool = True  # the wake word while answering starts a new command
    stop_words: bool = True  # "стоп" while answering stops it
    stop_word_max_s: float = 2.0  # longer speech while answering is not a stop word
    stop_word_silence_ms: int = 300
    mic_muted_after_s: float | None = 2.0  # exact digital silence this long means mute
    pause_poll_s: float = 2.0


@dataclass(slots=True)
class TurnMetrics:
    """Timings of one voice command, measured from the end of the phrase."""

    utterance_id: str
    text: str
    end_reason: EndReason
    recognized_s: float  # end of phrase -> final transcript
    first_audio_s: float | None = None  # end of phrase -> first audio of the answer
    fast: bool = False
    interrupted: bool = False


class Mode(Enum):
    IDLE = auto()  # waiting for the wake word
    LISTENING = auto()  # recording a command
    RECOGNIZING = auto()  # final transcript is being computed
    RESPONDING = auto()  # thinking and speaking


class _Utterance:
    """One command being recorded. Frames reach the recognizer only once speech starts,
    so a wake word followed by silence costs no recognition at all."""

    def __init__(self, endpointer: Endpointer, preroll: list[bytes], pad_frames: int) -> None:
        self.id = uuid.uuid4().hex
        self.endpointer = endpointer
        self.pending: deque[bytes] = deque(preroll, maxlen=len(preroll) + pad_frames)
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.started = asyncio.Event()  # speech began, or the phrase ended without it
        self.end_reason: EndReason | None = None
        self.ended_at = 0.0

    def push(self, frame: bytes, is_speech: bool, now: float) -> bool:
        """Add a frame; True when the phrase is over."""
        reason = self.endpointer.push(is_speech)
        if self.started.is_set():
            self.queue.put_nowait(frame)
        else:
            self.pending.append(frame)
            if self.endpointer.started:
                for f in self.pending:
                    self.queue.put_nowait(f)
                self.pending.clear()
                self.started.set()
        if reason is None:
            return False
        self.end_reason, self.ended_at = reason, now
        self.queue.put_nowait(None)
        self.started.set()
        return True

    async def frames(self) -> AsyncIterator[bytes]:
        while (frame := await self.queue.get()) is not None:
            yield frame


class _StopListener:
    """Cuts short bursts of speech out of the audio while the assistant answers."""

    def __init__(self, max_frames: int, silence_frames: int) -> None:
        self.max_frames = max_frames
        self.silence_frames = silence_frames
        self.reset()

    def reset(self) -> None:
        self._frames: list[bytes] = []
        self._silence = 0
        self._too_long = False

    def push(self, frame: bytes, is_speech: bool) -> bytes | None:
        """Returns a finished short segment."""
        if not self._frames and not self._too_long and not is_speech:
            return None
        self._silence = 0 if is_speech else self._silence + 1
        if not self._too_long:
            self._frames.append(frame)
            if len(self._frames) > self.max_frames + self.silence_frames:
                self._too_long = True
                self._frames = []
        if self._silence < self.silence_frames:
            return None
        segment = b"".join(self._frames[: -self.silence_frames])
        self.reset()
        return segment or None


@dataclass(slots=True)
class _Session:
    task: asyncio.Task[None] | None = None
    utterance: _Utterance | None = None
    answer: str = ""  # what the assistant has said so far in this turn
    stop_checks: set[asyncio.Task[None]] = field(default_factory=set)


class VoicePipeline:
    def __init__(
        self,
        core: Core,
        source: AudioSource,
        *,
        vad: VoiceActivityDetector,
        stt: STTProvider,
        tts: TTSProvider,
        sink: AudioSink,
        wake: WakeWordDetector | None = None,
        autopause: AutoPause | None = None,
        config: PipelineConfig | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.core = core
        self.source = source
        self.vad = vad
        self.stt = stt
        self.tts = tts
        self.sink = sink
        self.wake = wake
        self.autopause = autopause
        self.config = config or PipelineConfig()
        self.clock = clock
        self.mode = Mode.IDLE
        self.metrics: list[TurnMetrics] = []
        self.frames_seen = 0
        self._session: _Session | None = None
        self._ring = RingBuffer(1.0)
        self._stop_listener = _StopListener(
            frames_for(self.config.stop_word_max_s * 1000),
            frames_for(self.config.stop_word_silence_ms),
        )
        self._was_muted = False
        self._zero_frames = 0
        self._mic_muted = False
        self._probe_reason: str | None = None
        self._auto_paused: str | None = None

    # ---- public API ----

    async def run(self) -> None:
        """Listen until the source ends or the task is cancelled."""
        watcher = asyncio.create_task(self._watch_pause()) if self.autopause else None
        try:
            await self.source.start()
            if self.core.state == "error":
                self.core.set_state("idle", "voice_ready")
            async for frame in self.source.frames():
                self._on_frame(frame)
        except AudioUnavailableError as exc:
            log.error("microphone failed: %s", exc)
            self._error("mic_unavailable", self._t("mic", error=str(exc)), recoverable=False)
            self.core.set_state("error", "mic_unavailable")
        finally:
            if watcher is not None:
                watcher.cancel()
            await self._end_session()
            with contextlib.suppress(Exception):
                await self.source.stop()

    @property
    def audio_time(self) -> float:
        """Seconds of microphone audio processed so far."""
        return self.frames_seen * FRAME_MS / 1000

    def activate(self, reason: str = "hotkey") -> bool:
        """Start listening as if the wake word was heard (push-to-talk)."""
        if self.core.muted or (self._session is None and self.core.turn_lock.locked()):
            return False
        self._start(reason)
        return True

    # ---- frame routing (sync: never blocks the microphone) ----

    def _on_frame(self, frame: bytes) -> None:
        self.frames_seen += 1
        self._ring.write(frame)
        self._track_mic_mute(frame)
        if self.core.muted:
            if not self._was_muted:
                self._was_muted = True
                self._cancel_session()
            return
        if self._was_muted:
            self._was_muted = False
            self._reset_detectors()
        if self.mode is Mode.LISTENING:
            self._listen_frame(frame)
        elif self.mode is Mode.RECOGNIZING:
            self._barge_in_frame(frame)
        elif self.mode is Mode.RESPONDING:
            if not self._barge_in_frame(frame):
                self._stop_word_frame(frame)
        else:
            self._idle_frame(frame)

    def _idle_frame(self, frame: bytes) -> None:
        voice = self.core.config.settings.voice
        if self.wake is None or not voice.wake_word_enabled:
            return
        if self.wake.sensitivity != voice.wake_sensitivity:
            self.wake.sensitivity = voice.wake_sensitivity
        hit = self.wake.process(frame)
        # A text chat turn in progress owns the assistant; let it finish.
        if hit is not None and not self.core.turn_lock.locked():
            log.info("wake word %s (%.2f)", hit.keyword, hit.score)
            self._start("wake_word")

    def _listen_frame(self, frame: bytes) -> None:
        session = self._session
        utterance = session.utterance if session else None
        if utterance is None:
            return
        if utterance.push(frame, self.vad.is_speech(frame), self.clock()):
            self._set_mode(Mode.RECOGNIZING)

    def _barge_in_frame(self, frame: bytes) -> bool:
        if self.wake is None or not self.config.barge_in:
            return False
        if not self.core.config.settings.voice.wake_word_enabled:
            return False
        if self.wake.process(frame) is None:
            return False
        log.info("barge-in by wake word")
        self._start("barge_in")
        return True

    def _stop_word_frame(self, frame: bytes) -> None:
        if not self.config.stop_words:
            return
        segment = self._stop_listener.push(frame, self.vad.is_speech(frame))
        session = self._session
        if segment is None or session is None:
            return
        task = asyncio.create_task(self._check_stop_word(session, segment))
        session.stop_checks.add(task)
        task.add_done_callback(session.stop_checks.discard)

    async def _check_stop_word(self, session: _Session, segment: bytes) -> None:
        try:
            text = (await self.stt.transcribe(segment)).text
        except Exception:
            log.debug("stop word check failed", exc_info=True)
            return
        phrase = normalize(text)
        # The microphone hears our own voice too: a "стоп" that we are saying is echo.
        if not is_stop(text) or phrase in normalize(session.answer):
            return
        if self._session is session and self.mode is Mode.RESPONDING:
            log.info("stopped by voice: %r", text)
            self._cancel_session()
            self._set_state("idle", "stop_word")

    # ---- sessions ----

    def _start(self, reason: str, timeout_s: float | None = None) -> None:
        """Begin listening for a command now, interrupting whatever was going on."""
        self._cancel_session()
        session = self._session = _Session()
        self._set_state("wake", reason)
        self._listen(session, timeout_s or self.config.listen_timeout_s, self._preroll())
        session.task = asyncio.create_task(self._run_session(session))

    def _listen(
        self, session: _Session, timeout_s: float, preroll: list[bytes], reason: str | None = None
    ) -> None:
        voice = self.core.config.settings.voice
        endpointer = Endpointer(
            end_silence_ms=voice.end_of_speech_ms,
            max_speech_ms=self.config.max_command_s * 1000,
            start_timeout_ms=timeout_s * 1000,
        )
        session.utterance = _Utterance(endpointer, preroll, frames_for(300))
        self.vad.reset()
        self._set_mode(Mode.LISTENING)
        self._set_state("listening", reason)

    def _preroll(self) -> list[bytes]:
        audio = self._ring.read(self.config.preroll_ms / 1000)
        start = len(audio) % FRAME_BYTES  # whole frames only
        return [audio[i : i + FRAME_BYTES] for i in range(start, len(audio), FRAME_BYTES)]

    async def _run_session(self, session: _Session) -> None:
        idle_reason = "done"
        try:
            while True:
                utterance = session.utterance
                assert utterance is not None
                transcript = await self._recognize(utterance)
                if transcript is None:
                    no_speech = utterance.end_reason is EndReason.NO_SPEECH
                    idle_reason = "no_speech" if no_speech else "not_recognized"
                    return
                text = transcript.text.strip()
                if is_cancel(text):
                    idle_reason = "cancelled"
                    return
                language = transcript.language or self.core.config.settings.general.language
                metrics = TurnMetrics(
                    utterance.id,
                    text,
                    utterance.end_reason or EndReason.SILENCE,
                    self.clock() - utterance.ended_at,
                )
                self.metrics.append(metrics)
                session.utterance = None
                answer = await self._respond(session, text, language, metrics, utterance.ended_at)
                if metrics.interrupted or not is_question(answer):
                    return
                self._listen(session, self.config.follow_up_s, [], "follow_up")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("voice session failed")
            self._error("voice_failed", self._t("failed"))
            idle_reason = "error"
        finally:
            for task in list(session.stop_checks):
                task.cancel()
            if self._session is session:
                self._session = None
                self._set_mode(Mode.IDLE)
                self._set_state("idle", idle_reason)

    async def _recognize(self, utterance: _Utterance) -> Transcript | None:
        await utterance.started.wait()
        if utterance.end_reason is EndReason.NO_SPEECH:
            return None
        final: Transcript | None = None
        try:
            async for transcript in self.stt.stream(utterance.frames()):
                if not transcript.text:
                    continue
                if transcript.final:
                    final = transcript
                else:
                    self.core.bus.emit(
                        "transcript.partial",
                        TranscriptEvent(
                            utterance_id=utterance.id,
                            text=transcript.text,
                            language=transcript.language,
                        ),
                    )
        except Exception:
            log.exception("speech recognition failed")
            self._error("stt_failed", self._t("stt"))
            return None
        # The pre-roll may carry the end of the wake word into the transcript.
        if final is None:
            return None
        text = strip_wake_word(final.text.strip())
        if not normalize(text):
            return None
        self.core.bus.emit(
            "transcript.final",
            TranscriptEvent(utterance_id=utterance.id, text=text, language=final.language),
        )
        return Transcript(text, final.language)

    async def _respond(
        self,
        session: _Session,
        text: str,
        language: Language,
        metrics: TurnMetrics,
        ended_at: float,
    ) -> str:
        """Run one dialog turn and speak it. Returns what was said."""
        dialog = self.core.dialog
        if dialog is None:
            self._error("llm_unavailable", self._t("no_llm", language))
            return ""
        turn_id = uuid.uuid4().hex
        session.answer = ""
        async with self.core.turn_lock:
            self._set_mode(Mode.RESPONDING)
            self._set_state("thinking", "voice")
            deltas: asyncio.Queue[str | None] = asyncio.Queue()

            async def text_deltas() -> AsyncIterator[str]:
                while (delta := await deltas.get()) is not None:
                    yield delta

            async def audio() -> AsyncIterator[bytes]:
                async for chunk in speak_stream(self.tts, text_deltas(), language):
                    if metrics.first_audio_s is None:
                        metrics.first_audio_s = self.clock() - ended_at
                        self._set_state("speaking")
                    yield chunk

            playback = asyncio.create_task(self._play(audio()))
            said = False  # the whole answer was generated and played
            try:
                async for event in dialog.turn(text, language=language, turn_id=turn_id):
                    if isinstance(event, TextDelta):
                        session.answer += event.text
                        deltas.put_nowait(event.text)
                        self.core.bus.emit(
                            "assistant.delta", AssistantDeltaEvent(turn_id=turn_id, text=event.text)
                        )
                    elif isinstance(event, ToolStarted):
                        self.core.bus.emit(
                            "tool.started",
                            ToolStartedEvent(
                                call_id=event.call.id,
                                turn_id=turn_id,
                                tool=event.call.name,
                                arguments=dict(event.call.arguments),
                            ),
                        )
                    elif isinstance(event, ToolFinished):
                        result = event.result
                        self.core.bus.emit(
                            "tool.finished",
                            ToolFinishedEvent(
                                call_id=event.call.id,
                                tool=event.call.name,
                                ok=result.ok,
                                summary=result.content[:200] if result.ok else None,
                                error=None if result.ok else result.content[:200],
                            ),
                        )
                    elif isinstance(event, TurnDone):
                        metrics.fast = event.fast
                        session.answer = event.text
                        if event.error_code:
                            self.core.bus.emit(
                                "error",
                                ErrorEvent(
                                    code=event.error_code, message=event.text, recoverable=True
                                ),
                            )
                deltas.put_nowait(None)
                await playback
                said = True
            finally:
                if not said:
                    metrics.interrupted = True
                    playback.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await playback
                    with contextlib.suppress(Exception):
                        await self.sink.stop()
                # Sent after playback: for voice the answer is done when it has been said.
                self.core.bus.emit(
                    "assistant.done",
                    AssistantDoneEvent(
                        turn_id=turn_id,
                        text=session.answer,
                        interrupted=True if metrics.interrupted else None,
                    ),
                )
                log.info(
                    "voice turn: recognized %.2fs, first audio %s, fast=%s, interrupted=%s",
                    metrics.recognized_s,
                    f"{metrics.first_audio_s:.2f}s" if metrics.first_audio_s is not None else "-",
                    metrics.fast,
                    metrics.interrupted,
                )
        return session.answer

    async def _play(self, chunks: AsyncIterator[bytes]) -> None:
        try:
            await self.sink.play(chunks, self.tts.sample_rate)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("playback failed")
            self._error("audio_output_failed", self._t("output"))

    def _cancel_session(self) -> None:
        """Interrupt the current session. Its cleanup runs on the next loop iteration."""
        session, self._session = self._session, None
        if session is not None and session.task is not None:
            session.task.cancel()
        self._set_mode(Mode.IDLE)

    async def _end_session(self) -> None:
        session = self._session
        self._cancel_session()
        if session is not None and session.task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await session.task

    def _set_mode(self, mode: Mode) -> None:
        if mode is self.mode:
            return
        previous, self.mode = self.mode, mode
        if mode is Mode.LISTENING:
            return
        # While answering the wake detector keeps running for barge-in; resetting it when
        # the answer ends would lose a wake word the user has already started saying.
        wake_was_fed = previous is not Mode.LISTENING and self.config.barge_in
        self._reset_detectors(wake=not wake_was_fed)

    def _reset_detectors(self, *, wake: bool = True) -> None:
        if wake and self.wake is not None:
            self.wake.reset()
        self.vad.reset()
        self._stop_listener.reset()

    # ---- auto-pause ----

    def _track_mic_mute(self, frame: bytes) -> None:
        limit = self.config.mic_muted_after_s
        if limit is None:
            return
        if frame.strip(b"\x00"):
            self._zero_frames = 0
            if self._mic_muted:
                self._mic_muted = False
                self._apply_pause()
            return
        self._zero_frames += 1
        if not self._mic_muted and self._zero_frames >= frames_for(limit * 1000):
            self._mic_muted = True
            self._apply_pause()

    async def _watch_pause(self) -> None:
        assert self.autopause is not None
        while True:
            reason = await self.autopause.check()
            if reason != self._probe_reason:
                self._probe_reason = reason
                self._apply_pause()
            await asyncio.sleep(self.config.pause_poll_s)

    def _apply_pause(self) -> None:
        reason = self._probe_reason or (MIC_MUTED if self._mic_muted else None)
        if reason is not None:
            if self._auto_paused is None and self.core.muted:
                return  # the user muted us; leave it to them
            self._auto_paused = reason
            if not self.core.muted:
                log.info("auto-pause: %s", reason)
                self._cancel_session()
                self.core.set_state("muted", reason)
        elif self._auto_paused is not None:
            log.info("auto-pause over: %s", self._auto_paused)
            self._auto_paused = None
            if self.core.muted:
                self.core.set_state("idle", "resumed")

    # ---- helpers ----

    def _set_state(self, state: AssistantState, reason: str | None = None) -> None:
        if not self.core.muted:
            self.core.set_state(state, reason)

    def _t(self, key: str, language: Language | None = None, **kwargs: str) -> str:
        lang = language or self.core.config.settings.general.language
        return _TEXT[key][lang].format(**kwargs)

    def _error(self, code: str, message: str, *, recoverable: bool = True) -> None:
        self.core.bus.emit("error", ErrorEvent(code=code, message=message, recoverable=recoverable))
