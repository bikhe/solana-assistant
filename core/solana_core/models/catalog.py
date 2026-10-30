"""Downloadable model weights: what exists, where it comes from and how big it is.

Sizes are approximate until the server reports ``Content-Length``. A file with a pinned
``sha256`` is verified against it; otherwise the manager uses the SHA-256 that Hugging Face
reports for LFS files (``X-Linked-Etag``) and records the result in the model's manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from solana_core.protocol import Language

ModelKind = Literal["wake", "vad", "stt", "tts", "llm", "embedding"]

_HF = "https://huggingface.co"
_MB = 1_000_000


@dataclass(frozen=True, slots=True)
class ModelFile:
    url: str
    path: str  # relative to the model folder
    size: int  # bytes, approximate
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    kind: ModelKind
    name: str
    engine: str
    files: tuple[ModelFile, ...]
    languages: tuple[Language, ...]
    license: str
    min_ram_gb: float = 0.0

    @property
    def size_bytes(self) -> int:
        return sum(f.size for f in self.files)


def _hf(repo: str, path: str, size: int, local: str | None = None) -> ModelFile:
    return ModelFile(f"{_HF}/{repo}/resolve/main/{path}", local or path, size)


def _faster_whisper(model_id: str, name: str, repo: str, size_mb: int, ram: float) -> ModelSpec:
    files = (
        _hf(repo, "config.json", 3_000),
        _hf(repo, "tokenizer.json", 2_200_000),
        _hf(repo, "vocabulary.txt", 460_000),
        _hf(repo, "model.bin", size_mb * _MB),
    )
    return ModelSpec(
        model_id, "stt", name, "faster-whisper", files, ("ru", "en"), "MIT", min_ram_gb=ram
    )


def _whisper_cpp(model_id: str, name: str, filename: str, size_mb: int, ram: float) -> ModelSpec:
    files = (_hf("ggerganov/whisper.cpp", filename, size_mb * _MB, "model.bin"),)
    return ModelSpec(
        model_id, "stt", name, "whisper.cpp", files, ("ru", "en"), "MIT", min_ram_gb=ram
    )


def _piper(voice: str, name: str, language: Language, size_mb: int) -> ModelSpec:
    lang_dir = {"ru": "ru/ru_RU", "en": "en/en_US"}[language]
    speaker, quality = voice.split("-")[1:]
    base = f"{lang_dir}/{speaker}/{quality}/{voice}"
    files = (
        _hf("rhasspy/piper-voices", f"{base}.onnx", size_mb * _MB, "voice.onnx"),
        _hf("rhasspy/piper-voices", f"{base}.onnx.json", 5_000, "voice.onnx.json"),
    )
    # Voice licenses differ: see MODEL_CARD next to each voice on Hugging Face.
    return ModelSpec(f"piper-{voice}", "tts", name, "piper", files, (language,), "see MODEL_CARD")


CATALOG: dict[str, ModelSpec] = {
    spec.id: spec
    for spec in (
        _faster_whisper(
            "faster-whisper-base", "Whisper base (CPU)", "Systran/faster-whisper-base", 145, 2
        ),
        _faster_whisper(
            "faster-whisper-small", "Whisper small (CPU)", "Systran/faster-whisper-small", 484, 4
        ),
        _faster_whisper(
            "faster-whisper-large-v3-turbo",
            "Whisper large-v3-turbo (CUDA)",
            "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
            1_620,
            8,
        ),
        _whisper_cpp("whisper-cpp-base", "Whisper base (whisper.cpp)", "ggml-base.bin", 148, 2),
        _whisper_cpp("whisper-cpp-small", "Whisper small (whisper.cpp)", "ggml-small.bin", 488, 4),
        _whisper_cpp(
            "whisper-cpp-large-v3-turbo",
            "Whisper large-v3-turbo q5 (whisper.cpp, Vulkan)",
            "ggml-large-v3-turbo-q5_0.bin",
            574,
            6,
        ),
        ModelSpec(
            "gigaam-v3-ctc",
            "stt",
            "GigaAM v3 CTC (русский)",
            "gigaam",
            (
                _hf("istupakov/gigaam-v3-onnx", "v3_ctc.int8.onnx", 225 * _MB),
                _hf("istupakov/gigaam-v3-onnx", "v3_vocab.txt", 1_000),
            ),
            ("ru",),
            "MIT",
            min_ram_gb=2,
        ),
        ModelSpec(
            "silero-tts-ru",
            "tts",
            "Silero TTS v4 (русский)",
            "silero",
            (ModelFile("https://models.silero.ai/models/tts/ru/v4_ru.pt", "model.pt", 40 * _MB),),
            ("ru",),
            # Weights only, downloaded by the user at runtime and never bundled.
            "CC BY-NC-SA 4.0",
            min_ram_gb=1,
        ),
        _piper("ru_RU-irina-medium", "Piper Irina (русский)", "ru", 63),
        _piper("en_US-amy-medium", "Piper Amy (English)", "en", 63),
    )
}
