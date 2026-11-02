"""PCM helpers and language guessing shared by the recognizers."""

from __future__ import annotations

import io
import wave

import numpy as np
import numpy.typing as npt

from solana_core.audio.base import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH
from solana_core.protocol import Language

_LANGUAGE_NAMES: dict[str, Language] = {
    "ru": "ru",
    "rus": "ru",
    "russian": "ru",
    "en": "en",
    "eng": "en",
    "english": "en",
}


def pcm16_to_float32(audio: bytes) -> npt.NDArray[np.float32]:
    """int16 PCM to float32 samples in [-1, 1]."""
    samples = np.frombuffer(audio[: len(audio) // 2 * 2], dtype="<i2")
    return samples.astype(np.float32) / 32768.0


def float32_to_pcm16(samples: npt.ArrayLike) -> bytes:
    data = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    return (data * 32767.0).astype("<i2").tobytes()


def pcm16_to_wav(audio: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(sample_rate)
        wav.writeframes(audio)
    return out.getvalue()


def read_wav(data: bytes | str) -> tuple[bytes, int]:
    """PCM frames and sample rate of a mono 16-bit WAV (bytes or a file path)."""
    source = io.BytesIO(data) if isinstance(data, bytes) else data
    with wave.open(source, "rb") as wav:
        if wav.getsampwidth() != SAMPLE_WIDTH or wav.getnchannels() != CHANNELS:
            raise ValueError("expected mono 16-bit PCM WAV")
        return wav.readframes(wav.getnframes()), wav.getframerate()


def duration_s(audio: bytes, sample_rate: int = SAMPLE_RATE) -> float:
    return len(audio) / (SAMPLE_WIDTH * sample_rate)


def normalize_language(value: str | None) -> Language | None:
    """Map engine language codes or names ("ru", "russian", "en-US") to ours."""
    if not value:
        return None
    key = value.strip().lower().split("-")[0].split("_")[0]
    return _LANGUAGE_NAMES.get(key)


def guess_language(text: str) -> Language | None:
    """Russian if Cyrillic words are at least as many as Latin ones ("Открой YouTube")."""
    cyrillic = latin = 0
    for word in text.lower().split():
        if any("а" <= c <= "я" or c == "ё" for c in word):
            cyrillic += 1
        elif any("a" <= c <= "z" for c in word):
            latin += 1
    if cyrillic == latin == 0:
        return None
    return "ru" if cyrillic >= latin else "en"


def resample_pcm16(audio: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Linear resampling, good enough for speech between 16 and 48 kHz."""
    if src_rate == dst_rate or not audio:
        return audio
    samples = np.frombuffer(audio[: len(audio) // 2 * 2], dtype="<i2").astype(np.float32)
    count = max(1, round(len(samples) * dst_rate / src_rate))
    positions = np.linspace(0, len(samples) - 1, count)
    out = np.interp(positions, np.arange(len(samples)), samples)
    return out.round().astype("<i2").tobytes()


def slice_pcm16(audio: bytes, sample_rate: int, ms: int = 100) -> list[bytes]:
    """Cut PCM into short chunks, so playback can stop between them."""
    step = sample_rate * ms // 1000 * 2
    return [audio[i : i + step] for i in range(0, len(audio), step)]
