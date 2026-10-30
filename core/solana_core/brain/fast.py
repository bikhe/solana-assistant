"""Frequent commands parsed without the LLM, so "громче" or "пауза" work instantly.

Each match names a tool from ``ToolRegistry``. The dialog uses the match only if that tool
is registered and enabled; otherwise the phrase goes to the LLM as usual. Tool names and
arguments are agreed with WP5 (``pc/tools.py``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from solana_core.protocol import Language

VOLUME_STEP = 10


@dataclass(frozen=True, slots=True)
class FastMatch:
    tool: str
    arguments: dict[str, Any]
    reply: dict[Language, str] = field(default_factory=dict)  # spoken when the tool succeeds

    def reply_for(self, language: Language) -> str:
        return self.reply.get(language) or self.reply.get("ru", "")


_FILLER = re.compile(
    r"\b(?:эй|солана|пожалуйста|please|hey|solana|ну|а|ка|давай|можешь|можно|"
    r"could you|can you)\b",
)
_PUNCT = re.compile(r"[^\w\s.:/?=&%#-]+")  # keeps what URLs need
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е").replace("-ка", "")
    text = _PUNCT.sub(" ", text)
    text = _FILLER.sub(" ", text)
    return _SPACES.sub(" ", text).strip(" .?")


_NUMBER_WORDS = {
    "ноль": 0, "десять": 10, "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "половину": 50, "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
    "сто": 100, "максимум": 100, "минимум": 0,
    "zero": 0, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "half": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "max": 100,
}  # fmt: skip

_SITES = {
    "ютуб": "youtube.com", "youtube": "youtube.com", "гугл": "google.com", "google": "google.com",
    "вк": "vk.com", "вконтакте": "vk.com", "гитхаб": "github.com", "github": "github.com",
    "википедию": "ru.wikipedia.org", "википедия": "ru.wikipedia.org",
    "wikipedia": "en.wikipedia.org",
}  # fmt: skip

_DOMAIN = re.compile(r"^(?:https?://)?(?:[\w-]+\.)+[a-z]{2,}(?:/\S*)?$")
# "Открой файл/папку …" needs a file search, which is a job for the LLM.
_NOT_AN_APP = re.compile(r"^(?:файл|папк|документ|сайт|страниц|file|folder|website|page)\w*\b")

Rule = tuple[re.Pattern[str], Callable[[re.Match[str]], FastMatch | None]]


def _volume(delta: int) -> FastMatch:
    word_ru, word_en = ("Громче", "Louder") if delta > 0 else ("Тише", "Quieter")
    return FastMatch(
        "pc.volume_change", {"delta": delta}, {"ru": f"{word_ru}.", "en": f"{word_en}."}
    )


def _volume_set(m: re.Match[str]) -> FastMatch | None:
    raw = m.group("n")
    level = int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw)
    if level is None or not 0 <= level <= 100:
        return None
    return FastMatch(
        "pc.volume_set", {"level": level}, {"ru": f"Громкость {level}.", "en": f"Volume {level}."}
    )


def _media(action: str, ru: str, en: str) -> Callable[[re.Match[str]], FastMatch]:
    return lambda _: FastMatch("pc.media", {"action": action}, {"ru": ru, "en": en})


def _mute(muted: bool) -> Callable[[re.Match[str]], FastMatch]:
    ru, en = ("Звук выключен.", "Muted.") if muted else ("Звук включён.", "Unmuted.")
    return lambda _: FastMatch("pc.mute", {"muted": muted}, {"ru": ru, "en": en})


def _open(m: re.Match[str]) -> FastMatch | None:
    target = m.group("what").strip()
    if not target or _NOT_AN_APP.match(target):
        return None
    site = _SITES.get(target)
    if site or _DOMAIN.match(target):
        url = site or target
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        return FastMatch(
            "pc.url_open", {"url": url}, {"ru": f"Открываю {target}.", "en": f"Opening {target}."}
        )
    return FastMatch(
        "pc.app_open", {"name": target}, {"ru": f"Открываю {target}.", "en": f"Opening {target}."}
    )


def _close(m: re.Match[str]) -> FastMatch | None:
    target = m.group("what").strip()
    if not target or _NOT_AN_APP.match(target):
        return None
    return FastMatch(
        "pc.app_close", {"name": target}, {"ru": f"Закрыла {target}.", "en": f"Closed {target}."}
    )


def _search(m: re.Match[str]) -> FastMatch | None:
    query = m.group("q").strip()
    if not query:
        return None
    return FastMatch(
        "pc.web_search", {"query": query}, {"ru": f"Ищу {query}.", "en": f"Searching for {query}."}
    )


def _rule(pattern: str, build: Callable[[re.Match[str]], FastMatch | None]) -> Rule:
    return re.compile(rf"^(?:{pattern})$"), build


_MORE = r"(?:еще |чуть |немного |намного |гораздо )?"
_RULES: list[Rule] = [
    _rule(
        rf"{_MORE}(?:по)?громче|сделай {_MORE}(?:по)?громче|прибавь(?: звук| громкость)?|"
        r"louder|volume up|turn it up",
        lambda m: _volume(2 * VOLUME_STEP if "намного" in m.group(0) else VOLUME_STEP),
    ),
    _rule(
        rf"{_MORE}(?:по)?тише|сделай {_MORE}(?:по)?тише|убавь(?: звук| громкость)?|"
        r"quieter|volume down|turn it down",
        lambda m: _volume(-2 * VOLUME_STEP if "намного" in m.group(0) else -VOLUME_STEP),
    ),
    _rule(
        r"(?:поставь |сделай |установи )?(?:громкость|звук)(?: на)? (?P<n>\w+)(?: процент\w*| %)?",
        _volume_set,
    ),
    _rule(r"(?:set )?volume(?: to)? (?P<n>\w+)(?: percent| %)?", _volume_set),
    _rule(r"выключи звук|без звука|отключи звук|mute|mute sound", _mute(True)),
    _rule(r"включи звук|верни звук|unmute", _mute(False)),
    _rule(
        r"пауза|на паузу|поставь на паузу|останови музыку|pause|pause music",
        _media("pause", "Пауза.", "Paused."),
    ),
    _rule(
        r"продолжи|продолжай|играй|включи музыку|сними с паузы|play|resume|play music",
        _media("play", "Продолжаю.", "Playing."),
    ),
    _rule(
        r"(?:следующ\w+|дальше)(?: трек| песн\w+| композици\w+)?|переключи(?: трек| песню)?|"
        r"next(?: track| song)?|skip",
        _media("next", "Следующий трек.", "Next track."),
    ),
    _rule(
        r"предыдущ\w+(?: трек| песн\w+| композици\w+)?|previous(?: track| song)?",
        _media("previous", "Предыдущий трек.", "Previous track."),
    ),
    _rule(r"(?:найди|поищи|ищи) в (?:интернете|гугле|google|сети) (?P<q>.+)", _search),
    _rule(r"загугли (?P<q>.+)", _search),
    _rule(r"(?:search|google)(?: the web)?(?: for)? (?P<q>.+)", _search),
    _rule(r"(?:открой|запусти|open|launch) (?P<what>.+)", _open),
    _rule(r"(?:закрой|close|quit) (?P<what>.+)", _close),
]


def parse(text: str) -> FastMatch | None:
    """Match a short command. Returns ``None`` for anything else."""
    phrase = normalize(text)
    if not phrase or len(phrase.split()) > 8:
        return None
    for pattern, build in _RULES:
        m = pattern.match(phrase)
        if m:
            return build(m)
    return None
