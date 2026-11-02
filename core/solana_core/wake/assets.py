"""Model files for voice input: where they live and how to fetch them.

Weights are never in git. The shared models are downloaded once into the user data
dir and checked by SHA-256. Keyword models are put into ``<models dir>/wake/`` by the
training scripts in ``models/`` (or by the model manager later), one ``<keyword>.onnx``
per wake word.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path

log = logging.getLogger(__name__)

APP_NAME = "solana"
OWW_RELEASE = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"

Progress = Callable[[int, int], None]  # (downloaded bytes, total bytes)


@dataclass(frozen=True, slots=True)
class ModelAsset:
    file: str
    url: str
    sha256: str
    license: str


# Feature extractors: Apache-2.0 (derived from Google's speech_embedding model).
MELSPECTROGRAM = ModelAsset(
    "melspectrogram.onnx",
    f"{OWW_RELEASE}/melspectrogram.onnx",
    "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f",
    "Apache-2.0",
)
EMBEDDING = ModelAsset(
    "embedding_model.onnx",
    f"{OWW_RELEASE}/embedding_model.onnx",
    "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f",
    "Apache-2.0",
)
SILERO_VAD = ModelAsset(
    "silero_vad.onnx",
    "https://raw.githubusercontent.com/snakers4/silero-vad/v5.1.2/src/silero_vad/data/silero_vad.onnx",
    "2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f",
    "MIT",
)
VOICE_INPUT_ASSETS = (MELSPECTROGRAM, EMBEDDING, SILERO_VAD)


class ModelDownloadError(RuntimeError):
    """User-facing (Russian) message."""


def models_dir() -> Path:
    """``SOLANA_MODELS_DIR`` if set, otherwise ``<user data dir>/solana/models``."""
    if env := os.environ.get("SOLANA_MODELS_DIR"):
        return Path(env)
    return user_data_path(APP_NAME, appauthor=False) / "models"


def wake_models_dir(base: Path | None = None) -> Path:
    return (base or models_dir()) / "wake"


def keyword_models(base: Path | None = None) -> list[Path]:
    """All installed wake word models, sorted by name."""
    folder = wake_models_dir(base)
    return sorted(folder.glob("*.onnx")) if folder.is_dir() else []


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(asset: ModelAsset, dest: Path, progress: Progress | None) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(asset.url, timeout=30) as response, tmp.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while block := response.read(1 << 16):
                out.write(block)
                done += len(block)
                if progress:
                    progress(done, total)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        msg = f"Не удалось скачать {asset.file}: {e}"
        raise ModelDownloadError(msg) from e
    if sha256_of(tmp) != asset.sha256:
        tmp.unlink(missing_ok=True)
        raise ModelDownloadError(f"Файл {asset.file} скачался повреждённым, попробуйте ещё раз")
    tmp.replace(dest)


async def ensure_asset(
    asset: ModelAsset, base: Path | None = None, progress: Progress | None = None
) -> Path:
    """Path to the asset, downloading it first if it is missing or damaged."""
    dest = (base or models_dir()) / asset.file
    if dest.is_file() and await asyncio.to_thread(sha256_of, dest) == asset.sha256:
        return dest
    log.info("downloading %s", asset.url)
    await asyncio.to_thread(_download, asset, dest, progress)
    return dest
