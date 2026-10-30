from __future__ import annotations

from pathlib import Path

import pytest

from solana_core.pc.base import AppInfo, FakePcBackend, MediaInfo, WindowInfo
from solana_core.pc.tools import (
    PC_TOOLS,
    Screenshot,
    build_pc_tools,
    find_app,
    find_window,
    normalize_url,
    register_pc_tools,
)
from solana_core.tools import ToolContext, ToolError, ToolRegistry
from solana_core.tools.base import ToolResult

CTX = ToolContext()


class RichFakePc(FakePcBackend):
    """FakePcBackend plus the few operations the tools need that the contract fake lacks."""

    def __init__(self) -> None:
        super().__init__()
        self.apps = [
            AppInfo("/apps/Google Chrome.lnk", "Google Chrome"),
            AppInfo("org.telegram.desktop.desktop", "Telegram Desktop"),
            AppInfo("firefox.desktop", "Firefox"),
            AppInfo("code.desktop", "Visual Studio Code"),
        ]
        self.playing: MediaInfo | None = MediaInfo(True, "Song", "Artist", "spotify")
        self.png = b"\x89PNG fake"

    async def now_playing(self) -> MediaInfo | None:
        return self.playing

    async def screenshot(self) -> bytes:
        return self.png

    async def focus_window(self, window_id: str) -> None:
        self._record("focus_window", window_id)


async def call(pc: FakePcBackend, tool_name: str, /, **args: object) -> ToolResult:
    tool = {t.name: t for t in build_pc_tools(pc)}[tool_name]
    return await tool.run(dict(args), CTX)


def test_names_are_unique_and_include_fast_command_names() -> None:
    names = [cls.name for cls in PC_TOOLS]
    assert len(names) == len(set(names))
    # Shared with the fast-command parser of WP3 (brain/fast.py).
    for name in (
        "pc.volume_set",
        "pc.volume_change",
        "pc.mute",
        "pc.media",
        "pc.app_open",
        "pc.app_close",
        "pc.url_open",
        "pc.web_search",
    ):
        assert name in names


def test_risks() -> None:
    risks = {cls.name: cls.risk for cls in PC_TOOLS}
    assert risks["pc.shutdown"] == "dangerous"
    for name in ("pc.app_close", "pc.window_close", "pc.file_move", "pc.file_trash", "pc.sleep"):
        assert risks[name] == "confirm"
    assert risks["pc.volume_set"] == risks["pc.app_open"] == "safe"


def test_register_pc_tools() -> None:
    registry = ToolRegistry()
    register_pc_tools(registry, FakePcBackend())
    assert {s.name for s in registry.specs()} == {cls.name for cls in PC_TOOLS}
    for spec in registry.specs():
        assert spec.parameters["type"] == "object"


def test_register_pc_tools_picks_os_backend() -> None:
    registry = ToolRegistry()
    registered = register_pc_tools(registry)
    assert registered and registered[0].pc.name in ("windows", "linux", "macos")


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("хром", "Google Chrome"),
        ("Chrome", "Google Chrome"),
        ("телеграм", "Telegram Desktop"),
        ("телега", "Telegram Desktop"),
        ("файрфокс", "Firefox"),
        ("firefox", "Firefox"),
        ("вскод", "Visual Studio Code"),
    ],
)
def test_find_app(spoken: str, expected: str) -> None:
    app = find_app(RichFakePc().apps, spoken)
    assert app is not None and app.name == expected


def test_find_app_no_match() -> None:
    assert find_app(RichFakePc().apps, "фотошоп") is None
    assert find_app([], "хром") is None


def test_find_window() -> None:
    windows = [
        WindowInfo("0x1", "README.md - Visual Studio Code", "Code"),
        WindowInfo("0x2", "YouTube — Mozilla Firefox", "firefox"),
    ]
    assert find_window(windows, "0x2") == windows[1]
    assert find_window(windows, "файрфокс") == windows[1]
    assert find_window(windows, "readme") == windows[0]
    assert find_window(windows, "telegram") is None


async def test_app_open_resolves_spoken_name() -> None:
    pc = RichFakePc()
    result = await call(pc, "pc.app_open", name="хром")
    assert result.ok and "Google Chrome" in result.content
    assert ("open_app", ("/apps/Google Chrome.lnk",)) in pc.calls


async def test_app_open_unknown_name_is_passed_through() -> None:
    pc = RichFakePc()
    await call(pc, "pc.app_open", name="gimp")
    assert ("open_app", ("gimp",)) in pc.calls


async def test_volume_tools() -> None:
    pc = RichFakePc()
    pc.muted = True
    assert (await call(pc, "pc.volume_set", level=30)).data["level"] == 30
    assert pc.muted is False
    assert (await call(pc, "pc.volume_change", delta=-50)).data["level"] == 0
    assert (await call(pc, "pc.volume_change", delta=15)).content == "Громкость 15%"
    assert (await call(pc, "pc.volume_get")).data["level"] == 15
    await call(pc, "pc.mute", muted=True)
    assert pc.muted is True


async def test_bad_arguments_are_reported_not_raised() -> None:
    result = await call(RichFakePc(), "pc.volume_set", level="громко")
    assert not result.ok and "числом" in result.content


async def test_media_play_when_already_playing_does_nothing() -> None:
    pc = RichFakePc()
    result = await call(pc, "pc.media", action="play")
    assert result.content == "Уже играет"
    assert ("media_play_pause", ()) not in pc.calls
    await call(pc, "pc.media", action="pause")
    assert ("media_play_pause", ()) in pc.calls


async def test_media_without_now_playing_toggles() -> None:
    pc = FakePcBackend()  # now_playing is not supported here
    result = await call(pc, "pc.media", action="pause")
    assert result.ok
    assert ("media_play_pause", ()) in pc.calls


async def test_now_playing() -> None:
    pc = RichFakePc()
    result = await call(pc, "pc.now_playing")
    assert result.content == "Играет в spotify: Artist — Song"
    pc.playing = None
    assert (await call(pc, "pc.now_playing")).content == "Сейчас ничего не играет"


async def test_not_supported_is_an_honest_answer() -> None:
    result = await call(FakePcBackend(), "pc.shutdown")
    assert not result.ok
    assert result.content.startswith("Не поддерживается")


async def test_url_open_and_search() -> None:
    pc = RichFakePc()
    result = await call(pc, "pc.url_open", url="youtube.com")
    assert ("open_url", ("https://youtube.com",)) in pc.calls
    assert result.content == "Открываю youtube.com"
    await call(pc, "pc.web_search", query="погода в москве")
    url = pc.calls[-1][1][0]
    assert isinstance(url, str) and url.startswith("https://yandex.ru/search/?text=")
    result = await call(pc, "pc.url_open", url="file:///etc/passwd")
    assert not result.ok


def test_normalize_url() -> None:
    assert normalize_url(" http://a.ru/x ") == "http://a.ru/x"
    with pytest.raises(ToolError):
        normalize_url("javascript:alert(1)")


async def test_file_open_refuses_programs(tmp_path: Path) -> None:
    exe = tmp_path / "setup.exe"
    exe.write_bytes(b"MZ")
    result = await call(RichFakePc(), "pc.file_open", path=str(exe))
    assert not result.ok and "небезопасно" in result.content


async def test_window_focus_by_name() -> None:
    pc = RichFakePc()
    pc.windows = [WindowInfo("w1", "Inbox", "thunderbird")]
    result = await call(pc, "pc.window_focus", window="thunderbird")
    assert result.ok
    assert ("focus_window", ("w1",)) in pc.calls
    assert not (await call(pc, "pc.window_focus", window="steam")).ok


async def test_clipboard() -> None:
    pc = RichFakePc()
    assert (await call(pc, "pc.clipboard_get")).content == "Буфер обмена пуст"
    await call(pc, "pc.clipboard_set", text="привет")
    assert (await call(pc, "pc.clipboard_get")).content == "привет"


async def test_screenshot_is_saved(tmp_path: Path) -> None:
    pc = RichFakePc()
    result = await Screenshot(pc, tmp_path / "shots").run({}, CTX)
    saved = Path(result.data["path"])
    assert saved.parent == tmp_path / "shots"
    assert saved.read_bytes() == pc.png  # noqa: ASYNC240
