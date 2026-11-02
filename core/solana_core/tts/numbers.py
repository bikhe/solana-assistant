"""Spell out numbers in Russian: Silero reads only letters, so "15" would be skipped."""

from __future__ import annotations

import re

_UNITS = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_TEENS = [
    "десять",
    "одиннадцать",
    "двенадцать",
    "тринадцать",
    "четырнадцать",
    "пятнадцать",
    "шестнадцать",
    "семнадцать",
    "восемнадцать",
    "девятнадцать",
]
_TENS = [
    "_",
    "_",
    "двадцать",
    "тридцать",
    "сорок",
    "пятьдесят",
    "шестьдесят",
    "семьдесят",
    "восемьдесят",
    "девяносто",
]
_HUNDREDS = [
    "_",
    "сто",
    "двести",
    "триста",
    "четыреста",
    "пятьсот",
    "шестьсот",
    "семьсот",
    "восемьсот",
    "девятьсот",
]
# (one, few, many, feminine)
_SCALES = (
    ("тысяча", "тысячи", "тысяч", True),
    ("миллион", "миллиона", "миллионов", False),
    ("миллиард", "миллиарда", "миллиардов", False),
)


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 100 in range(11, 15):
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(n % 10, many)


def _triple(n: int, feminine: bool) -> list[str]:
    words: list[str] = []
    if n >= 100:
        words.append(_HUNDREDS[n // 100])
    rest = n % 100
    if 10 <= rest < 20:
        words.append(_TEENS[rest - 10])
        return words
    if rest >= 20:
        words.append(_TENS[rest // 10])
    unit = rest % 10
    if unit:
        if feminine and unit in (1, 2):
            words.append("одна" if unit == 1 else "две")
        else:
            words.append(_UNITS[unit])
    return words


def number_to_words(n: int) -> str:
    if n == 0:
        return _UNITS[0]
    if n < 0:
        return "минус " + number_to_words(-n)
    if n >= 10**12:
        return " ".join(_UNITS[int(d)] for d in str(n))
    words: list[str] = []
    for power in (3, 2, 1):
        part = n // 1000**power % 1000
        if part:
            one, few, many, feminine = _SCALES[power - 1]
            words += [*_triple(part, feminine), _plural(part, one, few, many)]
    words += _triple(n % 1000, feminine=False)
    return " ".join(words)


_NUMBER = re.compile(r"(?<![\w.,])(-?\d+)(?:[.,](\d+))?(?![\w])")


def spell_numbers_ru(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        whole = number_to_words(int(match.group(1)))
        if match.group(2) is None:
            return whole
        return f"{whole} и {' '.join(_UNITS[int(d)] for d in match.group(2))}"

    text = text.replace("%", " процентов").replace("°", " градусов")
    return _NUMBER.sub(replace, text)
