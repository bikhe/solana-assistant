"""Speech-to-text providers: faster-whisper, whisper.cpp, GigaAM and an OpenAI-compatible cloud.

``create_stt`` builds the provider named in ``settings.voice.stt_provider``. Local engines
import their libraries lazily, so a missing extra only fails when that engine is chosen.
"""

from __future__ import annotations

from solana_core.config import SecretStore
from solana_core.models import Hardware, ModelError, ModelManager, detect_hardware
from solana_core.models.hardware import default_stt_model
from solana_core.stt.base import FakeSTT, STTProvider, Transcript

STT_PROVIDERS = ("faster-whisper", "whisper.cpp", "gigaam", "openai", "fake")

__all__ = ["STT_PROVIDERS", "FakeSTT", "STTProvider", "Transcript", "create_stt"]


def create_stt(
    provider: str,
    *,
    models: ModelManager,
    secrets: SecretStore,
    hardware: Hardware | None = None,
    model_id: str | None = None,
) -> STTProvider:
    """Build a recognizer. Local models must be downloaded first (``ModelError`` otherwise)."""
    if provider == "fake":
        return FakeSTT()
    if provider == "openai":
        from solana_core.stt.openai import OPENAI_SECRET, OpenAISTT

        return OpenAISTT(secrets.get(OPENAI_SECRET))
    if provider not in STT_PROVIDERS:
        raise ValueError(f"Unknown STT provider: {provider}")

    hw = hardware or detect_hardware()
    model_id = model_id or default_stt_model(provider, hw)
    if models.spec(model_id).engine != provider:
        raise ModelError(f"Model {model_id} is not for {provider}")
    path = models.require(model_id)

    if provider == "faster-whisper":
        from solana_core.stt.faster_whisper import FasterWhisperSTT

        return FasterWhisperSTT(path, device="cuda" if hw.cuda else "cpu")
    if provider == "gigaam":
        from solana_core.stt.gigaam import GigaAMSTT

        return GigaAMSTT(path)
    from solana_core.stt.whisper_cpp import WhisperCppSTT

    return WhisperCppSTT(path / "model.bin")
