"""PC control backends per OS.

WP5a: Windows and shared tools in pc/tools.py, WP5b: Linux, WP5c: macOS.
"""

from __future__ import annotations

import sys

from solana_core.pc.base import NotSupportedError, PcBackend


def get_pc_backend() -> PcBackend:
    """Backend for the current OS; an unknown OS gets one that supports nothing."""
    if sys.platform == "win32":
        from solana_core.pc.windows.backend import WindowsPcBackend

        return WindowsPcBackend()
    if sys.platform == "darwin":
        from solana_core.pc.macos.backend import MacPcBackend

        return MacPcBackend()
    if sys.platform.startswith("linux"):
        from solana_core.pc.linux.backend import LinuxPcBackend

        return LinuxPcBackend()
    return PcBackend()


__all__ = ["NotSupportedError", "PcBackend", "get_pc_backend"]
