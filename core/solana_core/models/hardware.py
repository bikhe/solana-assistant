"""What the machine can run, and which speech models fit it.

The reference machine is an AMD RX 6600 (8 GB, no CUDA): GPU speech recognition there goes
through whisper.cpp with Vulkan, everything else runs on the CPU.
"""

from __future__ import annotations

import ctypes.util
import os
import platform
import shutil
import sys
from dataclasses import dataclass
from functools import cache
from typing import Literal

Accelerator = Literal["cpu", "vulkan", "metal", "cuda"]


@dataclass(frozen=True, slots=True)
class Hardware:
    cpu_cores: int
    ram_gb: float
    cuda: bool = False
    vulkan: bool = False
    metal: bool = False

    @property
    def best_accelerator(self) -> Accelerator:
        if self.cuda:
            return "cuda"
        if self.metal:
            return "metal"
        if self.vulkan:
            return "vulkan"
        return "cpu"


@dataclass(frozen=True, slots=True)
class SpeechChoice:
    stt_provider: str
    stt_model: str
    device: Accelerator


@cache
def detect_hardware() -> Hardware:
    return Hardware(
        cpu_cores=os.cpu_count() or 1,
        ram_gb=_ram_gb(),
        cuda=shutil.which("nvidia-smi") is not None,
        vulkan=_has_vulkan(),
        metal=sys.platform == "darwin" and platform.machine() == "arm64",
    )


def recommend_stt(hw: Hardware, *, whisper_cpp_available: bool = False) -> SpeechChoice:
    """Pick the fastest recognizer that keeps good Russian quality on this machine."""
    if hw.cuda and hw.ram_gb >= 8:
        return SpeechChoice("faster-whisper", "faster-whisper-large-v3-turbo", "cuda")
    if whisper_cpp_available and (hw.vulkan or hw.metal) and hw.ram_gb >= 6:
        device: Accelerator = "metal" if hw.metal else "vulkan"
        return SpeechChoice("whisper.cpp", "whisper-cpp-large-v3-turbo", device)
    if hw.ram_gb >= 4 and hw.cpu_cores >= 4:
        return SpeechChoice("faster-whisper", "faster-whisper-small", "cpu")
    return SpeechChoice("faster-whisper", "faster-whisper-base", "cpu")


def default_stt_model(provider: str, hw: Hardware) -> str:
    """Model id for a provider chosen in settings."""
    if provider == "gigaam":
        return "gigaam-v3-ctc"
    if provider == "whisper.cpp":
        big = (hw.vulkan or hw.metal or hw.cuda) and hw.ram_gb >= 6
        return "whisper-cpp-large-v3-turbo" if big else "whisper-cpp-small"
    choice = recommend_stt(hw)
    return choice.stt_model if choice.stt_provider == "faster-whisper" else "faster-whisper-small"


def _has_vulkan() -> bool:
    names = ["vulkan-1"] if sys.platform == "win32" else ["vulkan", "MoltenVK"]
    return any(ctypes.util.find_library(n) for n in names)


def _ram_gb() -> float:
    try:
        if sys.platform == "win32":
            return _ram_gb_windows()
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return float(pages * page_size) / 1024**3
    except (OSError, ValueError, AttributeError):
        return 8.0


def _ram_gb_windows() -> float:
    class MemoryStatus(ctypes.Structure):
        _fields_ = (
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        )

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
    return float(status.ullTotalPhys) / 1024**3
