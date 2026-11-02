"""Shared helpers: feature models, reading audio of any format, finding files."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

import numpy as np
from solana_core.audio.base import SAMPLE_RATE
from solana_core.audio.wav import Pcm, read_wav
from solana_core.wake.assets import EMBEDDING, MELSPECTROGRAM, SILERO_VAD, ensure_asset
from solana_core.wake.openwakeword import FeatureExtractor

AUDIO_SUFFIXES = {".wav", ".mp3", ".ogg", ".opus", ".flac", ".m4a", ".webm", ".mkv", ".mp4"}
CLIP_SECONDS = 2.5  # long enough for 16 embeddings (~2.1 s) plus a little slack
CLIP_SAMPLES = int(CLIP_SECONDS * SAMPLE_RATE)


def feature_paths() -> tuple[Path, Path, Path]:
    """Download (once) and return melspectrogram, embedding and Silero VAD models."""

    async def fetch() -> tuple[Path, Path, Path]:
        return (
            await ensure_asset(MELSPECTROGRAM),
            await ensure_asset(EMBEDDING),
            await ensure_asset(SILERO_VAD),
        )

    return asyncio.run(fetch())


def feature_extractor() -> FeatureExtractor:
    mel, emb, _ = feature_paths()
    return FeatureExtractor.from_files(mel, emb)


def read_audio(path: Path) -> Pcm:
    """WAV directly; anything else through ffmpeg (if it is installed)."""
    if path.suffix.lower() == ".wav":
        return read_wav(path)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit(f"{path.name}: для форматов кроме WAV нужен ffmpeg")
    out = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(out, dtype=np.int16).copy()


def audio_files(paths: Iterable[Path]) -> list[Path]:
    """Audio files from a mix of files and folders (searched recursively)."""
    found: list[Path] = []
    for p in paths:
        if p.is_dir():
            found += sorted(f for f in p.rglob("*") if f.suffix.lower() in AUDIO_SUFFIXES)
        elif p.is_file():
            found.append(p)
        else:
            raise SystemExit(f"нет такого файла или папки: {p}")
    return found
