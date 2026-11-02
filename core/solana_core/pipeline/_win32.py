"""Windows checks for auto-pause: locked screen and microphone users. Imported only on Windows."""

from __future__ import annotations

import ctypes
import sys
import winreg
from collections.abc import Iterator
from ctypes import wintypes

assert sys.platform == "win32"  # tells mypy to skip this module on other platforms

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.OpenInputDesktop.restype = wintypes.HANDLE
user32.GetUserObjectInformationW.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
user32.CloseDesktop.argtypes = [wintypes.HANDLE]

DESKTOP_READOBJECTS = 0x0001
UOI_NAME = 2
CONSENT_STORE = (
    r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
)


def screen_locked() -> bool:
    """While locked, the input desktop is Winlogon and a normal process cannot open it."""
    desk = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
    if not desk:
        return True
    try:
        buf = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        if not user32.GetUserObjectInformationW(
            desk, UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(needed)
        ):
            return False
        return buf.value.lower() != "default"
    finally:
        user32.CloseDesktop(desk)


def _usage(key: winreg.HKEYType, name: str) -> tuple[str, int, int] | None:
    try:
        with winreg.OpenKey(key, name) as sub:
            start = int(winreg.QueryValueEx(sub, "LastUsedTimeStart")[0])
            stop = int(winreg.QueryValueEx(sub, "LastUsedTimeStop")[0])
    except OSError:
        return None
    return name, start, stop


def _subkeys(key: winreg.HKEYType) -> Iterator[str]:
    i = 0
    while True:
        try:
            yield winreg.EnumKey(key, i)
        except OSError:
            return
        i += 1


def microphone_usage() -> list[tuple[str, int, int]]:
    """Every app Windows has seen using the microphone, packaged and unpackaged."""
    out: list[tuple[str, int, int]] = []
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CONSENT_STORE) as root:
        for name in _subkeys(root):
            if name == "NonPackaged":
                with winreg.OpenKey(root, name) as unpackaged:
                    out += [u for n in _subkeys(unpackaged) if (u := _usage(unpackaged, n))]
            elif u := _usage(root, name):
                out.append(u)
    return out
