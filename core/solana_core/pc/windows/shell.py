"""Pure helpers for the Windows backend that tests can run on any OS."""

from __future__ import annotations

import base64
import os
from pathlib import Path

PS_ARGS = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]


def ps_literal(text: str) -> str:
    """A PowerShell expression that evaluates to ``text`` without any quoting pitfalls."""
    encoded = base64.b64encode(text.encode()).decode()
    return f"[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}'))"


def ps_command(script: str) -> list[str]:
    """argv that runs ``script`` through ``-EncodedCommand`` (UTF-16LE base64)."""
    # Make PowerShell write UTF-8 so Cyrillic output survives.
    script = "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n" + script
    return [*PS_ARGS, "-EncodedCommand", base64.b64encode(script.encode("utf-16-le")).decode()]


def toast_script(title: str, body: str) -> str:
    return f"""
$m = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$xml = $m::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $xml.GetElementsByTagName('text')
$texts.Item(0).AppendChild($xml.CreateTextNode({ps_literal(title)})) | Out-Null
$texts.Item(1).AppendChild($xml.CreateTextNode({ps_literal(body)})) | Out-Null
$app = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe'
$m::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""  # noqa: E501


def shortcut_target_script(path: Path) -> str:
    return (
        f"(New-Object -ComObject WScript.Shell).CreateShortcut({ps_literal(str(path))}).TargetPath"
    )


def start_menu_dirs() -> list[Path]:
    dirs = []
    for var in ("ProgramData", "APPDATA"):
        base = os.environ.get(var)
        if base:
            dirs.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return dirs


SKIP_SHORTCUT_WORDS = ("uninstall", "удалить", "удаление", "readme", "help", "справка")


def scan_shortcuts(dirs: list[Path]) -> list[tuple[str, str]]:
    """(path, name) of Start Menu shortcuts, without uninstallers and docs."""
    found: dict[str, tuple[str, str]] = {}
    for base in dirs:
        if not base.is_dir():
            continue
        for path in base.rglob("*.lnk"):
            name = path.stem
            if any(word in name.casefold() for word in SKIP_SHORTCUT_WORDS):
                continue
            found.setdefault(name.casefold(), (str(path), name))
    return sorted(found.values(), key=lambda item: item[1].casefold())
