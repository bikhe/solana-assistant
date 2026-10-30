from __future__ import annotations

from pathlib import Path

import pytest

from solana_core.pc.base import NotSupportedError
from solana_core.pc.common import CommandResult
from solana_core.pc.linux.backend import (
    LinuxPcBackend,
    exec_argv,
    parse_desktop_entry,
    parse_mpris_names,
    parse_pactl_volume,
    parse_wmctrl,
    parse_wpctl_volume,
)
from solana_core.tools import ToolError
from tests.fake_runner import FakeRunner

X11 = {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}
WAYLAND = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}

FIREFOX = """
[Desktop Entry]
Type=Application
Name=Firefox Web Browser
Name[ru]=Веб-браузер Firefox
Exec=firefox %u
Icon=firefox

[Desktop Action new-window]
Name=New Window
Exec=firefox --new-window
"""


def backend(
    runner: FakeRunner,
    *,
    env: dict[str, str] | None = None,
    has: set[str] | None = None,
    app_dirs: list[Path] | None = None,
) -> LinuxPcBackend:
    return LinuxPcBackend(runner, env=env or X11, has=has or set(), app_dirs=app_dirs or [])


def test_parse_desktop_entry() -> None:
    entry = parse_desktop_entry(FIREFOX, "ru")
    assert entry is not None
    assert entry["_name"] == "Веб-браузер Firefox"
    assert parse_desktop_entry(FIREFOX, "de") is not None
    hidden = FIREFOX.replace("Icon=firefox", "NoDisplay=true")
    assert parse_desktop_entry(hidden) is None
    assert parse_desktop_entry("[Desktop Entry]\nType=Link\nURL=x\n") is None
    assert parse_desktop_entry("garbage") is None


def test_exec_argv() -> None:
    assert exec_argv("firefox %u") == ["firefox"]
    assert exec_argv('env FOO=1 "/opt/My App/app" --flag %F') == [
        "env",
        "FOO=1",
        "/opt/My App/app",
        "--flag",
    ]


def test_parse_wmctrl() -> None:
    out = (
        "0x03a00007  0 navigator.Firefox  host YouTube — Mozilla Firefox\n"
        "0x01e00003 -1 xfce4-panel.Xfce4-panel  host xfce4-panel\n"
        "0x04400004  1 code.Code  host main.py - solana - Visual Studio Code\n"
    )
    windows = parse_wmctrl(out, active=0x3A00007)
    assert [w.app for w in windows] == ["Firefox", "Code"]
    assert windows[0].focused and not windows[1].focused
    assert windows[1].title == "main.py - solana - Visual Studio Code"


def test_parse_volume_outputs() -> None:
    assert parse_wpctl_volume("Volume: 0.45\n") == (45, False)
    assert parse_wpctl_volume("Volume: 1.00 [MUTED]\n") == (100, True)
    pactl = "Volume: front-left: 26214 /  40% / -23.88 dB,   front-right: 26214 /  40% / -23.88 dB"
    assert parse_pactl_volume(pactl) == 40
    names = "(['org.freedesktop.DBus', 'org.mpris.MediaPlayer2.spotify', ':1.4'],)"
    assert parse_mpris_names(names) == ["org.mpris.MediaPlayer2.spotify"]


async def test_list_and_open_apps(tmp_path: Path) -> None:
    apps_dir = tmp_path / "applications"
    (apps_dir / "kde").mkdir(parents=True)
    (apps_dir / "firefox.desktop").write_text(FIREFOX)
    (apps_dir / "kde" / "konsole.desktop").write_text(
        "[Desktop Entry]\nName=Konsole\nExec=konsole\n"
    )
    runner = FakeRunner()
    pc = backend(runner, app_dirs=[apps_dir])
    apps = await pc.list_apps()
    assert {a.id for a in apps} == {"firefox.desktop", "kde-konsole.desktop"}
    with pytest.raises(ToolError):
        await pc.open_app("no-such-app")


async def test_volume_prefers_wpctl() -> None:
    runner = FakeRunner({"wpctl get-volume": "Volume: 0.30\n"})
    pc = backend(runner, has={"wpctl", "pactl"})
    assert await pc.get_volume() == 30
    await pc.set_volume(55)
    await pc.set_muted(True)
    assert ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.55"] in runner.argvs
    assert ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"] in runner.argvs


async def test_volume_falls_back_to_pactl() -> None:
    runner = FakeRunner({"pactl get-sink-volume": "Volume: front-left: 1 /  70% / 0 dB"})
    pc = backend(runner, has={"pactl"})
    assert await pc.get_volume() == 70
    await pc.set_volume(120)
    assert ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"] in runner.argvs


async def test_volume_without_sound_server() -> None:
    with pytest.raises(NotSupportedError):
        await backend(FakeRunner()).get_volume()


async def test_windows_on_x11() -> None:
    runner = FakeRunner(
        {
            "xprop": "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x4400004\n",
            "wmctrl -lx": "0x04400004  0 code.Code  host editor\n",
        }
    )
    pc = backend(runner, has={"wmctrl", "xprop"})
    windows = await pc.list_windows()
    assert windows[0].focused
    await pc.focus_window("0x04400004")
    await pc.minimize_window("0x04400004")
    assert ["wmctrl", "-ia", "0x04400004"] in runner.argvs
    assert ["wmctrl", "-ir", "0x04400004", "-b", "add,hidden"] in runner.argvs


async def test_windows_on_wayland_are_not_supported() -> None:
    pc = backend(FakeRunner(), env=WAYLAND, has={"wmctrl"})
    with pytest.raises(NotSupportedError) as info:
        await pc.list_windows()
    assert "Wayland" in info.value.reason
    assert "list_windows" not in pc.capabilities().supported
    assert "Wayland" in pc.capabilities().notes["list_windows"]


async def test_media_with_playerctl() -> None:
    runner = FakeRunner({"playerctl metadata": "Playing\tSong\tArtist\tspotify\n"})
    pc = backend(runner, has={"playerctl"})
    info = await pc.now_playing()
    assert info is not None and info.playing and info.title == "Song" and info.app == "spotify"
    await pc.media_next()
    assert ["playerctl", "next"] in runner.argvs


async def test_media_without_players() -> None:
    runner = FakeRunner(
        {
            "playerctl metadata": CommandResult(1, "", "No players found"),
            "playerctl play-pause": CommandResult(1, "", "No players found"),
        }
    )
    pc = backend(runner, has={"playerctl"})
    assert await pc.now_playing() is None
    with pytest.raises(ToolError):
        await pc.media_play_pause()


async def test_media_falls_back_to_dbus() -> None:
    runner = FakeRunner(
        {"gdbus call --session --dest org.freedesktop.DBus": "(['org.mpris.MediaPlayer2.vlc'],)"}
    )
    pc = backend(runner, has={"gdbus"})
    await pc.media_play_pause()
    assert runner.argvs[-1][-1] == "org.mpris.MediaPlayer2.Player.PlayPause"
    assert "org.mpris.MediaPlayer2.vlc" in runner.argvs[-1]


async def test_clipboard_and_system() -> None:
    runner = FakeRunner({"xclip -selection clipboard -o": "привет"})
    pc = backend(runner, has={"xclip", "notify-send", "systemctl"})
    assert await pc.get_clipboard() == "привет"
    await pc.notify("Solana", "Таймер")
    await pc.sleep()
    assert ["notify-send", "--app-name=Solana", "Solana", "Таймер"] in runner.argvs
    assert ["systemctl", "suspend"] in runner.argvs


async def test_capabilities_with_nothing_installed() -> None:
    caps = backend(FakeRunner()).capabilities()
    assert {"list_apps", "search_files", "trash_path"} <= caps.supported
    assert "get_volume" not in caps.supported
    assert "wpctl" in caps.notes["get_volume"]
