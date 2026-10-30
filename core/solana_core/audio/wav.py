"""WAV files and PCM helpers: read any PCM WAV as 16 kHz mono int16, split it into frames."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from solana_core.audio.base import FRAME_BYTES, SAMPLE_RATE

Pcm = NDArray[np.int16]


def resample(
    samples: NDArray[np.floating] | Pcm, src_rate: int, dst_rate: int = SAMPLE_RATE
) -> Pcm:
    """Linear-interpolation resampling. Good enough for speech at 16 kHz."""
    if src_rate == dst_rate:
        return np.asarray(samples, dtype=np.float64).astype(np.int16)
    duration = len(samples) / src_rate
    count = round(duration * dst_rate)
    positions = np.arange(count) * (src_rate / dst_rate)
    out: NDArray[np.float64] = np.interp(
        positions, np.arange(len(samples)), np.asarray(samples, dtype=np.float64)
    )
    return np.clip(out, -32768, 32767).astype(np.int16)


def read_wav(path: Path | str) -> Pcm:
    """Read an 8/16/24/32-bit PCM WAV, mix down to mono and resample to 16 kHz."""
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.int32) - 128) << 8
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.int32)
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        data = (b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)) << 8 >> 16
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.int32) >> 16
    else:
        raise ValueError(f"unsupported sample width: {width} bytes")
    mono = data.reshape(-1, channels).mean(axis=1) if channels > 1 else data
    return resample(mono, rate)


def write_wav(path: Path | str, samples: Pcm, sample_rate: int = SAMPLE_RATE) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(np.asarray(samples, dtype="<i2").tobytes())


def to_frames(samples: Pcm | bytes, frame_bytes: int = FRAME_BYTES) -> list[bytes]:
    """Split PCM into frames of ``frame_bytes``; the last one is padded with silence."""
    raw = samples if isinstance(samples, bytes) else np.asarray(samples, dtype="<i2").tobytes()
    if rem := len(raw) % frame_bytes:
        raw += bytes(frame_bytes - rem)
    return [raw[i : i + frame_bytes] for i in range(0, len(raw), frame_bytes)]


def rms(pcm: bytes | Pcm) -> float:
    """Root mean square level in int16 units (0..32768)."""
    samples = np.frombuffer(pcm, dtype=np.int16) if isinstance(pcm, bytes) else pcm
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
