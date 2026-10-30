from __future__ import annotations

from typing import Any

import pytest

from solana_core.brain.fast import parse


@pytest.mark.parametrize(
    ("phrase", "tool", "args"),
    [
        ("Громче", "pc.volume_change", {"delta": 10}),
        ("Солана, сделай погромче, пожалуйста!", "pc.volume_change", {"delta": 10}),
        ("намного громче", "pc.volume_change", {"delta": 20}),
        ("потише", "pc.volume_change", {"delta": -10}),
        ("убавь звук", "pc.volume_change", {"delta": -10}),
        ("громкость на 30", "pc.volume_set", {"level": 30}),
        ("поставь звук на пятьдесят процентов", "pc.volume_set", {"level": 50}),
        ("volume 70", "pc.volume_set", {"level": 70}),
        ("выключи звук", "pc.mute", {"muted": True}),
        ("включи звук", "pc.mute", {"muted": False}),
        ("Пауза.", "pc.media", {"action": "pause"}),
        ("поставь на паузу", "pc.media", {"action": "pause"}),
        ("продолжи", "pc.media", {"action": "play"}),
        ("следующий трек", "pc.media", {"action": "next"}),
        ("дальше", "pc.media", {"action": "next"}),
        ("предыдущая песня", "pc.media", {"action": "previous"}),
        ("открой браузер", "pc.app_open", {"name": "браузер"}),
        ("Эй, Солана, запусти Телеграм", "pc.app_open", {"name": "телеграм"}),
        ("открой ютуб", "pc.url_open", {"url": "https://youtube.com"}),
        ("открой habr.com", "pc.url_open", {"url": "https://habr.com"}),
        ("закрой-ка блокнот", "pc.app_close", {"name": "блокнот"}),
        ("найди в интернете рецепт блинов", "pc.web_search", {"query": "рецепт блинов"}),
        ("загугли курс доллара", "pc.web_search", {"query": "курс доллара"}),
        ("louder", "pc.volume_change", {"delta": 10}),
        ("open spotify", "pc.app_open", {"name": "spotify"}),
    ],
)
def test_fast_commands(phrase: str, tool: str, args: dict[str, Any]) -> None:
    match = parse(phrase)
    assert match is not None, phrase
    assert (match.tool, match.arguments) == (tool, args)
    assert match.reply_for("ru")


@pytest.mark.parametrize(
    "phrase",
    [
        "какая сегодня погода",
        "почему небо голубое",
        "открой файл отчёт за март",  # needs file search: LLM
        "включи свет на кухне",  # smart home, not an app
        "выключи компьютер",
        "громкость на двести",
        "расскажи что-нибудь интересное про громкость звука в концертных залах",
        "",
    ],
)
def test_not_fast(phrase: str) -> None:
    assert parse(phrase) is None


def test_reply_language() -> None:
    match = parse("громче")
    assert match is not None
    assert match.reply_for("ru") == "Громче."
    assert match.reply_for("en") == "Louder."
