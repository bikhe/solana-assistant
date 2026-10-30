from __future__ import annotations

import base64
import re
from pathlib import Path

from solana_core.pc.windows.shell import ps_command, ps_literal, scan_shortcuts, toast_script


def _decode_literal(expr: str) -> str:
    match = re.search(r"FromBase64String\('([^']+)'\)", expr)
    assert match
    return base64.b64decode(match.group(1)).decode()


def test_ps_literal_round_trips_hostile_text() -> None:
    text = "Привет'; Remove-Item C:\\ -Recurse; $(calc)"
    expr = ps_literal(text)
    assert "Remove-Item" not in expr
    assert _decode_literal(expr) == text


def test_ps_command_is_encoded() -> None:
    argv = ps_command("Get-Date")
    assert argv[0] == "powershell" and argv[-2] == "-EncodedCommand"
    script = base64.b64decode(argv[-1]).decode("utf-16-le")
    assert script.endswith("Get-Date") and "UTF8" in script


def test_toast_script_keeps_user_text_encoded() -> None:
    script = toast_script("Solana", 'Таймер "чай"')
    assert "чай" not in script
    assert "ToastText02" in script


def test_scan_shortcuts(tmp_path: Path) -> None:
    (tmp_path / "Telegram").mkdir()
    (tmp_path / "Telegram" / "Telegram.lnk").write_bytes(b"")
    (tmp_path / "Telegram" / "Uninstall Telegram.lnk").write_bytes(b"")
    (tmp_path / "Google Chrome.lnk").write_bytes(b"")
    (tmp_path / "readme.txt").write_bytes(b"")
    names = [name for _, name in scan_shortcuts([tmp_path, tmp_path / "missing"])]
    assert names == ["Google Chrome", "Telegram"]
