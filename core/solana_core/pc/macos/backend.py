"""macOS backend: ``open``, AppleScript/JXA through ``osascript``, Spotlight and ``pmset``.

Window tools go through System Events and need the Accessibility permission for the app
that runs the core. Without it ``osascript`` fails and the tool says so.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from pathlib import Path

from solana_core.pc.base import (
    AppInfo,
    Capabilities,
    FileHit,
    MediaInfo,
    NotSupportedError,
    WindowInfo,
)
from solana_core.pc.common import (
    COMMON_CAPABILITIES,
    CommandError,
    CommonPcBackend,
    Runner,
    ensure_exists,
    search_files_sync,
)
from solana_core.tools.base import ToolError

APP_DIRS = [
    Path("/Applications"),
    Path("/Applications/Utilities"),
    Path("/System/Applications"),
    Path("/System/Applications/Utilities"),
    Path.home() / "Applications",
]

ACCESSIBILITY_HINT = (
    "разрешите Solana управлять компьютером: Системные настройки → Конфиденциальность → "
    "Универсальный доступ"
)

# Window ids are "<process name>\x1f<window index>", stable while the window stays open.
SEP = "\x1f"

LIST_WINDOWS_JXA = """
const se = Application('System Events');
const out = [];
for (const p of se.processes.whose({backgroundOnly: false})()) {
  const front = p.frontmost();
  const wins = p.windows();
  for (let i = 0; i < wins.length; i++) {
    let title = '';
    try { title = wins[i].name() || ''; } catch (e) {}
    out.push({app: p.name(), index: i + 1, title: title, focused: front && i === 0});
  }
}
JSON.stringify(out);
"""

# Players we can control without media keys, in the order we try them.
PLAYERS = ["Spotify", "Music"]


def applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_windows_json(output: str) -> list[WindowInfo]:
    windows: list[WindowInfo] = []
    for item in json.loads(output or "[]"):
        wid = f"{item['app']}{SEP}{item['index']}"
        windows.append(WindowInfo(wid, item["title"], item["app"], bool(item["focused"])))
    return windows


def split_window_id(window_id: str) -> tuple[str, int]:
    app, _, index = window_id.rpartition(SEP)
    if not app or not index.isdigit():
        raise ToolError("Не нашла такое окно")
    return app, int(index)


def parse_now_playing(output: str) -> MediaInfo | None:
    """``<state>\\t<title>\\t<artist>\\t<app>`` from the AppleScript below."""
    line = output.strip("\n")
    if not line:
        return None
    state, title, artist, app = (line.split("\t") + [""] * 4)[:4]
    return MediaInfo(state == "playing", title or None, artist or None, app or None)


class MacPcBackend(CommonPcBackend):
    name = "macos"

    def __init__(self, runner: Runner | None = None, *, app_dirs: Iterable[Path] | None = None):
        super().__init__(runner)
        self._app_dirs = list(app_dirs) if app_dirs is not None else APP_DIRS

    def capabilities(self) -> Capabilities:
        supported = set(COMMON_CAPABILITIES) | {
            "list_apps", "open_app", "close_app",
            "list_windows", "focus_window", "minimize_window", "maximize_window", "close_window",
            "get_volume", "set_volume", "set_muted",
            "media_play_pause", "media_next", "media_previous", "now_playing",
            "open_path", "reveal_path", "open_url",
            "get_clipboard", "set_clipboard", "notify", "lock_screen", "sleep", "shutdown",
        }  # fmt: skip
        notes = {
            "list_windows": f"нужен универсальный доступ: {ACCESSIBILITY_HINT}",
            "media_play_pause": "управляет Spotify и Музыкой",
            "screenshot": "нужно разрешение «Запись экрана»",
        }
        return Capabilities(supported, notes)

    async def osascript(self, script: str, *, jxa: bool = False) -> str:
        argv = ["osascript", *(["-l", "JavaScript"] if jxa else []), "-e", script]
        result = await self.run(*argv)
        if not result.ok:
            err = result.stderr.strip()
            if "-1719" in err or "-25211" in err or "assistive" in err.lower():
                raise ToolError(f"Нет доступа: {ACCESSIBILITY_HINT}")
            raise CommandError(f"osascript: {err or result.returncode}")
        return result.stdout

    # Apps

    def _scan_apps(self) -> list[AppInfo]:
        apps: dict[str, AppInfo] = {}
        for base in self._app_dirs:
            if not base.is_dir():
                continue
            for path in base.glob("*.app"):
                apps.setdefault(path.stem.casefold(), AppInfo(str(path), path.stem))
        return sorted(apps.values(), key=lambda a: a.name.casefold())

    async def list_apps(self) -> list[AppInfo]:
        return await asyncio.to_thread(self._scan_apps)

    async def open_app(self, app_id: str) -> None:
        result = await self.run("open", "-a", app_id)
        if not result.ok:
            raise ToolError(f"Не нашла приложение «{Path(app_id).stem}»")

    async def close_app(self, app_id: str) -> None:
        name = Path(app_id).stem if app_id.endswith(".app") else app_id
        running = await self.osascript(f"application {applescript_string(name)} is running")
        if running.strip() != "true":
            raise ToolError(f"Приложение «{name}» не запущено")
        await self.osascript(f"tell application {applescript_string(name)} to quit")

    # Windows

    async def list_windows(self) -> list[WindowInfo]:
        return parse_windows_json(await self.osascript(LIST_WINDOWS_JXA, jxa=True))

    async def _window_script(self, window_id: str, body: str) -> None:
        app, index = split_window_id(window_id)
        await self.osascript(
            f'tell application "System Events" to tell process {applescript_string(app)}\n'
            f"  tell window {index}\n{body}\n  end tell\nend tell"
        )

    async def focus_window(self, window_id: str) -> None:
        app, _ = split_window_id(window_id)
        await self._window_script(window_id, 'perform action "AXRaise"')
        await self.osascript(
            f'tell application "System Events" to set frontmost of process '
            f"{applescript_string(app)} to true"
        )

    async def minimize_window(self, window_id: str) -> None:
        await self._window_script(window_id, 'set value of attribute "AXMinimized" to true')

    async def maximize_window(self, window_id: str) -> None:
        await self._window_script(window_id, 'set value of attribute "AXFullScreen" to true')

    async def close_window(self, window_id: str) -> None:
        await self._window_script(
            window_id,
            'click (first button whose value of attribute "AXSubrole" is "AXCloseButton")',
        )

    # Sound and media

    async def get_volume(self) -> int:
        out = await self.osascript("output volume of (get volume settings)")
        if out.strip() == "missing value":  # e.g. digital outputs without volume control
            raise NotSupportedError("get_volume", "у этого устройства вывода нет громкости")
        return int(out.strip())

    async def set_volume(self, percent: int) -> None:
        await self.osascript(f"set volume output volume {max(0, min(100, percent))}")

    async def set_muted(self, muted: bool) -> None:
        await self.osascript(f"set volume output muted {'true' if muted else 'false'}")

    async def _player_command(self, command: str) -> None:
        for player in PLAYERS:
            running = await self.osascript(f'application "{player}" is running')
            if running.strip() == "true":
                await self.osascript(f'tell application "{player}" to {command}')
                return
        raise ToolError("Не нашла запущенный плеер (Spotify или Музыка)")

    async def media_play_pause(self) -> None:
        await self._player_command("playpause")

    async def media_next(self) -> None:
        await self._player_command("next track")

    async def media_previous(self) -> None:
        await self._player_command("previous track")

    async def now_playing(self) -> MediaInfo | None:
        for player in PLAYERS:
            running = await self.osascript(f'application "{player}" is running')
            if running.strip() != "true":
                continue
            out = await self.osascript(
                f'tell application "{player}"\n'
                '  if player state is stopped then return ""\n'
                "  return (player state as text) & tab & (name of current track) & tab & "
                f'(artist of current track) & tab & "{player}"\n'
                "end tell"
            )
            info = parse_now_playing(out)
            if info is not None:
                return info
        return None

    # Files and browser

    async def search_files(self, query: str, limit: int = 20) -> list[FileHit]:
        result = await self.run("mdfind", "-onlyin", str(Path.home()), "-name", query)
        if result.ok:
            paths = [Path(line) for line in result.stdout.splitlines() if line]
            visible = [p for p in paths if not any(part.startswith(".") for part in p.parts)]
            return [FileHit(p, p.is_dir()) for p in visible[:limit]]
        return await asyncio.to_thread(search_files_sync, query, limit)

    async def open_path(self, path: Path) -> None:
        await ensure_exists(path)
        await self.run_ok("open", str(path))

    async def reveal_path(self, path: Path) -> None:
        await ensure_exists(path)
        await self.run_ok("open", "-R", str(path))

    async def open_url(self, url: str) -> None:
        await self.run_ok("open", url)

    # System

    async def get_clipboard(self) -> str:
        return await self.run_ok("pbpaste")

    async def set_clipboard(self, text: str) -> None:
        await self.run_ok("pbcopy", stdin=text)

    async def notify(self, title: str, body: str) -> None:
        await self.osascript(
            f"display notification {applescript_string(body)} "
            f"with title {applescript_string(title)}"
        )

    async def lock_screen(self) -> None:
        # Sleeping the display locks it when "require password" is on (the default).
        await self.run_ok("pmset", "displaysleepnow")

    async def sleep(self) -> None:
        await self.run_ok("pmset", "sleepnow")

    async def shutdown(self) -> None:
        await self.osascript('tell application "System Events" to shut down')
