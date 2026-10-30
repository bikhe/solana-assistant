"""Linux backend: XDG desktop files, PipeWire/PulseAudio, MPRIS, wmctrl on X11.

Every helper program is optional. What is missing shows up as "не поддерживается" with a
hint about what to install. On Wayland other apps' windows can't be listed or moved, so
window tools honestly report that.
"""

from __future__ import annotations

import asyncio
import configparser
import contextlib
import os
import re
import shlex
import tempfile
from collections.abc import Iterable
from pathlib import Path

from solana_core.pc.base import AppInfo, Capabilities, MediaInfo, NotSupportedError, WindowInfo
from solana_core.pc.common import (
    COMMON_CAPABILITIES,
    CommandError,
    CommonPcBackend,
    Runner,
    ensure_exists,
    spawn_detached,
    which,
)
from solana_core.tools.base import ToolError

WAYLAND_WINDOWS = "в Wayland нельзя управлять окнами других приложений"


def xdg_application_dirs() -> list[Path]:
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs = [data_home, *data_dirs.split(":"), "/var/lib/flatpak/exports/share"]
    dirs.append(str(Path.home() / ".local/share/flatpak/exports/share"))
    seen: list[Path] = []
    for d in dirs:
        path = Path(d) / "applications"
        if d and path not in seen:
            seen.append(path)
    return seen


def _ui_language() -> str:
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return value.split(":")[0].split("_")[0].split(".")[0]
    return "en"


def parse_desktop_entry(text: str, language: str = "ru") -> dict[str, str] | None:
    """Return the ``[Desktop Entry]`` group of a visible application, or None."""
    parser = configparser.RawConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    try:
        parser.read_string(text)
    except configparser.Error:
        return None
    if not parser.has_section("Desktop Entry"):
        return None
    entry = dict(parser["Desktop Entry"])
    if entry.get("Type", "Application") != "Application":
        return None
    if entry.get("NoDisplay") == "true" or entry.get("Hidden") == "true" or "Exec" not in entry:
        return None
    entry["_name"] = entry.get(f"Name[{language}]") or entry.get("Name") or ""
    return entry


def exec_argv(exec_line: str) -> list[str]:
    """Exec= line to argv without field codes like %f or %U."""
    argv = shlex.split(exec_line)
    return [a for a in argv if not re.fullmatch(r"%[a-zA-Z]", a)]


def parse_wmctrl(output: str, active: int | None = None) -> list[WindowInfo]:
    """Parse ``wmctrl -lx``: id, desktop, wm_class, host, title."""
    windows: list[WindowInfo] = []
    for line in output.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4 or parts[1] == "-1":  # -1 is docks and desktop widgets
            continue
        wid, _, wm_class, _host = parts[:4]
        title = parts[4] if len(parts) > 4 else ""
        app = wm_class.split(".")[-1]
        windows.append(WindowInfo(wid, title, app, focused=int(wid, 16) == active))
    return windows


def parse_wpctl_volume(output: str) -> tuple[int, bool]:
    """``Volume: 0.45 [MUTED]`` -> (45, True)."""
    match = re.search(r"Volume:\s*([\d.]+)", output)
    if not match:
        raise CommandError(f"wpctl: unexpected output {output!r}")
    return round(float(match.group(1)) * 100), "[MUTED]" in output


def parse_pactl_volume(output: str) -> int:
    """First channel percent of ``pactl get-sink-volume``."""
    match = re.search(r"(\d+)%", output)
    if not match:
        raise CommandError(f"pactl: unexpected output {output!r}")
    return int(match.group(1))


def parse_mpris_names(output: str) -> list[str]:
    return re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", output)


class LinuxPcBackend(CommonPcBackend):
    name = "linux"

    def __init__(
        self,
        runner: Runner | None = None,
        *,
        app_dirs: Iterable[Path] | None = None,
        env: dict[str, str] | None = None,
        has: set[str] | None = None,
    ) -> None:
        super().__init__(runner)
        self._app_dirs = list(app_dirs) if app_dirs is not None else xdg_application_dirs()
        self._env = env if env is not None else dict(os.environ)
        self._has = has  # tests pass the set of installed helper programs

    def _which(self, name: str) -> bool:
        return name in self._has if self._has is not None else which(name)

    @property
    def wayland(self) -> bool:
        return self._env.get("XDG_SESSION_TYPE") == "wayland" or bool(
            self._env.get("WAYLAND_DISPLAY")
        )

    def capabilities(self) -> Capabilities:
        caps = Capabilities(set(COMMON_CAPABILITIES) | {"list_apps", "open_app", "close_app"})
        notes = caps.notes

        def need(ops: Iterable[str], ok: bool, note: str) -> None:
            if ok:
                caps.supported.update(ops)
            else:
                for op in ops:
                    notes[op] = note

        x11_windows = not self.wayland and self._which("wmctrl")
        need(
            ["list_windows", "focus_window", "maximize_window", "close_window", "minimize_window"],
            x11_windows,
            WAYLAND_WINDOWS if self.wayland else "установите wmctrl",
        )
        need(
            ["get_volume", "set_volume", "set_muted"],
            self._which("wpctl") or self._which("pactl"),
            "нужен PipeWire (wpctl) или PulseAudio (pactl)",
        )
        need(
            ["media_play_pause", "media_next", "media_previous"],
            self._which("playerctl") or self._which("gdbus"),
            "установите playerctl",
        )
        need(["now_playing"], self._which("playerctl"), "установите playerctl")
        opener = self._which("xdg-open")
        need(["open_path", "reveal_path", "open_url"], opener, "установите xdg-utils")
        clip = (
            self._which("wl-copy") if self.wayland else self._which("xclip") or self._which("xsel")
        )
        need(
            ["get_clipboard", "set_clipboard"],
            clip,
            "установите wl-clipboard" if self.wayland else "установите xclip",
        )
        need(["notify"], self._which("notify-send") or self._which("gdbus"), "установите libnotify")
        need(["lock_screen", "sleep", "shutdown"], self._which("systemctl"), "нужен systemd")
        return caps

    # Apps

    def _entries(self) -> dict[str, tuple[Path, dict[str, str]]]:
        language = _ui_language()
        entries: dict[str, tuple[Path, dict[str, str]]] = {}
        for base in self._app_dirs:
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.desktop")):
                app_id = "-".join(path.relative_to(base).parts)
                if app_id in entries:  # earlier dirs win, as in the XDG spec
                    continue
                try:
                    entry = parse_desktop_entry(path.read_text("utf-8", "replace"), language)
                except OSError:
                    continue
                if entry is not None:
                    entries[app_id] = (path, entry)
        return entries

    async def list_apps(self) -> list[AppInfo]:
        entries = await asyncio.to_thread(self._entries)
        apps = [AppInfo(app_id, entry["_name"]) for app_id, (_, entry) in entries.items()]
        return sorted(apps, key=lambda a: a.name.casefold())

    async def _entry(self, app_id: str) -> dict[str, str] | None:
        entries = await asyncio.to_thread(self._entries)
        found = entries.get(app_id) or entries.get(f"{app_id}.desktop")
        return found[1] if found else None

    async def open_app(self, app_id: str) -> None:
        entry = await self._entry(app_id)
        if entry is not None:
            argv = exec_argv(entry["Exec"])
        elif self._which(app_id):
            argv = [app_id]
        else:
            raise ToolError(f"Не нашла приложение «{app_id}»")
        await spawn_detached(argv)

    async def close_app(self, app_id: str) -> None:
        entry = await self._entry(app_id)
        argv = exec_argv(entry["Exec"]) if entry else [app_id]
        while argv and (argv[0] == "env" or "=" in argv[0]):
            argv = argv[1:]
        if not argv:
            raise ToolError(f"Не нашла приложение «{app_id}»")
        # Flatpak apps run as "flatpak run <id>"; match the id in the command line instead.
        needle = argv[-1] if Path(argv[0]).name == "flatpak" else Path(argv[0]).name
        stopped = await asyncio.to_thread(_terminate_matching, needle)
        if not stopped:
            raise ToolError(f"Приложение «{app_id}» не запущено")

    # Windows (X11 only)

    def _require_x11(self, operation: str) -> None:
        if self.wayland:
            raise NotSupportedError(operation, WAYLAND_WINDOWS)
        if not self._which("wmctrl"):
            raise NotSupportedError(operation, "установите wmctrl")

    async def list_windows(self) -> list[WindowInfo]:
        self._require_x11("list_windows")
        active: int | None = None
        if self._which("xprop"):
            with contextlib.suppress(CommandError):
                out = await self.run_ok("xprop", "-root", "_NET_ACTIVE_WINDOW")
                match = re.search(r"0x[0-9a-fA-F]+", out)
                active = int(match.group(0), 16) if match else None
        return parse_wmctrl(await self.run_ok("wmctrl", "-lx"), active)

    async def focus_window(self, window_id: str) -> None:
        self._require_x11("focus_window")
        await self.run_ok("wmctrl", "-ia", window_id)

    async def minimize_window(self, window_id: str) -> None:
        self._require_x11("minimize_window")
        if self._which("xdotool"):
            await self.run_ok("xdotool", "windowminimize", str(int(window_id, 16)))
        else:
            await self.run_ok("wmctrl", "-ir", window_id, "-b", "add,hidden")

    async def maximize_window(self, window_id: str) -> None:
        self._require_x11("maximize_window")
        await self.run_ok("wmctrl", "-ir", window_id, "-b", "add,maximized_vert,maximized_horz")

    async def close_window(self, window_id: str) -> None:
        self._require_x11("close_window")
        await self.run_ok("wmctrl", "-ic", window_id)

    # Sound and media

    async def get_volume(self) -> int:
        if self._which("wpctl"):
            out = await self.run_ok("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
            return parse_wpctl_volume(out)[0]
        if self._which("pactl"):
            return parse_pactl_volume(
                await self.run_ok("pactl", "get-sink-volume", "@DEFAULT_SINK@")
            )
        raise NotSupportedError("get_volume", "нужен PipeWire (wpctl) или PulseAudio (pactl)")

    async def set_volume(self, percent: int) -> None:
        percent = max(0, min(100, percent))
        if self._which("wpctl"):
            await self.run_ok("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent / 100:.2f}")
        elif self._which("pactl"):
            await self.run_ok("pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%")
        else:
            raise NotSupportedError("set_volume", "нужен PipeWire (wpctl) или PulseAudio (pactl)")

    async def set_muted(self, muted: bool) -> None:
        flag = "1" if muted else "0"
        if self._which("wpctl"):
            await self.run_ok("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", flag)
        elif self._which("pactl"):
            await self.run_ok("pactl", "set-sink-mute", "@DEFAULT_SINK@", flag)
        else:
            raise NotSupportedError("set_muted", "нужен PipeWire (wpctl) или PulseAudio (pactl)")

    async def _media(self, playerctl_cmd: str, mpris_method: str) -> None:
        if self._which("playerctl"):
            result = await self.run("playerctl", playerctl_cmd)
            if not result.ok:
                raise ToolError("Сейчас ничего не играет")
            return
        if not self._which("gdbus"):
            raise NotSupportedError(playerctl_cmd, "установите playerctl")
        names = parse_mpris_names(
            await self.run_ok(
                "gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                "--object-path", "/org/freedesktop/DBus",
                "--method", "org.freedesktop.DBus.ListNames",
            )
        )  # fmt: skip
        if not names:
            raise ToolError("Сейчас ничего не играет")
        await self.run_ok(
            "gdbus", "call", "--session", "--dest", names[0],
            "--object-path", "/org/mpris/MediaPlayer2",
            "--method", f"org.mpris.MediaPlayer2.Player.{mpris_method}",
        )  # fmt: skip

    async def media_play_pause(self) -> None:
        await self._media("play-pause", "PlayPause")

    async def media_next(self) -> None:
        await self._media("next", "Next")

    async def media_previous(self) -> None:
        await self._media("previous", "Previous")

    async def now_playing(self) -> MediaInfo | None:
        if not self._which("playerctl"):
            raise NotSupportedError("now_playing", "установите playerctl")
        fmt = "{{status}}\t{{title}}\t{{artist}}\t{{playerName}}"
        result = await self.run("playerctl", "metadata", "--format", fmt)
        if not result.ok or not result.stdout.strip():
            return None
        status, title, artist, player = (result.stdout.rstrip("\n").split("\t") + [""] * 4)[:4]
        return MediaInfo(status == "Playing", title or None, artist or None, player or None)

    # Files and browser

    async def open_path(self, path: Path) -> None:
        await ensure_exists(path)
        await spawn_detached(["xdg-open", str(path)])

    async def reveal_path(self, path: Path) -> None:
        await ensure_exists(path)
        if self._which("gdbus"):
            result = await self.run(
                "gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1",
                "--object-path", "/org/freedesktop/FileManager1",
                "--method", "org.freedesktop.FileManager1.ShowItems", f"['{path.as_uri()}']", "",
            )  # fmt: skip
            if result.ok:
                return
        await spawn_detached(["xdg-open", str(path.parent)])

    async def open_url(self, url: str) -> None:
        await spawn_detached(["xdg-open", url])

    # System

    async def get_clipboard(self) -> str:
        if self.wayland and self._which("wl-paste"):
            result = await self.run("wl-paste", "--no-newline")
            return result.stdout if result.ok else ""  # empty clipboard exits with 1
        if self._which("xclip"):
            result = await self.run("xclip", "-selection", "clipboard", "-o")
            return result.stdout if result.ok else ""
        if self._which("xsel"):
            return await self.run_ok("xsel", "--clipboard", "--output")
        raise NotSupportedError("get_clipboard", "установите wl-clipboard или xclip")

    async def set_clipboard(self, text: str) -> None:
        if self.wayland and self._which("wl-copy"):
            await spawn_input(["wl-copy"], text)
        elif self._which("xclip"):
            await spawn_input(["xclip", "-selection", "clipboard", "-i"], text)
        elif self._which("xsel"):
            await self.run_ok("xsel", "--clipboard", "--input", stdin=text)
        else:
            raise NotSupportedError("set_clipboard", "установите wl-clipboard или xclip")

    async def screenshot(self) -> bytes:
        if self.wayland and self._which("grim"):
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "shot.png"
                await self.run_ok("grim", str(target))
                return target.read_bytes()
        if self.wayland:
            raise NotSupportedError("screenshot", "в Wayland нужен grim")
        return await super().screenshot()

    async def notify(self, title: str, body: str) -> None:
        if self._which("notify-send"):
            await self.run_ok("notify-send", "--app-name=Solana", title, body)
            return
        if not self._which("gdbus"):
            raise NotSupportedError("notify", "установите libnotify")
        await self.run_ok(
            "gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
            "--object-path", "/org/freedesktop/Notifications",
            "--method", "org.freedesktop.Notifications.Notify",
            "Solana", "0", "", title, body, "[]", "{}", "5000",
        )  # fmt: skip

    async def lock_screen(self) -> None:
        result = await self.run("loginctl", "lock-session")
        if not result.ok:
            await self.run_ok("xdg-screensaver", "lock")

    async def sleep(self) -> None:
        await self.run_ok("systemctl", "suspend")

    async def shutdown(self) -> None:
        await self.run_ok("systemctl", "poweroff")


async def spawn_input(argv: list[str], text: str) -> None:
    """Feed stdin to a clipboard owner that keeps running (xclip, wl-copy) without waiting."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as e:
        raise CommandError(f"{argv[0]}: not found") from e
    assert proc.stdin is not None
    proc.stdin.write(text.encode())
    await proc.stdin.drain()
    proc.stdin.close()
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(proc.wait(), 0.5)


def _terminate_matching(needle: str) -> int:
    import psutil

    me = os.getpid()
    count = 0
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        info = proc.info
        if info["pid"] == me:
            continue
        exe = Path(info["exe"] or "").name
        cmdline = info["cmdline"] or []
        if needle in (info["name"], exe, *(Path(c).name for c in cmdline[:1])) or (
            "." in needle and needle in cmdline
        ):
            with contextlib.suppress(psutil.Error):
                proc.terminate()
                count += 1
    return count
