"""Build the real voice pipeline from settings and keep it running.

The pipeline is rebuilt when a setting it was built from changes (devices, engines, voice,
language, wake word on/off). Timings and the wake sensitivity are read live and need no
rebuild. If something is missing (no model downloaded, no microphone), the core keeps
working for text chat and retries later.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from solana_core.audio.vad import SileroVAD
from solana_core.config.models import Settings
from solana_core.models import ModelManager
from solana_core.pipeline.autopause import AutoPause, default_probes
from solana_core.pipeline.voice import PipelineConfig, VoicePipeline
from solana_core.protocol.generated import ErrorEvent
from solana_core.server.core import Core
from solana_core.stt import create_stt
from solana_core.tts import create_tts
from solana_core.tts.playback import SoundDeviceSink
from solana_core.wake.assets import SILERO_VAD, ensure_asset
from solana_core.wake.factory import build_microphone, build_wake_detector

log = logging.getLogger(__name__)

RETRY_S = 30.0
POLL_S = 2.0


def rebuild_key(settings: Settings) -> tuple[Any, ...]:
    """The settings a built pipeline depends on."""
    v = settings.voice
    return (
        v.input_device,
        v.output_device,
        v.stt_provider,
        v.tts_provider,
        v.tts_voice,
        v.wake_word_enabled,
        settings.general.language,
    )


async def build_pipeline(
    core: Core, models: ModelManager | None = None, config: PipelineConfig | None = None
) -> VoicePipeline:
    """Raises if an engine is unknown, a model is not downloaded or a download fails."""
    settings = core.config.settings
    voice = settings.voice
    models = models or ModelManager()
    stt = create_stt(voice.stt_provider, models=models, secrets=core.secrets)
    tts = create_tts(
        voice.tts_provider,
        models=models,
        secrets=core.secrets,
        voice=voice.tts_voice,
        default_language=settings.general.language,
    )
    wake = await build_wake_detector(voice)
    vad = SileroVAD(await ensure_asset(SILERO_VAD))
    return VoicePipeline(
        core,
        build_microphone(voice),
        vad=vad,
        stt=stt,
        tts=tts,
        sink=SoundDeviceSink(voice.output_device),
        wake=wake,
        autopause=AutoPause(default_probes()),
        config=config,
    )


async def _settings_changed(core: Core, key: tuple[Any, ...], timeout_s: float | None) -> None:
    loop = asyncio.get_running_loop()
    deadline = None if timeout_s is None else loop.time() + timeout_s
    while rebuild_key(core.config.settings) == key:
        if deadline is not None and loop.time() >= deadline:
            return
        await asyncio.sleep(POLL_S)


async def run_voice(core: Core, models: ModelManager | None = None) -> None:
    """Run the voice pipeline for the lifetime of the core."""
    last_error = ""
    while True:
        key = rebuild_key(core.config.settings)
        try:
            pipeline = await build_pipeline(core, models)
        except Exception as exc:
            message = f"Голосовой режим недоступен: {exc}"
            log.warning("%s", message)
            if message != last_error:
                last_error = message
                core.bus.emit(
                    "error",
                    ErrorEvent(code="voice_unavailable", message=message, recoverable=True),
                )
            await _settings_changed(core, key, RETRY_S)
            continue
        last_error = ""
        log.info("voice pipeline started")
        running = asyncio.create_task(pipeline.run())
        changed = asyncio.create_task(_settings_changed(core, key, None))
        try:
            done, _ = await asyncio.wait({running, changed}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (running, changed):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        if changed in done:
            log.info("voice settings changed, rebuilding the pipeline")
        else:
            # The microphone went away: the pipeline already reported it. Try again later.
            await _settings_changed(core, key, RETRY_S)
