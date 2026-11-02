"""Auto-pause: stop listening while the screen is locked or another app holds the microphone
for a call. Each check is a ``PauseProbe``; a probe that cannot work on this machine (no
``loginctl``, no ``pactl``) switches itself off after the first failure.

A muted microphone is detected by the pipeline itself: it delivers exact digital zeros.
"""

from __future__ import annotations

import logging
import os
import plistlib
import re
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from pathlib import PureWindowsPath

from solana_core.pc.common import CommandError, Runner, run_command

log = logging.getLogger(__name__)

SCREEN_LOCKED = "screen_locked"
CALL = "call"
MIC_MUTED = "mic_muted"


class PauseProbe(ABC):
    reason: str

    @abstractmethod
    async def active(self) -> bool:
        """True while listening should pause. May raise if the probe cannot work here."""


class FakePauseProbe(PauseProbe):
    def __init__(self, reason: str = SCREEN_LOCKED, value: bool = False) -> None:
        self.reason = reason
        self.value = value

    async def active(self) -> bool:
        return self.value


class AutoPause:
    """Asks every probe in turn and returns the first reason to pause."""

    def __init__(self, probes: Sequence[PauseProbe]) -> None:
        self.probes = list(probes)

    async def check(self) -> str | None:
        for probe in list(self.probes):
            try:
                if await probe.active():
                    return probe.reason
            except Exception as exc:
                log.info("auto-pause probe %s disabled: %s", type(probe).__name__, exc)
                self.probes.remove(probe)
        return None


async def _run(runner: Runner, argv: Sequence[str]) -> str:
    result = await runner(argv, None)
    if not result.ok:
        raise CommandError(f"{argv[0]} failed: {result.stderr.strip()}")
    return result.stdout


class LinuxScreenLock(PauseProbe):
    """``LockedHint`` of the logind session, set by GNOME, KDE and most lockers."""

    reason = SCREEN_LOCKED

    def __init__(self, runner: Runner = run_command, session: str | None = None) -> None:
        self.runner = runner
        self.session = session or os.environ.get("XDG_SESSION_ID") or "self"

    async def active(self) -> bool:
        out = await _run(
            self.runner, ["loginctl", "show-session", self.session, "-p", "LockedHint"]
        )
        return out.strip().lower() == "lockedhint=yes"


# Apps that record without being a call: mixers, meters, our own process.
_NOT_CALLS = frozenset(["pavucontrol", "pulseaudio volume control", "gnome-control-center"])
_PROP = re.compile(r'^\s*(application\.process\.id|application\.name)\s*=\s*"(.*)"\s*$')


def linux_recording_apps(pactl_output: str, own_pid: int) -> list[str]:
    """Names of other apps with an open recording stream, from ``pactl list source-outputs``."""
    apps: list[str] = []
    for block in pactl_output.split("Source Output #")[1:]:
        props: dict[str, str] = {}
        for line in block.splitlines():
            if m := _PROP.match(line):
                props[m.group(1)] = m.group(2)
        name = props.get("application.name", "")
        if props.get("application.process.id") == str(own_pid):
            continue
        if name.lower() in _NOT_CALLS:
            continue
        apps.append(name or "?")
    return apps


class LinuxCall(PauseProbe):
    """Another app (Telegram, Zoom, a browser tab) is recording from PulseAudio/PipeWire."""

    reason = CALL

    def __init__(self, runner: Runner = run_command, own_pid: int | None = None) -> None:
        self.runner = runner
        self.own_pid = own_pid or os.getpid()

    async def active(self) -> bool:
        out = await _run(self.runner, ["pactl", "list", "source-outputs"])
        return bool(linux_recording_apps(out, self.own_pid))


def macos_screen_locked(ioreg_plist: bytes) -> bool:
    """Parse ``ioreg -n Root -d1 -a``: the console user's ``CGSSessionScreenIsLocked``."""
    root = plistlib.loads(ioreg_plist)
    users = root.get("IOConsoleUsers", []) if isinstance(root, dict) else []
    return any(bool(u.get("CGSSessionScreenIsLocked")) for u in users if isinstance(u, dict))


class MacScreenLock(PauseProbe):
    reason = SCREEN_LOCKED

    def __init__(self, runner: Runner = run_command) -> None:
        self.runner = runner

    async def active(self) -> bool:
        out = await _run(self.runner, ["ioreg", "-n", "Root", "-d1", "-a"])
        return macos_screen_locked(out.encode())


# (app key, LastUsedTimeStart, LastUsedTimeStop) from the microphone ConsentStore.
MicUsage = tuple[str, int, int]


def windows_mic_users(entries: Iterable[MicUsage], own_exe: str) -> list[str]:
    """Apps using the microphone right now: started and not yet stopped.

    Unpackaged apps are keyed by their path with ``#`` instead of ``\\``.
    """
    own = str(PureWindowsPath(own_exe)).lower()
    return [
        key
        for key, start, stop in entries
        if start != 0 and stop == 0 and key.replace("#", "\\").lower() != own
    ]


class WindowsCall(PauseProbe):
    reason = CALL

    def __init__(
        self, read: Callable[[], Iterable[MicUsage]] | None = None, own_exe: str = sys.executable
    ) -> None:
        self.read = read
        self.own_exe = own_exe

    async def active(self) -> bool:
        if self.read is not None:
            return bool(windows_mic_users(self.read(), self.own_exe))
        if sys.platform != "win32":
            raise OSError("Windows only")
        from solana_core.pipeline import _win32

        return bool(windows_mic_users(_win32.microphone_usage(), self.own_exe))


class WindowsScreenLock(PauseProbe):
    reason = SCREEN_LOCKED

    async def active(self) -> bool:
        if sys.platform != "win32":
            raise OSError("Windows only")
        from solana_core.pipeline import _win32

        return _win32.screen_locked()


def default_probes() -> list[PauseProbe]:
    if sys.platform == "win32":
        return [WindowsScreenLock(), WindowsCall()]
    if sys.platform == "darwin":
        # macOS has no public way to see who else records, so no call probe.
        return [MacScreenLock()]
    return [LinuxScreenLock(), LinuxCall()]
