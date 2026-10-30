"""PC tools for the assistant, built on top of any ``PcBackend``.

Tool names and arguments are shared with the fast-command parser in ``brain/fast.py``
(``pc.volume_set``, ``pc.app_open`` …), so keep them stable.
"""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import logging
import re
from abc import abstractmethod
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import quote_plus, urlparse

from solana_core.pc.base import AppInfo, NotSupportedError, PcBackend, WindowInfo
from solana_core.pc.common import CommandError
from solana_core.tools.base import Tool, ToolContext, ToolError, ToolResult
from solana_core.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

# Matching spoken names to apps and windows

_TRANSLIT = dict(
    zip(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        [
            "a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o",
            "p", "r", "s", "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e",
            "yu", "ya",
        ],
        strict=True,
    )
)  # fmt: skip

# How people say app names in Russian -> a word found in the app's real name or id.
APP_ALIASES: dict[str, str] = {
    "хром": "chrome",
    "гугл хром": "chrome",
    "браузер": "browser",
    "файрфокс": "firefox",
    "фаерфокс": "firefox",
    "мозилла": "firefox",
    "яндекс браузер": "yandex",
    "эдж": "edge",
    "сафари": "safari",
    "телеграм": "telegram",
    "телега": "telegram",
    "дискорд": "discord",
    "стим": "steam",
    "спотифай": "spotify",
    "вскод": "code",
    "вс код": "code",
    "визуал студио код": "code",
    "блокнот": "notepad",
    "проводник": "explorer",
    "файлы": "files",
    "файндер": "finder",
    "терминал": "terminal",
    "консоль": "terminal",
    "калькулятор": "calc",
    "настройки": "settings",
    "ворд": "word",
    "эксель": "excel",
    "обс": "obs",
    "влц": "vlc",
}

_NAME_SUFFIXES = (".desktop", ".lnk", ".app", ".exe")


def normalize(text: str) -> str:
    text = text.casefold().strip()
    for suffix in _NAME_SUFFIXES:
        text = text.removesuffix(suffix)
    return re.sub(r"[\s_.-]+", " ", text).strip()


def transliterate(text: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in text)


def _variants(spoken: str) -> list[str]:
    base = normalize(spoken)
    out = [base]
    if base in APP_ALIASES:
        out.append(APP_ALIASES[base])
    translit = transliterate(base)
    if translit != base:
        out.append(translit)
    return out


def _score(candidate: str, variants: Sequence[str]) -> float:
    cand = normalize(candidate)
    best = 0.0
    for v in variants:
        if not v or not cand:
            continue
        if cand == v:
            return 1.0
        if cand.startswith(v) or f" {v}" in f" {cand}":
            best = max(best, 0.9)
        elif v in cand:
            best = max(best, 0.75)
        else:
            best = max(best, difflib.SequenceMatcher(None, v, cand).ratio() * 0.8)
    return best


def find_app(apps: Sequence[AppInfo], spoken: str) -> AppInfo | None:
    variants = _variants(spoken)
    scored: list[tuple[float, int, AppInfo]] = []
    for app in apps:
        stem = Path(app.id).name if ("/" in app.id or "\\" in app.id) else app.id
        score = max(_score(app.name, variants), _score(stem, variants) - 0.05)
        scored.append((score, -len(app.name), app))
    if not scored:
        return None
    score, _, app = max(scored, key=lambda s: (s[0], s[1]))
    return app if score >= 0.6 else None


def find_window(windows: Sequence[WindowInfo], spoken: str) -> WindowInfo | None:
    for w in windows:
        if w.id == spoken:
            return w
    variants = _variants(spoken)
    scored = [(max(_score(w.app, variants), _score(w.title, variants)), w) for w in windows]
    if not scored:
        return None
    score, window = max(scored, key=lambda s: s[0])
    return window if score >= 0.6 else None


# Base class


class PcTool(Tool):
    """A tool that talks to a ``PcBackend`` and turns its failures into spoken answers."""

    def __init__(self, pc: PcBackend) -> None:
        self.pc = pc

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            return await self.call(args, ctx)
        except NotSupportedError as e:
            reason = f": {e.reason}" if e.reason else ""
            return ToolResult(f"Не поддерживается на этом компьютере{reason}", ok=False)
        except ToolError as e:
            return ToolResult(str(e), ok=False)
        except FileNotFoundError as e:
            return ToolResult(f"Не нашла файл: {e.args[0] if e.args else ''}", ok=False)
        except FileExistsError as e:
            return ToolResult(f"Там уже есть файл с таким именем: {e.args[0]}", ok=False)
        except PermissionError:
            return ToolResult("Нет прав на это действие", ok=False)
        except (CommandError, OSError) as e:
            log.warning("%s failed: %s", self.name, e)
            return ToolResult(f"Не получилось: {e}", ok=False)

    @abstractmethod
    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


def _str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"Не хватает параметра «{key}»")
    return value.strip()


def _int(args: dict[str, Any], key: str) -> int:
    value = args.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ToolError(f"Параметр «{key}» должен быть числом")
    return int(value)


def _path(args: dict[str, Any], key: str) -> Path:
    path = Path(_str(args, key)).expanduser()
    return path if path.is_absolute() else Path.home() / path


def _schema(**props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props)}


STRING: dict[str, Any] = {"type": "string"}
WINDOW: dict[str, Any] = {
    "type": "string",
    "description": "id окна из pc.windows_list или часть названия/приложения",
}
PATH: dict[str, Any] = {"type": "string", "description": "Полный путь к файлу или папке"}

# Apps


class AppsList(PcTool):
    name = "pc.apps_list"
    description = "Список установленных приложений. Можно отфильтровать по части названия."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"query": STRING},
    }

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        apps = await self.pc.list_apps()
        query = args.get("query")
        if isinstance(query, str) and query.strip():
            variants = _variants(query)
            apps = [a for a in apps if _score(a.name, variants) >= 0.6]
        names = [a.name for a in apps[:100]]
        more = f" и ещё {len(apps) - 100}" if len(apps) > 100 else ""
        return ToolResult(
            ", ".join(names) + more if names else "Ничего не нашла",
            data={"apps": [{"id": a.id, "name": a.name} for a in apps[:100]]},
        )


class AppOpen(PcTool):
    name = "pc.app_open"
    description = "Открыть приложение по названию, как его назвал пользователь."
    parameters: ClassVar[dict[str, Any]] = _schema(name=STRING)

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        spoken = _str(args, "name")
        try:
            apps = await self.pc.list_apps()
        except NotSupportedError:
            apps = []
        app = find_app(apps, spoken)
        await self.pc.open_app(app.id if app else spoken)
        return ToolResult(f"Открываю {app.name if app else spoken}", data={"app": app and app.id})


class AppClose(PcTool):
    name = "pc.app_close"
    description = "Закрыть приложение по названию. Несохранённые данные могут пропасть."
    parameters: ClassVar[dict[str, Any]] = _schema(name=STRING)
    risk = "confirm"

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        spoken = _str(args, "name")
        try:
            apps = await self.pc.list_apps()
        except NotSupportedError:
            apps = []
        app = find_app(apps, spoken)
        await self.pc.close_app(app.id if app else spoken)
        return ToolResult(f"Закрыла {app.name if app else spoken}")


# Windows


class WindowsList(PcTool):
    name = "pc.windows_list"
    description = "Список открытых окон: id, приложение, заголовок."

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        windows = await self.pc.list_windows()
        lines = [
            f"{w.id} | {w.app} | {w.title}{' (активное)' if w.focused else ''}" for w in windows
        ]
        return ToolResult(
            "\n".join(lines) if lines else "Открытых окон нет",
            data={"windows": [{"id": w.id, "app": w.app, "title": w.title} for w in windows]},
        )


class _WindowTool(PcTool):
    parameters: ClassVar[dict[str, Any]] = _schema(window=WINDOW)
    done: ClassVar[str]

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        window = find_window(await self.pc.list_windows(), _str(args, "window"))
        if window is None:
            raise ToolError("Не нашла такое окно")
        await self.act(window.id)
        return ToolResult(f"{self.done}: {window.title or window.app}")

    @abstractmethod
    async def act(self, window_id: str) -> None: ...


class WindowFocus(_WindowTool):
    name = "pc.window_focus"
    description = "Переключиться на окно."
    done = "Переключилась на окно"

    async def act(self, window_id: str) -> None:
        await self.pc.focus_window(window_id)


class WindowMinimize(_WindowTool):
    name = "pc.window_minimize"
    description = "Свернуть окно."
    done = "Свернула окно"

    async def act(self, window_id: str) -> None:
        await self.pc.minimize_window(window_id)


class WindowMaximize(_WindowTool):
    name = "pc.window_maximize"
    description = "Развернуть окно на весь экран."
    done = "Развернула окно"

    async def act(self, window_id: str) -> None:
        await self.pc.maximize_window(window_id)


class WindowClose(_WindowTool):
    name = "pc.window_close"
    description = "Закрыть окно."
    done = "Закрыла окно"
    risk = "confirm"

    async def act(self, window_id: str) -> None:
        await self.pc.close_window(window_id)


# Sound and media


class VolumeGet(PcTool):
    name = "pc.volume_get"
    description = "Узнать текущую громкость (0–100)."

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        level = await self.pc.get_volume()
        return ToolResult(f"Громкость {level}%", data={"level": level})


class VolumeSet(PcTool):
    name = "pc.volume_set"
    description = "Поставить громкость от 0 до 100."
    parameters: ClassVar[dict[str, Any]] = _schema(
        level={"type": "integer", "minimum": 0, "maximum": 100}
    )

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        level = max(0, min(100, _int(args, "level")))
        await self.pc.set_volume(level)
        if level > 0:
            await _unmute(self.pc)
        return ToolResult(f"Громкость {level}%", data={"level": level})


class VolumeChange(PcTool):
    name = "pc.volume_change"
    description = "Сделать громче или тише: delta от -100 до 100, например 10 или -10."
    parameters: ClassVar[dict[str, Any]] = _schema(
        delta={"type": "integer", "minimum": -100, "maximum": 100}
    )

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        delta = _int(args, "delta")
        level = max(0, min(100, await self.pc.get_volume() + delta))
        await self.pc.set_volume(level)
        if delta > 0:
            await _unmute(self.pc)
        return ToolResult(f"Громкость {level}%", data={"level": level})


async def _unmute(pc: PcBackend) -> None:
    with contextlib.suppress(NotSupportedError, CommandError):
        await pc.set_muted(False)


class Mute(PcTool):
    name = "pc.mute"
    description = "Выключить (muted=true) или включить (muted=false) звук."
    parameters: ClassVar[dict[str, Any]] = _schema(muted={"type": "boolean"})

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        muted = bool(args.get("muted", True))
        await self.pc.set_muted(muted)
        return ToolResult("Звук выключен" if muted else "Звук включён")


class Media(PcTool):
    name = "pc.media"
    description = "Управление музыкой и видео: пауза, продолжить, следующий, предыдущий трек."
    parameters: ClassVar[dict[str, Any]] = _schema(
        action={"type": "string", "enum": ["play_pause", "play", "pause", "next", "previous"]}
    )

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        action = _str(args, "action")
        if action == "next":
            await self.pc.media_next()
            return ToolResult("Следующий трек")
        if action == "previous":
            await self.pc.media_previous()
            return ToolResult("Предыдущий трек")
        if action not in ("play_pause", "play", "pause"):
            raise ToolError(f"Неизвестное действие: {action}")
        if action != "play_pause":
            try:
                info = await self.pc.now_playing()
            except (NotSupportedError, CommandError, ToolError, OSError):
                info = None
            # Only toggle when it changes something; unknown state toggles anyway.
            if info is not None and info.playing == (action == "play"):
                return ToolResult("Уже играет" if action == "play" else "Уже на паузе")
        await self.pc.media_play_pause()
        return ToolResult({"play": "Продолжаю", "pause": "Пауза"}.get(action, "Готово"))


class NowPlaying(PcTool):
    name = "pc.now_playing"
    description = "Что сейчас играет: трек, исполнитель, приложение."

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        info = await self.pc.now_playing()
        if info is None or not (info.title or info.artist):
            return ToolResult("Сейчас ничего не играет", data={"playing": False})
        track = " — ".join(x for x in (info.artist, info.title) if x)
        state = "Играет" if info.playing else "На паузе"
        where = f" в {info.app}" if info.app else ""
        return ToolResult(
            f"{state}{where}: {track}",
            data={
                "playing": info.playing,
                "title": info.title,
                "artist": info.artist,
                "app": info.app,
            },
        )


# Files

EXECUTABLE_SUFFIXES = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".ps1", ".vbs", ".js", ".jse", ".wsf", ".scr",
    ".lnk", ".sh", ".command", ".app", ".desktop", ".appimage", ".run", ".jar", ".py",
}  # fmt: skip


class FilesSearch(PcTool):
    name = "pc.files_search"
    description = "Найти файлы и папки по части имени в папках пользователя."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"query": STRING, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
        "required": ["query"],
    }

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        limit = _int(args, "limit") if "limit" in args else 10
        hits = await self.pc.search_files(_str(args, "query"), max(1, min(50, limit)))
        if not hits:
            return ToolResult("Ничего не нашла", data={"files": []})
        lines = [f"{h.path}{'/' if h.is_dir else ''}" for h in hits]
        return ToolResult(
            "\n".join(lines),
            data={"files": [{"path": str(h.path), "is_dir": h.is_dir} for h in hits]},
        )


class FileOpen(PcTool):
    name = "pc.file_open"
    description = "Открыть файл или папку в программе по умолчанию. Программы так не запускаются."
    parameters: ClassVar[dict[str, Any]] = _schema(path=PATH)

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = _path(args, "path")
        if path.suffix.casefold() in EXECUTABLE_SUFFIXES:
            raise ToolError("Программы и скрипты так не открываю, это небезопасно")
        await self.pc.open_path(path)
        return ToolResult(f"Открываю {path.name}")


class FileReveal(PcTool):
    name = "pc.file_reveal"
    description = "Показать файл в папке (в проводнике или Finder)."
    parameters: ClassVar[dict[str, Any]] = _schema(path=PATH)

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = _path(args, "path")
        await self.pc.reveal_path(path)
        return ToolResult(f"Показываю {path.name}")


class FileMove(PcTool):
    name = "pc.file_move"
    description = "Переместить или переименовать файл. Существующие файлы не перезаписываются."
    parameters: ClassVar[dict[str, Any]] = _schema(
        src=PATH, dst={"type": "string", "description": "Новый путь или папка назначения"}
    )
    risk = "confirm"

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        src, dst = _path(args, "src"), _path(args, "dst")
        await self.pc.move_path(src, dst)
        return ToolResult(f"Переместила {src.name} в {dst}")


class FileTrash(PcTool):
    name = "pc.file_trash"
    description = "Переместить файл или папку в корзину. Безвозвратно не удаляет."
    parameters: ClassVar[dict[str, Any]] = _schema(path=PATH)
    risk = "confirm"

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = _path(args, "path")
        await self.pc.trash_path(path)
        return ToolResult(f"{path.name} в корзине")


# Browser

SEARCH_URLS = {
    "ru": "https://yandex.ru/search/?text={}",
    "en": "https://www.google.com/search?q={}",
}


def normalize_url(url: str) -> str:
    url = url.strip()
    if "://" not in url and re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:(?!\d)", url):
        raise ToolError("Открываю только веб-адреса (http и https)")  # mailto:, javascript:
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ToolError("Открываю только веб-адреса (http и https)")
    return url


class UrlOpen(PcTool):
    name = "pc.url_open"
    description = "Открыть сайт в браузере по умолчанию."
    parameters: ClassVar[dict[str, Any]] = _schema(url=STRING)

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        url = normalize_url(_str(args, "url"))
        await self.pc.open_url(url)
        return ToolResult(f"Открываю {urlparse(url).netloc}", data={"url": url})


class WebSearch(PcTool):
    name = "pc.web_search"
    description = "Открыть поиск в браузере по запросу."
    parameters: ClassVar[dict[str, Any]] = _schema(query=STRING)

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = _str(args, "query")
        url = SEARCH_URLS.get(ctx.language, SEARCH_URLS["ru"]).format(quote_plus(query))
        await self.pc.open_url(url)
        return ToolResult(f"Ищу «{query}»", data={"url": url})


# System

CLIPBOARD_LIMIT = 4000


class ClipboardGet(PcTool):
    name = "pc.clipboard_get"
    description = "Прочитать текст из буфера обмена."

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        text = await self.pc.get_clipboard()
        if not text:
            return ToolResult("Буфер обмена пуст")
        cut = text[:CLIPBOARD_LIMIT]
        return ToolResult(cut + ("…" if len(text) > CLIPBOARD_LIMIT else ""))


class ClipboardSet(PcTool):
    name = "pc.clipboard_set"
    description = "Положить текст в буфер обмена."
    parameters: ClassVar[dict[str, Any]] = _schema(text=STRING)

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        text = args.get("text")
        if not isinstance(text, str):
            raise ToolError("Не хватает параметра «text»")
        await self.pc.set_clipboard(text)
        return ToolResult("Скопировала в буфер обмена")


def screenshot_dir() -> Path:
    pictures = Path.home() / "Pictures"
    return (pictures if pictures.is_dir() else Path.home()) / "Screenshots"


def _save(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class Screenshot(PcTool):
    name = "pc.screenshot"
    description = "Сделать скриншот всего экрана и сохранить в папку «Изображения/Screenshots»."

    def __init__(self, pc: PcBackend, folder: Path | None = None) -> None:
        super().__init__(pc)
        self.folder = folder

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        png = await self.pc.screenshot()
        path = (self.folder or screenshot_dir()) / f"solana-{datetime.now():%Y%m%d-%H%M%S}.png"
        await asyncio.to_thread(_save, path, png)
        return ToolResult(f"Скриншот сохранён: {path}", data={"path": str(path)})


class Battery(PcTool):
    name = "pc.battery"
    description = "Заряд батареи и идёт ли зарядка."

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        info = await self.pc.battery()
        if info is None:
            return ToolResult("Батареи нет, компьютер работает от сети", data={"battery": False})
        charging = ", заряжается" if info.charging else ""
        return ToolResult(
            f"Заряд {round(info.percent)}%{charging}",
            data={"percent": info.percent, "charging": info.charging},
        )


class Notify(PcTool):
    name = "pc.notify"
    description = "Показать системное уведомление."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"title": STRING, "body": STRING},
        "required": ["body"],
    }

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        title = args.get("title") if isinstance(args.get("title"), str) else None
        await self.pc.notify(title or "Solana", _str(args, "body"))
        return ToolResult("Уведомление показано")


class Lock(PcTool):
    name = "pc.lock"
    description = "Заблокировать экран."

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        await self.pc.lock_screen()
        return ToolResult("Экран заблокирован")


class Sleep(PcTool):
    name = "pc.sleep"
    description = "Перевести компьютер в спящий режим."
    risk = "confirm"

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        await self.pc.sleep()
        return ToolResult("Ухожу в сон")


class Shutdown(PcTool):
    name = "pc.shutdown"
    description = "Выключить компьютер. Несохранённые данные пропадут."
    risk = "dangerous"

    async def call(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        await self.pc.shutdown()
        return ToolResult("Выключаю компьютер")


PC_TOOLS: tuple[type[PcTool], ...] = (
    AppsList, AppOpen, AppClose,
    WindowsList, WindowFocus, WindowMinimize, WindowMaximize, WindowClose,
    VolumeGet, VolumeSet, VolumeChange, Mute, Media, NowPlaying,
    FilesSearch, FileOpen, FileReveal, FileMove, FileTrash,
    UrlOpen, WebSearch,
    ClipboardGet, ClipboardSet, Screenshot, Battery, Notify, Lock, Sleep, Shutdown,
)  # fmt: skip


def build_pc_tools(pc: PcBackend) -> list[PcTool]:
    return [cls(pc) for cls in PC_TOOLS]


def register_pc_tools(registry: ToolRegistry, pc: PcBackend | None = None) -> list[PcTool]:
    """Register every PC tool. Operations the OS lacks answer "не поддерживается"."""
    if pc is None:
        from solana_core.pc import get_pc_backend

        pc = get_pc_backend()
    tools = build_pc_tools(pc)
    for tool in tools:
        registry.register(tool)
    return tools
