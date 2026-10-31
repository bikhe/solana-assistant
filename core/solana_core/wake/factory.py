"""Build the voice input chain from settings: microphone -> Silero VAD gate -> wake word."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from solana_core.audio.mic import SoundDeviceSource
from solana_core.audio.vad import SileroVAD
from solana_core.config.models import VoiceSettings
from solana_core.wake.assets import (
    EMBEDDING,
    MELSPECTROGRAM,
    SILERO_VAD,
    Progress,
    ensure_asset,
    keyword_models,
)
from solana_core.wake.base import WakeWordDetector
from solana_core.wake.gate import VadGatedDetector
from solana_core.wake.openwakeword import FeatureExtractor, KeywordModel, OpenWakeWordDetector

log = logging.getLogger(__name__)


def build_microphone(voice: VoiceSettings) -> SoundDeviceSource:
    return SoundDeviceSource(voice.input_device)


async def build_wake_detector(
    voice: VoiceSettings, base: Path | None = None, progress: Progress | None = None
) -> WakeWordDetector | None:
    """The gated wake word detector, or ``None`` if it is off or no keyword model is installed.

    Downloads the shared feature and VAD models on first use.
    """
    if not voice.wake_word_enabled:
        return None
    keywords = keyword_models(base)
    if not keywords:
        log.warning("no wake word models installed, only push-to-talk will work")
        return None
    mel = await ensure_asset(MELSPECTROGRAM, base, progress)
    emb = await ensure_asset(EMBEDDING, base, progress)
    vad = await ensure_asset(SILERO_VAD, base, progress)

    def load() -> WakeWordDetector:
        detector = OpenWakeWordDetector(
            FeatureExtractor.from_files(mel, emb),
            [KeywordModel.from_file(p) for p in keywords],
            voice.wake_sensitivity,
        )
        return VadGatedDetector(detector, SileroVAD(vad))

    return await asyncio.to_thread(load)
