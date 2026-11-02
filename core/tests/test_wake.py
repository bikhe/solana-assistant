"""WP1 wake word: openWakeWord-style runtime, VAD gate, model files and the factory."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from solana_core.audio.base import FRAME_BYTES
from solana_core.audio.onnx import Array
from solana_core.audio.vad import EnergyVAD, SileroVAD
from solana_core.audio.wav import read_wav, to_frames, write_wav
from solana_core.config.models import VoiceSettings
from solana_core.wake import assets
from solana_core.wake.assets import ModelAsset, ModelDownloadError, ensure_asset, keyword_models
from solana_core.wake.base import WakeDetection, WakeWordDetector
from solana_core.wake.factory import build_wake_detector
from solana_core.wake.gate import VadGatedDetector
from solana_core.wake.openwakeword import (
    FeatureExtractor,
    KeywordModel,
    OpenWakeWordDetector,
    clip_embeddings,
    threshold_for,
)
from tests.audio_fixtures import burst, noise, phrase_wav, silence


class FakeFeatureModels:
    """Mel = loudness of the chunk; embedding = mean of the mel window. Records shapes."""

    def __init__(self) -> None:
        self.mel_shapes: list[tuple[int, ...]] = []
        self.embed_shapes: list[tuple[int, ...]] = []

    def mel(self, x: Array) -> Array:
        self.mel_shapes.append(x.shape)
        level = np.sqrt(np.mean(x[0, -1280:] ** 2)) / 1000.0
        return np.full((8, 32), (level - 2.0) * 10.0, dtype=np.float32)  # undone by /10 + 2

    def embed(self, x: Array) -> Array:
        self.embed_shapes.append(x.shape)
        return np.full((len(x), 96), float(x[:, -8:].mean()), dtype=np.float32)

    def extractor(self) -> FeatureExtractor:
        return FeatureExtractor(self.mel, self.embed)


def loud_keyword(name: str = "эй_солана", window: int = 16, peak: float = 0.9) -> KeywordModel:
    """Scores ``peak`` while the latest embedding is loud, so a burst wakes it up."""
    return KeywordModel(name, lambda x: peak if float(x[0, -1, 0]) > 1.0 else 0.01, window)


def test_feature_extractor_shapes_and_warmup() -> None:
    models = FakeFeatureModels()
    features = models.extractor()
    # First mel needs 1280 + 480 samples (2 chunks); 76 mel frames need 10 chunks after that.
    assert features.push(burst(0.08 * 10)) == 0
    assert features.push(burst(0.08)) == 1
    assert models.mel_shapes[0] == (1, 1760)
    assert models.embed_shapes == [(1, 76, 32, 1)]
    assert features.push(burst(0.08 * 3 + 0.04)) == 3  # half a chunk stays pending
    assert features.embeddings.shape == (4, 96)
    features.reset()
    assert features.embeddings.shape == (0, 96)


def test_clip_embeddings_needs_enough_audio() -> None:
    features = FakeFeatureModels().extractor()
    assert clip_embeddings(features, burst(1.0)) is None
    emb = clip_embeddings(features, burst(2.2))
    assert emb is not None and emb.shape == (16, 96)


def test_sensitivity_maps_to_threshold() -> None:
    assert threshold_for(0.5) == 0.5
    assert threshold_for(0.8) == pytest.approx(0.2)
    assert threshold_for(1.0) == 0.05
    assert threshold_for(0.0) == 0.95


def frames_of(*parts: np.ndarray) -> list[bytes]:
    return to_frames(np.concatenate(parts))


def test_detector_fires_once_per_phrase() -> None:
    detector = OpenWakeWordDetector(FakeFeatureModels().extractor(), [loud_keyword()])
    hits = [
        (i, hit)
        for i, f in enumerate(frames_of(noise(2.0), burst(0.5), noise(2.0), burst(0.5), noise(2.0)))
        if (hit := detector.process(f))
    ]
    assert len(hits) == 2
    assert hits[0][1] == WakeDetection("эй_солана", 0.9)
    assert 100 <= hits[0][0] < 125  # during the first burst
    assert detector.last_scores["эй_солана"] < 0.5  # back to quiet at the end


def test_detector_sensitivity_and_best_keyword() -> None:
    quiet = loud_keyword("тихо", peak=0.4)
    loud = loud_keyword("громко")
    detector = OpenWakeWordDetector(FakeFeatureModels().extractor(), [quiet], sensitivity=0.5)
    assert not any(detector.process(f) for f in frames_of(noise(2.0), burst(0.5)))
    detector = OpenWakeWordDetector(FakeFeatureModels().extractor(), [quiet], sensitivity=0.7)
    assert any(detector.process(f) for f in frames_of(noise(2.0), burst(0.5)))
    detector = OpenWakeWordDetector(FakeFeatureModels().extractor(), [quiet, loud], 0.9)
    hits = [h for f in frames_of(noise(2.0), burst(0.5)) if (h := detector.process(f))]
    assert [h.keyword for h in hits] == ["громко"]
    with pytest.raises(ValueError):
        OpenWakeWordDetector(FakeFeatureModels().extractor(), [])


class RecordingDetector(WakeWordDetector):
    """Counts frames and fires on the first loud frame it sees."""

    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.resets = 0

    def process(self, frame: bytes) -> WakeDetection | None:
        self.frames.append(frame)
        loud = np.abs(np.frombuffer(frame, dtype=np.int16)).max() > 3000
        return WakeDetection("x", 1.0) if loud else None

    def reset(self) -> None:
        self.resets += 1


def test_gate_keeps_detector_idle_in_silence(tmp_path: Path) -> None:
    inner = RecordingDetector()
    gate = VadGatedDetector(inner, EnergyVAD(threshold=300), preroll_s=2.0, hangover_ms=1000)
    frames = to_frames(read_wav(phrase_wav(tmp_path / "p.wav")))
    hits = [gate.process(f) for f in frames]
    assert all(h is None for h in hits[:50])
    assert hits[50] == WakeDetection("x", 1.0)  # fired during the pre-roll replay
    assert inner.resets == 1
    # Pre-roll of 51 frames (1 s noise + first speech frame), the burst, then the hangover.
    assert len(inner.frames[:51]) == 51 and inner.frames[50] == frames[50]
    hangover = 10 + 49  # EnergyVAD's own 200 ms plus the gate's ~1 s
    assert len(inner.frames) == 51 + 49 + hangover
    assert gate.active_frames == len(inner.frames)
    assert not gate.active


def test_gate_passes_sensitivity_through() -> None:
    inner = OpenWakeWordDetector(FakeFeatureModels().extractor(), [loud_keyword()], 0.3)
    gate = VadGatedDetector(inner, EnergyVAD())
    assert gate.sensitivity == 0.3
    gate.sensitivity = 0.9
    assert inner.sensitivity == 0.9


def test_gated_openwakeword_on_wav_fixture(tmp_path: Path) -> None:
    """The whole chain on a WAV file: noise, a phrase, noise. One detection, during it."""
    path = tmp_path / "p.wav"
    write_wav(path, np.concatenate((noise(2.5), burst(1.0), noise(2.0, seed=1))))
    inner = OpenWakeWordDetector(FakeFeatureModels().extractor(), [loud_keyword()])
    gate = VadGatedDetector(inner, EnergyVAD(threshold=300))
    hits = [(i, h) for i, f in enumerate(to_frames(read_wav(path))) if (h := gate.process(f))]
    assert len(hits) == 1 and 125 <= hits[0][0] < 175


def test_gate_in_silence_costs_only_vad() -> None:
    inner = RecordingDetector()
    gate = VadGatedDetector(inner, EnergyVAD())
    for f in to_frames(silence(60.0)):
        gate.process(f)
    assert inner.frames == [] and gate.active_frames == 0


@pytest.fixture
def asset(tmp_path: Path) -> ModelAsset:
    src = tmp_path / "src" / "tiny.onnx"
    src.parent.mkdir()
    src.write_bytes(b"model bytes")
    return ModelAsset("tiny.onnx", src.as_uri(), hashlib.sha256(b"model bytes").hexdigest(), "MIT")


async def test_ensure_asset_downloads_once_and_checks_hash(
    asset: ModelAsset, tmp_path: Path
) -> None:
    base = tmp_path / "models"
    seen: list[tuple[int, int]] = []
    path = await ensure_asset(asset, base, lambda done, total: seen.append((done, total)))
    assert path.read_bytes() == b"model bytes" and seen[-1][0] == 11
    seen.clear()
    assert await ensure_asset(asset, base, lambda d, t: seen.append((d, t))) == path
    assert seen == []  # already there
    with pytest.raises(ModelDownloadError):
        await ensure_asset(replace(asset, file="bad.onnx", sha256="0" * 64), base)
    assert not (base / "bad.onnx").exists() and not (base / "bad.onnx.part").exists()
    with pytest.raises(ModelDownloadError):
        await ensure_asset(replace(asset, file="gone.onnx", url=asset.url + "x"), base)


def test_models_dir_and_keyword_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLANA_MODELS_DIR", str(tmp_path))
    assert assets.models_dir() == tmp_path
    assert keyword_models() == []
    (tmp_path / "wake").mkdir()
    (tmp_path / "wake" / "ey_solana.onnx").write_bytes(b"")
    (tmp_path / "wake" / "notes.txt").write_bytes(b"")
    assert [p.name for p in keyword_models()] == ["ey_solana.onnx"]


async def test_factory_without_models_or_when_disabled(tmp_path: Path) -> None:
    assert await build_wake_detector(VoiceSettings(wake_word_enabled=False), tmp_path) is None
    assert await build_wake_detector(VoiceSettings(), tmp_path) is None


REAL_MODELS = Path(os.environ.get("SOLANA_TEST_MODELS", "/nonexistent"))


@pytest.mark.skipif(
    not (REAL_MODELS / "melspectrogram.onnx").is_file(),
    reason="set SOLANA_TEST_MODELS to a folder with the downloaded ONNX models",
)
def test_real_models_stay_quiet_on_noise() -> None:
    """Optional smoke test with the real ONNX files (never runs in CI)."""
    features = FeatureExtractor.from_files(
        REAL_MODELS / "melspectrogram.onnx", REAL_MODELS / "embedding_model.onnx"
    )
    keywords = [KeywordModel.from_file(p) for p in sorted((REAL_MODELS / "wake").glob("*.onnx"))]
    vad = SileroVAD(REAL_MODELS / "silero_vad.onnx")
    assert not any(vad.is_speech(f) for f in to_frames(noise(2.0)))
    if keywords:
        detector = OpenWakeWordDetector(features, keywords)
        assert not any(detector.process(f) for f in to_frames(noise(5.0, level=300)))
    emb = clip_embeddings(features, noise(2.0, level=300))
    assert emb is not None and emb.shape == (16, 96)
    assert len(to_frames(noise(1.0))[0]) == FRAME_BYTES
