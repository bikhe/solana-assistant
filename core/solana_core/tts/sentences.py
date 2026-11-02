"""Speak an answer while the LLM is still writing it.

``split_sentences`` turns text deltas into sentences as soon as each one ends, and
``speak_stream`` synthesizes them one by one. Synthesis runs ahead of playback, so the
next sentence is ready by the time the current one finishes.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterable, AsyncIterator

from solana_core.protocol import Language
from solana_core.tts.base import TTSProvider

# Words that end with a dot but do not end a sentence.
_ABBREVIATIONS = frozenset(
    [
        "т.е",
        "т.д",
        "т.п",
        "т.к",
        "др",
        "пр",
        "см",
        "ср",
        "им",
        "ул",
        "г",
        "гг",
        "д",
        "кв",
        "стр",
        "тыс",
        "млн",
        "млрд",
        "руб",
        "коп",
        "мин",
        "сек",
        "mr",
        "mrs",
        "ms",
        "dr",
        "st",
        "vs",
        "etc",
        "e.g",
        "i.e",
    ]
)
_END = re.compile(r"[.!?…]+[\"»”')\]]*(?=\s)|\n+")
_SOFT = re.compile(r"[,;:—–]\s")


def _is_abbreviation(text: str, dot: int) -> bool:
    if text[dot] != ".":
        return False
    head = text[:dot].split()
    word = head[-1].lstrip("(«\"'") if head else ""
    # A single capital letter is an initial ("А. С. Пушкин"); "это я." still ends a sentence.
    return word.lower() in _ABBREVIATIONS or (len(word) == 1 and word.isupper())


def _clean(sentence: str) -> str:
    sentence = re.sub(r"[*_`#]+", "", sentence)  # markdown the LLM may still produce
    return " ".join(sentence.split())


async def split_sentences(
    deltas: AsyncIterable[str], *, max_chars: int = 220, first_max_chars: int = 80
) -> AsyncIterator[str]:
    """Yield whole sentences from streamed text.

    A sentence longer than the limit is cut at the last comma or space. The first one has
    a lower limit, so the voice starts quickly even when the answer opens with a long phrase.
    """
    buffer = ""
    first = True
    async for delta in deltas:
        buffer += delta
        while True:
            cut = _find_cut(buffer, first_max_chars if first else max_chars)
            if cut is None:
                break
            sentence, buffer = _clean(buffer[:cut]), buffer[cut:].lstrip()
            if sentence:
                first = False
                yield sentence
    if tail := _clean(buffer):
        yield tail


def _find_cut(text: str, limit: int) -> int | None:
    for match in _END.finditer(text):
        if not _is_abbreviation(text, match.start()):
            return match.end()
    if len(text) <= limit:
        return None
    soft = [m.end() for m in _SOFT.finditer(text, 0, limit)]
    if soft:
        return soft[-1]
    space = text.rfind(" ", 0, limit)
    return space + 1 if space > 0 else limit


async def speak_stream(
    tts: TTSProvider,
    deltas: AsyncIterable[str],
    language: Language | None = None,
    *,
    lookahead_chunks: int = 256,
) -> AsyncIterator[bytes]:
    """Audio for streamed text, sentence by sentence. Closing the iterator stops synthesis."""
    queue: asyncio.Queue[bytes | BaseException | None] = asyncio.Queue(lookahead_chunks)

    async def produce() -> None:
        try:
            async for sentence in split_sentences(deltas):
                async for chunk in tts.synthesize(sentence, language):
                    await queue.put(chunk)
            await queue.put(None)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            await queue.put(exc)

    producer = asyncio.create_task(produce())
    try:
        while (item := await queue.get()) is not None:
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        producer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer


async def text_stream(text: str) -> AsyncIterator[str]:
    """Wrap a ready string, for ``speak_stream`` on a non-streamed answer."""
    yield text
