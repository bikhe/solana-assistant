"""Safe operations against the real backend of the OS the tests run on.

CI runs this file on Windows, Linux and macOS. Runners have no sound card, display
server or media player, so operations that need one are skipped when the backend
honestly reports it can't do them; everything else must work for real.
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Awaitable, Iterator
from pathlib import Path

import pytest

from solana_core.pc import get_pc_backend
from solana_core.pc.base import BatteryInfo, NotSupportedError, PcBackend
from solana_core.pc.common import CommandError
from solana_core.tools import ToolError

EXPECTED = {"win32": "windows", "darwin": "macos", "linux": "linux"}


@pytest.fixture
def pc() -> PcBackend:
    return get_pc_backend()


@pytest.fixture
def home_tmp() -> Iterator[Path]:
    # Inside the home folder: trash on Linux and macOS works per volume.
    with tempfile.TemporaryDirectory(dir=Path.home(), prefix="solana-test-") as tmp:
        yield Path(tmp)


async def or_skip[T](awaitable: Awaitable[T]) -> T:
    """Skip when the runner lacks the hardware or session the operation needs."""
    try:
        return await awaitable
    except (NotSupportedError, ToolError, CommandError, OSError) as e:
        pytest.skip(f"not available on this runner: {e}")


def test_backend_matches_os(pc: PcBackend) -> None:
    assert pc.name == EXPECTED.get(sys.platform, "unsupported")
    assert {"search_files", "move_path", "trash_path", "battery"} <= pc.capabilities().supported


async def test_list_apps(pc: PcBackend) -> None:
    apps = await pc.list_apps()
    assert all(app.id and app.name for app in apps)
    if sys.platform == "darwin":  # every Mac has the system apps
        assert any(app.name in ("Safari", "Calculator", "Finder") for app in apps)


async def test_move_and_trash(pc: PcBackend, home_tmp: Path) -> None:
    src = home_tmp / "заметка.txt"
    src.write_text("Solana", encoding="utf-8")
    dst = home_tmp / "inbox"
    dst.mkdir()
    await pc.move_path(src, dst)
    moved = dst / "заметка.txt"
    assert moved.read_text(encoding="utf-8") == "Solana" and not src.exists()
    await pc.trash_path(moved)
    assert not moved.exists()


async def test_battery(pc: PcBackend) -> None:
    info = await pc.battery()
    assert info is None or (isinstance(info, BatteryInfo) and 0 <= info.percent <= 100)


async def test_clipboard_round_trip(pc: PcBackend) -> None:
    await or_skip(pc.set_clipboard("Привет, Солана"))
    assert (await or_skip(pc.get_clipboard())).strip() == "Привет, Солана"


async def test_volume_round_trip(pc: PcBackend) -> None:
    before = await or_skip(pc.get_volume())
    assert 0 <= before <= 100
    await pc.set_volume(before)
    assert abs(await pc.get_volume() - before) <= 1


async def test_list_windows(pc: PcBackend) -> None:
    windows = await or_skip(pc.list_windows())
    assert all(w.id for w in windows)


async def test_now_playing(pc: PcBackend) -> None:
    info = await or_skip(pc.now_playing())
    assert info is None or isinstance(info.playing, bool)
