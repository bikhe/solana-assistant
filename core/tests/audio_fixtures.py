"""Synthetic WAV fixtures: silence, quiet noise and a loud speech-like burst."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from solana_core.audio.base import SAMPLE_RATE
from solana_core.audio.wav import Pcm, write_wav


def silence(seconds: float) -> Pcm:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.int16)


def noise(seconds: float, level: float = 20.0, seed: int = 0) -> Pcm:
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(int(seconds * SAMPLE_RATE)) * level).astype(np.int16)


def burst(seconds: float, level: float = 6000.0) -> Pcm:
    """A vowel-like signal: 150 Hz harmonics with a slow amplitude wobble."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    voice = sum(np.sin(2 * np.pi * 150 * k * t) / k for k in range(1, 8))
    envelope = 0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)
    return (voice * envelope * level / 2).astype(np.int16)


def phrase_wav(path: Path) -> Path:
    """1 s of quiet noise, 1 s of "speech", 2 s of quiet noise."""
    write_wav(path, np.concatenate((noise(1.0), burst(1.0), noise(2.0, seed=1))))
    return path
