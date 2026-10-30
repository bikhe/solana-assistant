"""Build a training set: synthetic phrases (Piper voices), augmentation, embeddings.

The result is one ``.npz`` with ``x`` (N, 16, 96) embeddings and ``y`` labels (1 = wake word).
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
from solana_core.audio.base import SAMPLE_RATE
from solana_core.audio.wav import Pcm, resample, write_wav
from solana_core.wake.openwakeword import DEFAULT_WINDOW, FeatureExtractor, clip_embeddings

from wakeword import phrases
from wakeword.augment import Float, augment, to_float
from wakeword.common import CLIP_SAMPLES, audio_files, feature_extractor, read_audio

log = logging.getLogger("wakeword.generate")

POSITIVE_END_MARGIN = (0.05, 0.4)  # seconds of audio after the phrase in a positive clip


def trim(pcm: Pcm, level: float = 300.0) -> Pcm:
    """Cut leading and trailing silence from a single-phrase recording."""
    loud = np.flatnonzero(np.abs(pcm) > level)
    if len(loud) == 0:
        return pcm
    pad = int(0.05 * SAMPLE_RATE)
    return pcm[max(loud[0] - pad, 0) : loud[-1] + 1 + pad]


class Synthesizer:
    """Piper voices with randomized speed and expressiveness; every speaker of every model."""

    def __init__(self, voice_paths: list[Path], rng: np.random.Generator) -> None:
        from piper import PiperVoice

        self.rng = rng
        self.voices: list[tuple[Any, int | None]] = []
        for path in voice_paths:
            voice = PiperVoice.load(path)
            speakers = voice.config.num_speakers
            ids: list[int | None] = list(range(speakers)) if speakers > 1 else [None]
            self.voices += [(voice, s) for s in ids]
        if not self.voices:
            raise SystemExit("не найдено ни одного голоса Piper (--voice)")
        log.info("%d voices/speakers", len(self.voices))

    def say(self, text: str) -> Pcm:
        from piper import SynthesisConfig

        voice, speaker = self.voices[self.rng.integers(len(self.voices))]
        config = SynthesisConfig(
            speaker_id=speaker,
            length_scale=float(self.rng.uniform(0.75, 1.35)),
            noise_scale=float(self.rng.uniform(0.4, 0.9)),
            noise_w_scale=float(self.rng.uniform(0.5, 1.0)),
        )
        chunks = list(voice.synthesize(text, syn_config=config))
        audio = np.concatenate([c.audio_int16_array for c in chunks])
        return trim(resample(audio, chunks[0].sample_rate))


def voice_files(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for p in paths:
        found += sorted(p.glob("*.onnx")) if p.is_dir() else [p]
    return found


def background_crops(rng: np.random.Generator, sources: list[Float], count: int) -> Iterator[Pcm]:
    """Random 2.5 s pieces of long recordings (podcasts, TV): real-world negatives."""
    long = [s for s in sources if len(s) > CLIP_SAMPLES]
    for _ in range(count if long else 0):
        src = long[rng.integers(len(long))]
        start = rng.integers(0, len(src) - CLIP_SAMPLES)
        yield (src[start : start + CLIP_SAMPLES] * 32767).astype(np.int16)


def embed_all(
    extractor: FeatureExtractor, clips: Iterator[Pcm], label: int, out: list[Any], save: Path | None
) -> None:
    for i, clip in enumerate(clips):
        if save is not None and i < 20:
            save.mkdir(parents=True, exist_ok=True)
            write_wav(save / f"{label}_{len(out):06d}.wav", clip)
        emb = clip_embeddings(extractor, clip, DEFAULT_WINDOW)
        if emb is not None:
            out.append((emb, label))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wakeword generate", description=__doc__)
    parser.add_argument(
        "--voice",
        type=Path,
        action="append",
        default=[],
        required=True,
        help="Piper voice .onnx (with its .onnx.json) or a folder of them",
    )
    parser.add_argument("--positives", type=int, default=4000)
    parser.add_argument("--negatives", type=int, default=8000)
    parser.add_argument(
        "--noise",
        type=Path,
        action="append",
        default=[],
        help="noise / music / speech audio to mix under the phrases",
    )
    parser.add_argument(
        "--background",
        type=Path,
        action="append",
        default=[],
        help="long speech recordings cut into negative clips",
    )
    parser.add_argument("--background-clips", type=int, default=4000)
    parser.add_argument(
        "--extra-positive",
        type=Path,
        action="append",
        default=[],
        help="your own recordings of the wake word, one phrase per file",
    )
    parser.add_argument(
        "--extra-negative",
        type=Path,
        action="append",
        default=[],
        help="your own recordings of anything else",
    )
    parser.add_argument(
        "--extra-repeats", type=int, default=20, help="augmented copies of each of your recordings"
    )
    parser.add_argument("--out", type=Path, default=Path("work/features.npz"))
    parser.add_argument("--save-examples", type=Path, help="write a few clips here to listen")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    rng = np.random.default_rng(args.seed)
    started = time.monotonic()
    noise = [to_float(read_audio(p)) for p in audio_files(args.noise)]
    background = [to_float(read_audio(p)) for p in audio_files(args.background)]
    extractor = feature_extractor()
    tts = Synthesizer(voice_files(args.voice), rng)

    # Render each text a few times, then augment the renders: TTS is the slow part.
    def rendered(texts: list[str], count: int) -> list[Pcm]:
        renders = max(count // 4, len(texts))
        return [tts.say(texts[i % len(texts)]) for i in range(renders)]

    pos_base = rendered(phrases.POSITIVE, args.positives)
    neg_texts = phrases.HARD_NEGATIVE * 3 + phrases.GENERAL_NEGATIVE
    neg_base = rendered(neg_texts, args.negatives)
    log.info("synthesized %d + %d clips", len(pos_base), len(neg_base))
    own_pos = [trim(read_audio(p)) for p in audio_files(args.extra_positive)]
    own_neg = [read_audio(p) for p in audio_files(args.extra_negative)]
    all_noise = noise + background

    def stream(base: list[Pcm], count: int, margin: tuple[float, float] | None) -> Iterator[Pcm]:
        for i in range(count):
            yield augment(rng, base[i % len(base)], CLIP_SAMPLES, all_noise, margin)

    data: list[Any] = []
    embed_all(
        extractor,
        stream(pos_base, args.positives, POSITIVE_END_MARGIN),
        1,
        data,
        args.save_examples,
    )
    if own_pos:
        count = len(own_pos) * args.extra_repeats
        embed_all(extractor, stream(own_pos, count, POSITIVE_END_MARGIN), 1, data, None)
    embed_all(extractor, stream(neg_base, args.negatives, None), 0, data, args.save_examples)
    if own_neg:
        embed_all(
            extractor, stream(own_neg, len(own_neg) * args.extra_repeats, None), 0, data, None
        )
    embed_all(extractor, background_crops(rng, background, args.background_clips), 0, data, None)
    # Pure noise and near-silence: the model must not fire on an empty room.
    silence = [np.zeros(SAMPLE_RATE // 2, dtype=np.int16)]
    embed_all(extractor, stream(silence, args.negatives // 10, None), 0, data, None)

    x = np.stack([d[0] for d in data]).astype(np.float32)
    y = np.array([d[1] for d in data], dtype=np.uint8)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, x=x, y=y)
    log.info(
        "%s: %d positive, %d negative in %.0f s",
        args.out,
        int(y.sum()),
        int(len(y) - y.sum()),
        time.monotonic() - started,
    )
