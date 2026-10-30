"""Model weights: catalog, downloads with progress and hash checks, hardware-based choice."""

from solana_core.models.catalog import CATALOG, ModelFile, ModelSpec
from solana_core.models.hardware import Hardware, detect_hardware, recommend_stt
from solana_core.models.manager import (
    HashMismatchError,
    ModelError,
    ModelManager,
    Progress,
    default_models_dir,
)

__all__ = [
    "CATALOG",
    "Hardware",
    "HashMismatchError",
    "ModelError",
    "ModelFile",
    "ModelManager",
    "ModelSpec",
    "Progress",
    "default_models_dir",
    "detect_hardware",
    "recommend_stt",
]
