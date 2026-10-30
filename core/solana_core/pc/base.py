"""PC control contract.

Every method has a default that raises ``NotSupportedError``, so an OS backend only
implements what it can do and the assistant can honestly say "не поддерживается".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class NotSupportedError(Exception):
    """The operation is not available on this OS or desktop environment."""

    def __init__(self, operation: str, reason: str = "") -> None:
        super().__init__(f"{operation}: not supported{f' ({reason})' if reason else ''}")
        self.operation = operation
        self.reason = reason


@dataclass(frozen=True, slots=True)
class AppInfo:
    id: str  # stable id: path, desktop file id or bundle id
    name: str


@dataclass(frozen=True, slots=True)
class WindowInfo:
    id: str
    title: str
    app: str
    focused: bool = False


@dataclass(frozen=True, slots=True)
class MediaInfo:
    playing: bool
    title: str | None = None
    artist: str | None = None
    app: str | None = None


@dataclass(frozen=True, slots=True)
class BatteryInfo:
    percent: float
    charging: bool


@dataclass(frozen=True, slots=True)
class FileHit:
    path: Path
    is_dir: bool = False


@dataclass(slots=True)
class Capabilities:
    """What a backend supports, for the UI and the system prompt."""

    supported: set[str] = field(default_factory=set)
    notes: dict[str, str] = field(default_factory=dict)


class PcBackend:
    """Base class for OS backends. Override what the OS supports."""

    name = "unsupported"

    def capabilities(self) -> Capabilities:
        return Capabilities()

    # Apps
    async def list_apps(self) -> list[AppInfo]:
        raise NotSupportedError("list_apps")

    async def open_app(self, app_id: str) -> None:
        raise NotSupportedError("open_app")

    async def close_app(self, app_id: str) -> None:
        raise NotSupportedError("close_app")

    # Windows
    async def list_windows(self) -> list[WindowInfo]:
        raise NotSupportedError("list_windows")

    async def focus_window(self, window_id: str) -> None:
        raise NotSupportedError("focus_window")

    async def minimize_window(self, window_id: str) -> None:
        raise NotSupportedError("minimize_window")

    async def maximize_window(self, window_id: str) -> None:
        raise NotSupportedError("maximize_window")

    async def close_window(self, window_id: str) -> None:
        raise NotSupportedError("close_window")

    # Sound and media
    async def get_volume(self) -> int:
        """Master volume, 0..100."""
        raise NotSupportedError("get_volume")

    async def set_volume(self, percent: int) -> None:
        raise NotSupportedError("set_volume")

    async def set_muted(self, muted: bool) -> None:
        raise NotSupportedError("set_muted")

    async def media_play_pause(self) -> None:
        raise NotSupportedError("media_play_pause")

    async def media_next(self) -> None:
        raise NotSupportedError("media_next")

    async def media_previous(self) -> None:
        raise NotSupportedError("media_previous")

    async def now_playing(self) -> MediaInfo | None:
        raise NotSupportedError("now_playing")

    # Files (no permanent delete on purpose: only trash)
    async def search_files(self, query: str, limit: int = 20) -> list[FileHit]:
        raise NotSupportedError("search_files")

    async def open_path(self, path: Path) -> None:
        raise NotSupportedError("open_path")

    async def reveal_path(self, path: Path) -> None:
        raise NotSupportedError("reveal_path")

    async def move_path(self, src: Path, dst: Path) -> None:
        raise NotSupportedError("move_path")

    async def trash_path(self, path: Path) -> None:
        raise NotSupportedError("trash_path")

    # Browser
    async def open_url(self, url: str) -> None:
        raise NotSupportedError("open_url")

    # System
    async def get_clipboard(self) -> str:
        raise NotSupportedError("get_clipboard")

    async def set_clipboard(self, text: str) -> None:
        raise NotSupportedError("set_clipboard")

    async def screenshot(self) -> bytes:
        """PNG bytes of the whole screen."""
        raise NotSupportedError("screenshot")

    async def battery(self) -> BatteryInfo | None:
        raise NotSupportedError("battery")

    async def notify(self, title: str, body: str) -> None:
        raise NotSupportedError("notify")

    async def lock_screen(self) -> None:
        raise NotSupportedError("lock_screen")

    async def sleep(self) -> None:
        raise NotSupportedError("sleep")

    async def shutdown(self) -> None:
        raise NotSupportedError("shutdown")


class FakePcBackend(PcBackend):
    """In-memory PC for tests: records every call, keeps volume and clipboard."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.volume = 50
        self.muted = False
        self.clipboard = ""
        self.apps = [AppInfo("browser", "Браузер"), AppInfo("music", "Музыка")]
        self.windows: list[WindowInfo] = []

    def _record(self, op: str, *args: object) -> None:
        self.calls.append((op, args))

    def capabilities(self) -> Capabilities:
        return Capabilities(
            {
                "list_apps",
                "open_app",
                "close_app",
                "list_windows",
                "get_volume",
                "set_volume",
                "set_muted",
                "media_play_pause",
                "open_url",
                "get_clipboard",
                "set_clipboard",
                "notify",
            }
        )

    async def list_apps(self) -> list[AppInfo]:
        return list(self.apps)

    async def open_app(self, app_id: str) -> None:
        self._record("open_app", app_id)
        self.windows.append(WindowInfo(app_id, app_id, app_id, focused=True))

    async def close_app(self, app_id: str) -> None:
        self._record("close_app", app_id)
        self.windows = [w for w in self.windows if w.app != app_id]

    async def list_windows(self) -> list[WindowInfo]:
        return list(self.windows)

    async def get_volume(self) -> int:
        return self.volume

    async def set_volume(self, percent: int) -> None:
        self._record("set_volume", percent)
        self.volume = max(0, min(100, percent))

    async def set_muted(self, muted: bool) -> None:
        self._record("set_muted", muted)
        self.muted = muted

    async def media_play_pause(self) -> None:
        self._record("media_play_pause")

    async def open_url(self, url: str) -> None:
        self._record("open_url", url)

    async def get_clipboard(self) -> str:
        return self.clipboard

    async def set_clipboard(self, text: str) -> None:
        self._record("set_clipboard", text)
        self.clipboard = text

    async def notify(self, title: str, body: str) -> None:
        self._record("notify", title, body)


def get_pc_backend() -> PcBackend:
    """Backend for the current OS.

    WP5a/b/c replace this with ``pc.windows`` / ``pc.linux`` / ``pc.macos`` backends
    chosen by ``sys.platform``. Until then every operation reports "not supported".
    """
    return PcBackend()
