"""Measure a wake word model the way Solana runs it (streaming, behind the VAD gate).

* recall: share of phrase recordings that wake the assistant (target >= 90 %);
* false wakes per hour on long background audio: podcasts, TV (target <= 1);
* CPU in silence, % of one core (target < 5 %).
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import numpy as np
from solana_core.audio.base import SAMPLE_RATE
from solana_core.audio.vad import SileroVAD
from solana_core.audio.wav import Pcm, to_frames
from solana_core.wake.base import WakeWordDetector
from solana_core.wake.gate import VadGatedDetector
from solana_core.wake.openwakeword import FeatureExtractor, KeywordModel, OpenWakeWordDetector

from wakeword.common import audio_files, feature_paths, read_audio

log = logging.getLogger("wakeword.evaluate")

TARGET_RECALL = 0.90
TARGET_FALSE_PER_HOUR = 1.0
TARGET_CPU_PERCENT = 5.0


class Factory:
    def __init__(self, models: list[Path], sensitivity: float, gate: bool) -> None:
        self.mel, self.emb, self.vad = feature_paths()
        self.keywords = [KeywordModel.from_file(m) for m in models]
        self.sensitivity = sensitivity
        self.gate = gate

    def __call__(self) -> WakeWordDetector:
        features = FeatureExtractor.from_files(self.mel, self.emb)
        detector = OpenWakeWordDetector(features, self.keywords, self.sensitivity)
        return VadGatedDetector(detector, SileroVAD(self.vad)) if self.gate else detector


def quiet_noise(seconds: float, rng: np.random.Generator, level: float = 30.0) -> Pcm:
    return (rng.standard_normal(int(seconds * SAMPLE_RATE)) * level).astype(np.int16)


def recall(build: Factory, files: list[Path]) -> tuple[float, list[str]]:
    """Each file is one phrase; it counts if the detector fires anywhere in it."""
    rng = np.random.default_rng(0)
    missed: list[str] = []
    for path in files:
        audio = np.concatenate((quiet_noise(1.0, rng), read_audio(path), quiet_noise(1.0, rng)))
        detector = build()
        if not any(detector.process(f) for f in to_frames(audio)):
            missed.append(path.name)
    return (1 - len(missed) / len(files)) if files else 0.0, missed


def false_wakes(build: Factory, files: list[Path]) -> tuple[int, float]:
    """(detections, hours of audio) over long background recordings."""
    count, seconds = 0, 0.0
    for path in files:
        audio = read_audio(path)
        seconds += len(audio) / SAMPLE_RATE
        detector = build()
        hits = [i for i, f in enumerate(to_frames(audio)) if detector.process(f)]
        for i in hits:
            log.info("false wake in %s at %.1f s", path.name, i * 0.02)
        count += len(hits)
    return count, seconds / 3600


def cpu_in_silence(build: Factory, seconds: float = 60.0) -> float:
    """Process time per second of quiet room noise, as % of one core."""
    detector = build()
    frames = to_frames(quiet_noise(seconds, np.random.default_rng(1)))
    started = time.process_time()
    for f in frames:
        detector.process(f)
    return (time.process_time() - started) / seconds * 100


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wakeword evaluate", description=__doc__)
    parser.add_argument("model", type=Path, nargs="+", help="keyword .onnx model(s)")
    parser.add_argument(
        "--positives",
        type=Path,
        action="append",
        default=[],
        help="recordings of the wake word (files or folders)",
    )
    parser.add_argument(
        "--background",
        type=Path,
        action="append",
        default=[],
        help="long recordings without the wake word (podcasts, TV)",
    )
    parser.add_argument("--sensitivity", type=float, default=0.5)
    parser.add_argument("--no-gate", action="store_true", help="run without the VAD gate")
    parser.add_argument("--json", type=Path, help="also write results here")
    args = parser.parse_args(argv)

    build = Factory(args.model, args.sensitivity, not args.no_gate)
    result: dict[str, object] = {"sensitivity": args.sensitivity, "gate": not args.no_gate}
    lines = []
    if positives := audio_files(args.positives):
        share, missed = recall(build, positives)
        result |= {"recall": share, "positives": len(positives), "missed": missed}
        ok = "OK" if share >= TARGET_RECALL else "мало"
        lines.append(f"Срабатывания: {share:.1%} из {len(positives)} записей ({ok})")
    if background := audio_files(args.background):
        count, hours = false_wakes(build, background)
        per_hour = count / hours if hours else 0.0
        result |= {"false_wakes": count, "background_hours": hours, "false_per_hour": per_hour}
        ok = "OK" if per_hour <= TARGET_FALSE_PER_HOUR else "много"
        lines.append(f"Ложные: {count} за {hours:.2f} ч = {per_hour:.2f} в час ({ok})")
    cpu = cpu_in_silence(build)
    result["cpu_percent_silence"] = cpu
    ok = "OK" if cpu < TARGET_CPU_PERCENT else "много"
    lines.append(f"CPU в тишине: {cpu:.2f}% одного ядра ({ok})")
    print("\n".join(lines))
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
