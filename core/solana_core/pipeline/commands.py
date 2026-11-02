"""Words the pipeline handles itself, without the dialog: stop, cancel, and questions that
open the follow-up window."""

from __future__ import annotations

import re

_PUNCT = re.compile(r"[^\w\s]+")
_SPACES = re.compile(r"\s+")
# What is left of the wake word when the recognizer catches its tail.
_WAKE_PREFIX = re.compile(r"^(?:(?:эй|hey|ok|окей)\s+)?(?:солана|лана|solana|lana)\b\s*")

STOP_PHRASES = frozenset(
    ["стоп", "хватит", "замолчи", "замолкни", "остановись", "stop", "enough", "be quiet"]
)
CANCEL_PHRASES = frozenset(
    [
        "отмена",
        "отмени",
        "отменить",
        "не надо",
        "уже не надо",
        "ничего",
        "забудь",
        "cancel",
        "never mind",
        "nevermind",
        "forget it",
        "nothing",
    ]
)


def normalize(text: str) -> str:
    """Lower case, no punctuation, no leading wake word."""
    text = text.lower().replace("ё", "е")
    text = _SPACES.sub(" ", _PUNCT.sub(" ", text)).strip()
    return _WAKE_PREFIX.sub("", text).strip()


def strip_wake_word(text: str) -> str:
    """Drop a leading "Эй, Солана" the recognizer may include, keeping the original case."""
    words = text.split()
    for n in (2, 1):
        if len(words) > n and not normalize(" ".join(words[:n])):
            return " ".join(words[n:])
    return text


def _matches(text: str, phrases: frozenset[str]) -> bool:
    phrase = normalize(text)
    if not phrase:
        return False
    if phrase in phrases:
        return True
    # "стоп стоп", "хватит, хватит"
    words = phrase.split()
    return len(words) <= 3 and all(w in phrases for w in words)


def is_stop(text: str) -> bool:
    return _matches(text, STOP_PHRASES)


def is_cancel(text: str) -> bool:
    return _matches(text, CANCEL_PHRASES) or is_stop(text)


def is_question(answer: str) -> bool:
    """True when the answer ends by asking the user something."""
    return answer.rstrip(" \n\"'»”)").endswith("?")
