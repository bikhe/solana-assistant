"""Partial results for recognizers that only decode whole utterances.

While audio arrives, the growing buffer is re-decoded every ``partial_interval_s`` seconds
of new audio. Only one partial decode runs at a time, so a slow machine simply gets fewer
partials instead of falling behind.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from solana_core.audio.base import SAMPLE_RATE, SAMPLE_WIDTH
from solana_core.protocol import Language
from solana_core.stt.base import STTProvider, Transcript


class ChunkedStreamingSTT(STTProvider):
    partial_interval_s: float = 1.0
    min_partial_s: float = 0.6

    async def stream(
        self, frames: AsyncIterator[bytes], language: Language | None = None
    ) -> AsyncIterator[Transcript]:
        buffer = bytearray()
        step = int(SAMPLE_RATE * SAMPLE_WIDTH * self.partial_interval_s)
        minimum = int(SAMPLE_RATE * SAMPLE_WIDTH * self.min_partial_s)
        decoded_at = 0
        pending: asyncio.Task[Transcript] | None = None
        last_text = ""
        try:
            async for frame in frames:
                buffer += frame
                if pending is not None and pending.done():
                    result, pending = pending.result(), None
                    if result.text and result.text != last_text:
                        last_text = result.text
                        yield Transcript(result.text, result.language, final=False)
                if (
                    pending is None
                    and step > 0
                    and len(buffer) >= minimum
                    and len(buffer) - decoded_at >= step
                ):
                    decoded_at = len(buffer)
                    pending = asyncio.create_task(self.transcribe(bytes(buffer), language))
        finally:
            if pending is not None:
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pending
        yield await self.transcribe(bytes(buffer), language)
