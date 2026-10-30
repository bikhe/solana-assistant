from __future__ import annotations

import sys
from pathlib import Path

import pytest

from solana_core.pc.common import (
    CommandError,
    move_path_sync,
    run_command,
    search_files_sync,
)


def test_search_files(tmp_path: Path) -> None:
    (tmp_path / "Docs" / "deep").mkdir(parents=True)
    (tmp_path / "Docs" / "Отчёт за май.docx").write_text("x", encoding="utf-8")
    (tmp_path / "Docs" / "deep" / "отчёт-июнь.pdf").write_text("x", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "отчёт.txt").write_text("x", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "отчёт.js").write_text("x", encoding="utf-8")

    hits = search_files_sync("ОТЧЁТ", roots=[tmp_path])
    assert sorted(h.path.name for h in hits) == ["Отчёт за май.docx", "отчёт-июнь.pdf"]
    assert search_files_sync("отчёт май", roots=[tmp_path])[0].path.name == "Отчёт за май.docx"
    assert search_files_sync("Docs", roots=[tmp_path])[0].is_dir
    assert len(search_files_sync("отчёт", limit=1, roots=[tmp_path])) == 1
    assert search_files_sync("  ", roots=[tmp_path]) == []


def test_move_never_overwrites(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("a", encoding="utf-8")
    folder = tmp_path / "folder"
    folder.mkdir()
    move_path_sync(src, folder)
    assert (folder / "a.txt").read_text() == "a"
    other = tmp_path / "b.txt"
    other.write_text("b", encoding="utf-8")
    with pytest.raises(FileExistsError):
        move_path_sync(other, folder / "a.txt")
    with pytest.raises(FileNotFoundError):
        move_path_sync(tmp_path / "missing", folder)


async def test_run_command() -> None:
    result = await run_command(
        [sys.executable, "-X", "utf8", "-c", "print(input().upper())"], "привет"
    )
    assert result.ok and result.stdout.strip() == "ПРИВЕТ"
    with pytest.raises(CommandError):
        await run_command(["solana-no-such-program"])
