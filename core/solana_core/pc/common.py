"""Helpers shared by the OS backends: subprocesses, files, battery and screenshots."""

from __future__ import annotations

import asyncio
import errno
import os
import shutil
import time
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from solana_core.pc.base import BatteryInfo, FileHit, NotSupportedError, PcBackend

COMMAND_TIMEOUT_S = 10.0


class CommandError(Exception):
    """A helper program failed or is missing."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[Sequence[str], str | None], Awaitable[CommandResult]]
"""Runs ``argv`` with optional stdin text. Backends take one so tests can fake the OS."""


async def run_command(
    argv: Sequence[str], stdin: str | None = None, *, timeout_s: float = COMMAND_TIMEOUT_S
) -> CommandResult:
    env = {**os.environ, "LC_ALL": "C.UTF-8"} if os.name != "nt" else None
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError as e:
        raise CommandError(f"{argv[0]}: not found") from e
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(stdin.encode() if stdin is not None else None), timeout_s
        )
    except TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise CommandError(f"{argv[0]}: timed out") from e
    return CommandResult(
        proc.returncode or 0,
        out.decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
    )


async def spawn_detached(argv: Sequence[str]) -> None:
    """Start a program that outlives the call (apps, file managers) without waiting for it."""
    try:
        await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=os.name != "nt",
        )
    except FileNotFoundError as e:
        raise CommandError(f"{argv[0]}: not found") from e


async def ensure_exists(path: Path) -> None:
    if not await asyncio.to_thread(path.exists):
        raise FileNotFoundError(path)


def which(name: str) -> bool:
    return shutil.which(name) is not None


# Files

SKIP_DIRS = {
    "node_modules",
    "__pycache__",
    "site-packages",
    "AppData",
    "Library",
    "venv",
    ".venv",
    "$RECYCLE.BIN",
}


def default_search_roots() -> list[Path]:
    home = Path.home()
    names = ["Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos", "Movies"]
    roots = [home / n for n in names if (home / n).is_dir()]
    return [*roots, home]


def _walk(root: Path, max_depth: int) -> Iterator[os.DirEntry[str]]:
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        path, depth = stack.pop()
        try:
            with os.scandir(path) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            yield entry
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir and depth < max_depth and entry.name not in SKIP_DIRS:
                stack.append((Path(entry.path), depth + 1))


def search_files_sync(
    query: str,
    limit: int = 20,
    roots: Sequence[Path] | None = None,
    *,
    max_depth: int = 6,
    budget_s: float = 3.0,
) -> list[FileHit]:
    """Case-insensitive name search under the user's folders, bounded in depth and time."""
    words = query.casefold().split()
    if not words:
        return []
    deadline = time.monotonic() + budget_s
    seen: set[str] = set()
    hits: list[FileHit] = []
    for root in roots if roots is not None else default_search_roots():
        for entry in _walk(root, max_depth):
            if time.monotonic() > deadline:
                return hits
            name = entry.name.casefold()
            if entry.path in seen or not all(w in name for w in words):
                continue
            seen.add(entry.path)
            try:
                is_dir = entry.is_dir()
            except OSError:
                is_dir = False
            hits.append(FileHit(Path(entry.path), is_dir))
            if len(hits) >= limit:
                return hits
    return hits


def move_path_sync(src: Path, dst: Path) -> None:
    """Move without ever overwriting: an existing target is an error, even in a race."""
    if not src.exists():
        raise FileNotFoundError(src)
    if dst.is_dir():
        dst = dst / src.name
    if dst.exists():
        raise FileExistsError(dst)
    if os.name == "nt" or src.is_dir():
        try:
            os.rename(src, dst)  # Windows refuses to replace; POSIX only replaces empty dirs
            return
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=False)
            shutil.rmtree(src)
        else:
            _copy_exclusive(src, dst)
            os.unlink(src)
        return
    try:
        os.link(src, dst)  # fails if dst appeared meanwhile
    except OSError as e:
        if e.errno == errno.EEXIST:
            raise FileExistsError(dst) from e
        _copy_exclusive(src, dst)  # other volume, or links unsupported
    os.unlink(src)


def _copy_exclusive(src: Path, dst: Path) -> None:
    with open(src, "rb") as fin, open(dst, "xb") as fout:  # "x" never replaces a file
        try:
            shutil.copyfileobj(fin, fout)
        except BaseException:
            fout.close()
            dst.unlink(missing_ok=True)  # no half-copied duplicate
            raise
    shutil.copystat(src, dst)


def trash_path_sync(path: Path) -> None:
    from send2trash import send2trash

    if not path.exists():
        raise FileNotFoundError(path)
    send2trash(path)


def battery_sync() -> BatteryInfo | None:
    import psutil

    info = psutil.sensors_battery()
    if info is None:
        return None
    return BatteryInfo(percent=float(info.percent), charging=bool(info.power_plugged))


def screenshot_sync() -> bytes:
    import mss
    import mss.tools

    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[0])  # all monitors together
        png = mss.tools.to_png(shot.rgb, shot.size)
    assert png is not None
    return png


class CommonPcBackend(PcBackend):
    """Operations that work the same way everywhere. OS backends inherit from it."""

    def __init__(self, runner: Runner | None = None) -> None:
        self._runner = runner

    async def run(self, *argv: str, stdin: str | None = None) -> CommandResult:
        if self._runner is not None:
            return await self._runner(argv, stdin)
        return await run_command(argv, stdin)

    async def run_ok(self, *argv: str, stdin: str | None = None) -> str:
        result = await self.run(*argv, stdin=stdin)
        if not result.ok:
            raise CommandError(f"{argv[0]}: {result.stderr.strip() or result.returncode}")
        return result.stdout

    async def search_files(self, query: str, limit: int = 20) -> list[FileHit]:
        return await asyncio.to_thread(search_files_sync, query, limit)

    async def move_path(self, src: Path, dst: Path) -> None:
        await asyncio.to_thread(move_path_sync, src, dst)

    async def trash_path(self, path: Path) -> None:
        await asyncio.to_thread(trash_path_sync, path)

    async def battery(self) -> BatteryInfo | None:
        return await asyncio.to_thread(battery_sync)

    async def screenshot(self) -> bytes:
        try:
            return await asyncio.to_thread(screenshot_sync)
        except Exception as e:  # mss raises its own ScreenShotError and OS errors
            raise NotSupportedError("screenshot", str(e)) from e


COMMON_CAPABILITIES = {"search_files", "move_path", "trash_path", "battery", "screenshot"}
