from __future__ import annotations

import json
from pathlib import Path

import pytest

from solana_core.pc.common import CommandResult
from solana_core.pc.macos.backend import (
    SEP,
    MacPcBackend,
    applescript_string,
    parse_now_playing,
    parse_windows_json,
    split_window_id,
)
from solana_core.tools import ToolError
from tests.fake_runner import FakeRunner


def test_applescript_string_escapes() -> None:
    assert applescript_string('He said "hi" \\o/') == '"He said \\"hi\\" \\\\o/"'


def test_parse_windows_json() -> None:
    out = json.dumps(
        [
            {"app": "Safari", "index": 1, "title": "Apple", "focused": True},
            {"app": "Finder", "index": 2, "title": "", "focused": False},
        ]
    )
    windows = parse_windows_json(out)
    assert windows[0].id == f"Safari{SEP}1" and windows[0].focused
    assert split_window_id(windows[1].id) == ("Finder", 2)
    with pytest.raises(ToolError):
        split_window_id("garbage")


def test_parse_now_playing() -> None:
    info = parse_now_playing("paused\tSong\tArtist\tMusic\n")
    assert info is not None and not info.playing and info.app == "Music"
    assert parse_now_playing("\n") is None


async def test_list_apps(tmp_path: Path) -> None:
    (tmp_path / "Safari.app").mkdir()
    (tmp_path / "Telegram.app").mkdir()
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    apps = await MacPcBackend(FakeRunner(), app_dirs=[tmp_path]).list_apps()
    assert [a.name for a in apps] == ["Safari", "Telegram"]
    assert apps[0].id.endswith("Safari.app")


async def test_volume() -> None:
    runner = FakeRunner({"osascript -e output volume": "35\n"})
    pc = MacPcBackend(runner)
    assert await pc.get_volume() == 35
    await pc.set_volume(150)
    assert runner.argvs[-1] == ["osascript", "-e", "set volume output volume 100"]


async def test_close_app_only_when_running() -> None:
    runner = FakeRunner({'osascript -e application "Telegram" is running': "false\n"})
    pc = MacPcBackend(runner)
    with pytest.raises(ToolError):
        await pc.close_app("/Applications/Telegram.app")
    runner.replies['osascript -e application "Telegram" is running'] = "true\n"
    await pc.close_app("/Applications/Telegram.app")
    assert runner.argvs[-1] == ["osascript", "-e", 'tell application "Telegram" to quit']


async def test_media_controls_the_running_player() -> None:
    runner = FakeRunner(
        {
            'osascript -e application "Spotify" is running': "false\n",
            'osascript -e application "Music" is running': "true\n",
        }
    )
    await MacPcBackend(runner).media_next()
    assert runner.argvs[-1] == ["osascript", "-e", 'tell application "Music" to next track']


async def test_missing_accessibility_permission() -> None:
    error = CommandResult(
        1, "", "execution error: osascript is not allowed assistive access. (-1719)"
    )
    runner = FakeRunner({"osascript -l JavaScript": error})
    with pytest.raises(ToolError) as info:
        await MacPcBackend(runner).list_windows()
    assert "Универсальный доступ" in str(info.value)


async def test_clipboard_uses_pbcopy() -> None:
    runner = FakeRunner({"pbpaste": "привет"})
    pc = MacPcBackend(runner)
    await pc.set_clipboard("мир")
    assert runner.calls[-1] == (["pbcopy"], "мир")
    assert await pc.get_clipboard() == "привет"
