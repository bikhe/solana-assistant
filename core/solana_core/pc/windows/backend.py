"""Windows backend: Win32 through ctypes, Core Audio through pycaw, media info through SMTC."""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypeVar

from solana_core.pc.base import AppInfo, Capabilities, MediaInfo, WindowInfo
from solana_core.pc.common import (
    COMMON_CAPABILITIES,
    CommonPcBackend,
    Runner,
    ensure_exists,
    spawn_detached,
)
from solana_core.pc.windows import _win32
from solana_core.pc.windows.shell import (
    ps_command,
    scan_shortcuts,
    shortcut_target_script,
    start_menu_dirs,
    toast_script,
)
from solana_core.tools.base import ToolError

assert sys.platform == "win32"

T = TypeVar("T")


def _process_names() -> dict[int, str]:
    import psutil

    return {p.pid: p.info["name"] or "" for p in psutil.process_iter(["name"])}


def _process_exes() -> dict[int, str]:
    import psutil

    exes: dict[int, str] = {}
    for p in psutil.process_iter(["exe"]):
        with contextlib.suppress(psutil.Error):
            exes[p.pid] = p.info["exe"] or ""
    return exes


def _parse_hwnd(window_id: str) -> int:
    try:
        return int(window_id, 0)
    except ValueError as e:
        raise ToolError("Не нашла такое окно") from e


class WindowsPcBackend(CommonPcBackend):
    name = "windows"

    def __init__(self, runner: Runner | None = None) -> None:
        super().__init__(runner)
        self._com: ThreadPoolExecutor | None = None

    def capabilities(self) -> Capabilities:
        supported = set(COMMON_CAPABILITIES) | {
            "list_apps", "open_app", "close_app",
            "list_windows", "focus_window", "minimize_window", "maximize_window", "close_window",
            "get_volume", "set_volume", "set_muted",
            "media_play_pause", "media_next", "media_previous", "now_playing",
            "open_path", "reveal_path", "open_url",
            "get_clipboard", "set_clipboard", "notify", "lock_screen", "sleep", "shutdown",
        }  # fmt: skip
        return Capabilities(supported)

    async def _in_com_thread(self, fn: Callable[[], T]) -> T:
        """Core Audio needs COM initialised on the calling thread; keep one such thread."""
        if self._com is None:
            import comtypes

            self._com = ThreadPoolExecutor(1, "solana-com", initializer=comtypes.CoInitialize)
        return await asyncio.get_running_loop().run_in_executor(self._com, fn)

    async def _ps(self, script: str) -> str:
        return await self.run_ok(*ps_command(script))

    # Apps

    async def list_apps(self) -> list[AppInfo]:
        shortcuts = await asyncio.to_thread(scan_shortcuts, start_menu_dirs())
        return [AppInfo(path, name) for path, name in shortcuts]

    async def open_app(self, app_id: str) -> None:
        try:
            # Shortcuts, full paths and "App Paths" names like "chrome" or "notepad".
            await asyncio.to_thread(os.startfile, app_id)
        except OSError as e:
            raise ToolError(f"Не нашла приложение «{Path(app_id).stem}»") from e

    async def close_app(self, app_id: str) -> None:
        target = app_id
        if app_id.lower().endswith(".lnk"):
            target = (await self._ps(shortcut_target_script(Path(app_id)))).strip()
        stem = Path(target).stem.casefold()
        exes = await asyncio.to_thread(_process_exes)
        windows = await asyncio.to_thread(_win32.list_windows)
        mine = [
            hwnd
            for hwnd, _, pid in windows
            if exes.get(pid)
            and (
                os.path.normcase(exes[pid]) == os.path.normcase(target)
                or Path(exes[pid]).stem.casefold() == stem
            )
        ]
        if not mine:
            raise ToolError(f"Приложение «{Path(app_id).stem}» не запущено")
        for hwnd in mine:
            with contextlib.suppress(LookupError):
                _win32.close(hwnd)  # WM_CLOSE lets the app ask to save documents

    # Windows

    async def list_windows(self) -> list[WindowInfo]:
        windows, names = await asyncio.gather(
            asyncio.to_thread(_win32.list_windows), asyncio.to_thread(_process_names)
        )
        active = _win32.foreground_window()
        return [
            WindowInfo(hex(hwnd), title, Path(names.get(pid, "")).stem, hwnd == active)
            for hwnd, title, pid in windows
        ]

    async def _window(self, window_id: str, action: Callable[[int], None]) -> None:
        try:
            await asyncio.to_thread(action, _parse_hwnd(window_id))
        except LookupError as e:
            raise ToolError("Это окно уже закрыто") from e

    async def focus_window(self, window_id: str) -> None:
        await self._window(window_id, _win32.focus)

    async def minimize_window(self, window_id: str) -> None:
        await self._window(window_id, lambda h: _win32.show(h, _win32.SW_MINIMIZE))

    async def maximize_window(self, window_id: str) -> None:
        await self._window(window_id, lambda h: _win32.show(h, _win32.SW_MAXIMIZE))

    async def close_window(self, window_id: str) -> None:
        await self._window(window_id, _win32.close)

    # Sound and media

    @staticmethod
    def _endpoint() -> Any:
        from pycaw.pycaw import AudioUtilities

        try:
            return AudioUtilities.GetSpeakers().EndpointVolume
        except Exception as e:  # COMError when there is no output device
            raise ToolError("Не нашла устройство вывода звука") from e

    async def get_volume(self) -> int:
        return await self._in_com_thread(
            lambda: round(self._endpoint().GetMasterVolumeLevelScalar() * 100)
        )

    async def set_volume(self, percent: int) -> None:
        level = max(0, min(100, percent)) / 100
        await self._in_com_thread(lambda: self._endpoint().SetMasterVolumeLevelScalar(level, None))

    async def set_muted(self, muted: bool) -> None:
        await self._in_com_thread(lambda: self._endpoint().SetMute(int(muted), None))

    async def media_play_pause(self) -> None:
        _win32.press_key(_win32.VK_MEDIA_PLAY_PAUSE)

    async def media_next(self) -> None:
        _win32.press_key(_win32.VK_MEDIA_NEXT_TRACK)

    async def media_previous(self) -> None:
        _win32.press_key(_win32.VK_MEDIA_PREV_TRACK)

    async def now_playing(self) -> MediaInfo | None:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
        )

        manager = await Manager.request_async()
        session = manager.get_current_session()
        if session is None:
            return None
        props = await session.try_get_media_properties_async()
        playback = session.get_playback_info()
        app = session.source_app_user_model_id.split("!")[0].removesuffix(".exe")
        return MediaInfo(
            playing=playback.playback_status == Status.PLAYING,
            title=props.title or None,
            artist=props.artist or None,
            app=app or None,
        )

    # Files and browser

    async def open_path(self, path: Path) -> None:
        await ensure_exists(path)
        await asyncio.to_thread(os.startfile, str(path))

    async def reveal_path(self, path: Path) -> None:
        await ensure_exists(path)
        await spawn_detached(["explorer", f"/select,{path}"])

    async def open_url(self, url: str) -> None:
        await asyncio.to_thread(os.startfile, url)

    # System

    async def get_clipboard(self) -> str:
        return await asyncio.to_thread(_win32.get_clipboard)

    async def set_clipboard(self, text: str) -> None:
        await asyncio.to_thread(_win32.set_clipboard, text)

    async def notify(self, title: str, body: str) -> None:
        await self._ps(toast_script(title, body))

    async def lock_screen(self) -> None:
        _win32.lock_screen()

    async def sleep(self) -> None:
        await asyncio.to_thread(_win32.suspend)

    async def shutdown(self) -> None:
        await self.run_ok("shutdown", "/s", "/t", "0")
