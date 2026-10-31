"""Text-to-speech providers: Silero (ru), Piper (en, ru) and an OpenAI-compatible cloud.

``create_tts`` builds the voice named in ``settings.voice.tts_provider``; ``speak_stream``
starts speaking an LLM answer before it is complete.
"""

from __future__ import annotations

from solana_core.config import SecretStore
from solana_core.models import ModelError, ModelManager
from solana_core.protocol import Language
from solana_core.tts.base import FakeTTS, TTSProvider, Voice
from solana_core.tts.multi import MultiLanguageTTS
from solana_core.tts.sentences import speak_stream, split_sentences

TTS_PROVIDERS = ("silero", "piper", "openai", "fake")
PIPER_VOICES: dict[Language, str] = {
    "ru": "piper-ru_RU-irina-medium",
    "en": "piper-en_US-amy-medium",
}

__all__ = [
    "TTS_PROVIDERS",
    "FakeTTS",
    "MultiLanguageTTS",
    "TTSProvider",
    "Voice",
    "create_tts",
    "speak_stream",
    "split_sentences",
]


def create_tts(
    provider: str,
    *,
    models: ModelManager,
    secrets: SecretStore,
    voice: str | None = None,
    default_language: Language = "ru",
) -> TTSProvider:
    """Build a voice. Local models must be downloaded first (``ModelError`` otherwise)."""
    if provider == "fake":
        return FakeTTS()
    if provider == "openai":
        from solana_core.stt.openai import OPENAI_SECRET
        from solana_core.tts.openai import OpenAITTS

        return OpenAITTS(secrets.get(OPENAI_SECRET), voice=voice)

    voices: dict[Language, TTSProvider] = {}
    if provider == "silero":
        from solana_core.tts.silero import SileroTTS

        voices["ru"] = SileroTTS(models.require("silero-tts-ru") / "model.pt", speaker=voice)
    elif provider != "piper":
        raise ValueError(f"Unknown TTS provider: {provider}")

    from solana_core.tts.piper import PiperTTS

    for lang, model_id in PIPER_VOICES.items():
        if lang not in voices and models.is_installed(model_id):
            voices[lang] = PiperTTS(models.path(model_id) / "voice.onnx")
    if not voices:
        raise ModelError(f"Не скачан ни один голос для {provider}")
    return MultiLanguageTTS(voices, default=default_language)
