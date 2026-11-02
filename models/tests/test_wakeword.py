"""The training tools work end to end on tiny synthetic data (no TTS, no downloads)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from solana_core.wake.openwakeword import KeywordModel

from wakeword import augment
from wakeword.generate import trim
from wakeword.train import main as train_main


def test_augment_keeps_length_and_range() -> None:
    rng = np.random.default_rng(0)
    clip = (np.sin(np.arange(8000) / 5) * 8000).astype(np.int16)
    noise = [augment.colored_noise(rng, 4000, 1.0)]
    for _ in range(20):
        out = augment.augment(rng, clip, 40_000, noise, (0.05, 0.4))
        assert out.shape == (40_000,) and out.dtype == np.int16
    placed = augment.place(rng, np.ones(100, dtype=np.float32), 1000, (0.0, 0.0))
    assert placed[-100:].all() and not placed[:-100].any()


def test_trim_cuts_silence() -> None:
    pcm = np.concatenate([np.zeros(16000), np.full(1600, 5000), np.zeros(16000)])
    assert len(trim(pcm.astype(np.int16))) == 1600 + 2 * 800


def test_train_exports_a_model_the_core_can_load(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    pos = rng.normal(1.0, 0.3, (200, 16, 96))
    neg = rng.normal(-1.0, 0.3, (400, 16, 96))
    data = tmp_path / "f.npz"
    np.savez(data, x=np.concatenate([pos, neg]), y=np.array([1] * 200 + [0] * 400))
    out = tmp_path / "kw.onnx"
    train_main([str(data), "--out", str(out), "--epochs", "5"])
    model = KeywordModel.from_file(out)
    assert model.keyword == "kw" and model.window == 16
    assert model.score(pos[:1].astype(np.float32)) > 0.9
    assert model.score(neg[:1].astype(np.float32)) < 0.1
