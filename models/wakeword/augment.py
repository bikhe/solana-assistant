"""Audio augmentation with plain numpy: speed, gain, reverb, background noise, placement."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from solana_core.audio.base import SAMPLE_RATE
from solana_core.audio.wav import Pcm, resample

Float = NDArray[np.float32]


def to_float(pcm: Pcm) -> Float:
    return pcm.astype(np.float32) / 32768.0


def to_pcm(x: Float) -> Pcm:
    return (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)


def speed(x: Float, factor: float) -> Float:
    """Faster (> 1) or slower playback; pitch moves with it, like a different voice."""
    return to_float(resample(to_pcm(x), round(SAMPLE_RATE * factor)))


def synthetic_rir(rng: np.random.Generator, rt60: float) -> Float:
    """Room impulse response: direct sound plus exponentially decaying noise."""
    n = int(rt60 * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    tail = rng.standard_normal(n) * np.exp(-6.9 * t / rt60)  # -60 dB at rt60
    tail[: int(0.002 * SAMPLE_RATE)] = 0.0  # small gap before the first reflections
    rir = np.concatenate(([1.0], tail * 0.3)).astype(np.float32)
    out: Float = rir / np.sqrt(np.sum(rir**2))
    return out


def reverb(x: Float, rir: Float) -> Float:
    wet = np.convolve(x, rir)[: len(x)].astype(np.float32)
    peak = np.max(np.abs(wet)) or 1.0
    out: Float = wet * (np.max(np.abs(x)) / peak)
    return out


def colored_noise(rng: np.random.Generator, n: int, exponent: float) -> Float:
    """0 = white, 1 = pink, 2 = brown. Unit RMS."""
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n)
    freqs[0] = freqs[1]
    noise = np.fft.irfft(spectrum / freqs ** (exponent / 2), n).astype(np.float32)
    return noise / (np.sqrt(np.mean(noise**2)) or 1.0)


def mix_at_snr(x: Float, noise: Float, snr_db: float) -> Float:
    signal_rms = np.sqrt(np.mean(x**2)) or 1e-4
    noise_rms = np.sqrt(np.mean(noise**2)) or 1e-4
    scale = signal_rms / (noise_rms * 10 ** (snr_db / 20))
    return (x + noise * scale).astype(np.float32)


def background(rng: np.random.Generator, n: int, sources: Sequence[Float]) -> Float:
    """A random piece of a recorded background, or synthetic colored noise."""
    if sources and rng.random() < 0.7:
        src = sources[int(rng.integers(len(sources)))]
        if len(src) < n:
            src = np.tile(src, n // len(src) + 1)
        start = rng.integers(0, len(src) - n + 1)
        piece: Float = src[start : start + n].copy()
        return piece
    return colored_noise(rng, n, float(rng.choice([0.0, 1.0, 2.0])))


def place(
    rng: np.random.Generator, x: Float, length: int, end_margin: tuple[float, float] | None
) -> Float:
    """Put ``x`` into a clip of ``length`` samples.

    With ``end_margin`` (seconds) the phrase ends that far before the clip end, the way the
    detector sees it at the moment it should fire. Without it the position is random.
    """
    out = np.zeros(length, dtype=np.float32)
    x = x[-length:]
    if end_margin is not None:
        margin = int(rng.uniform(*end_margin) * SAMPLE_RATE)
        start = max(length - margin - len(x), 0)
    else:
        start = int(rng.integers(0, length - len(x) + 1))
    out[start : start + len(x)] = x[: length - start]
    return out


def augment(
    rng: np.random.Generator,
    clip: Pcm,
    length: int,
    noise_sources: Sequence[Float],
    end_margin: tuple[float, float] | None,
) -> Pcm:
    """One randomized training example of ``length`` samples."""
    x = to_float(clip)
    if rng.random() < 0.8:
        x = speed(x, rng.uniform(0.88, 1.12))
    if rng.random() < 0.5:
        x = reverb(x, synthetic_rir(rng, rng.uniform(0.15, 0.7)))
    x = place(rng, x, length, end_margin)
    x *= 10 ** (rng.uniform(-18, 0) / 20) / (np.max(np.abs(x)) or 1.0)
    if rng.random() < 0.9:
        x = mix_at_snr(x, background(rng, length, noise_sources), rng.uniform(0, 25))
    return to_pcm(x)
