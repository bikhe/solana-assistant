"""Measure speech latency on this machine and print a Markdown table for the PR.

    uv sync --extra speech
    uv run python scripts/bench_speech.py --download
    uv run python scripts/bench_speech.py --wav my_phrase.wav --stt gigaam faster-whisper

STT: time from the end of a ~5 s Russian phrase to the final text (model already loaded).
TTS: time from the text to the first audio chunk. Without ``--wav`` the phrase is spoken by
the first TTS provider and fed back to the recognizers.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from pathlib import Path

from solana_core.config import KeyringSecretStore
from solana_core.models import ModelManager, detect_hardware
from solana_core.models.hardware import default_stt_model
from solana_core.stt import create_stt
from solana_core.stt.audio import duration_s, read_wav, resample_pcm16
from solana_core.tts import PIPER_VOICES, create_tts

PHRASE = (
    "Солана, включи, пожалуйста, музыку в гостиной, сделай погромче "
    "и напомни мне через десять минут проверить духовку."
)
TTS_MODELS = {"silero": ["silero-tts-ru", *PIPER_VOICES.values()], "piper": PIPER_VOICES.values()}


async def timed(coro: object) -> tuple[float, object]:
    started = time.perf_counter()
    result = await coro  # type: ignore[misc]
    return time.perf_counter() - started, result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", type=Path, help="16 kHz mono WAV with a ~5 s phrase")
    parser.add_argument("--stt", nargs="*", default=["gigaam", "faster-whisper", "whisper.cpp"])
    parser.add_argument("--tts", nargs="*", default=["silero", "piper"])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--download", action="store_true", help="download missing models first")
    args = parser.parse_args()

    hw = detect_hardware()
    models = ModelManager()
    secrets = KeyringSecretStore()
    print(f"Machine: {hw}\n")

    if args.download:
        wanted = [default_stt_model(p, hw) for p in args.stt if p != "openai"]
        wanted += [m for p in args.tts for m in TTS_MODELS.get(p, [])]
        for model_id in dict.fromkeys(wanted):
            print(f"downloading {model_id} ...", flush=True)
            await models.download(model_id)

    rows = [
        "| Этап | Движок | Модель | Аудио, с | Медиана, с | Мин, с |",
        "|---|---|---|---|---|---|",
    ]
    phrase: bytes | None = None
    if args.wav:
        pcm, rate = read_wav(str(args.wav))
        phrase = resample_pcm16(pcm, rate, 16_000)

    for provider in args.tts:
        try:
            tts = create_tts(provider, models=models, secrets=secrets)
            load = getattr(tts, "load", None)
            for voice in getattr(tts, "providers", {}).values():
                if hasattr(voice, "load"):
                    await voice.load()
            if load:
                await load()
        except Exception as exc:
            rows.append(f"| TTS | {provider} | - | - | ошибка: {exc} | - |")
            continue
        firsts: list[float] = []
        audio = b""
        for _ in range(args.runs):
            started = time.perf_counter()
            chunks: list[bytes] = []
            async for chunk in tts.synthesize("Хорошо, включаю музыку в гостиной.", "ru"):
                if not chunks:
                    firsts.append(time.perf_counter() - started)
                chunks.append(chunk)
            audio = b"".join(chunks)
        if phrase is None:
            spoken = b"".join([c async for c in tts.synthesize(PHRASE, "ru")])
            phrase = resample_pcm16(spoken, tts.sample_rate, 16_000)
        rows.append(
            f"| TTS, первый звук | {provider} | - | {duration_s(audio, tts.sample_rate):.1f} "
            f"| {statistics.median(firsts):.2f} | {min(firsts):.2f} |"
        )

    if phrase is None:
        raise SystemExit("No phrase: pass --wav or a working --tts provider")
    for provider in args.stt:
        model_id = default_stt_model(provider, hw) if provider != "openai" else "-"
        try:
            stt = create_stt(provider, models=models, secrets=secrets, hardware=hw)
            if hasattr(stt, "load"):
                await stt.load()
            await stt.transcribe(phrase[:16_000])  # warm-up
        except Exception as exc:
            rows.append(f"| STT | {provider} | {model_id} | - | ошибка: {exc} | - |")
            continue
        times: list[float] = []
        text = ""
        for _ in range(args.runs):
            elapsed, result = await timed(stt.transcribe(phrase))
            times.append(elapsed)
            text = getattr(result, "text", "")
        rows.append(
            f"| STT | {provider} | {model_id} | {duration_s(phrase):.1f} "
            f"| {statistics.median(times):.2f} | {min(times):.2f} |"
        )
        print(f"{provider}: {text}")
        if close := getattr(stt, "close", None):
            await close()

    print("\n" + "\n".join(rows))


if __name__ == "__main__":
    asyncio.run(main())
