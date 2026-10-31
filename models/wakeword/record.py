"""Record your own examples from the microphone, one phrase per WAV file."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from solana_core.audio.base import FRAME_MS
from solana_core.audio.mic import SoundDeviceSource, list_input_devices
from solana_core.audio.wav import write_wav

PROMPTS = {
    "positive": "Скажите «Эй, Солана»",
    "negative": "Скажите любую фразу без «Эй, Солана»",
}


async def record_one(source: SoundDeviceSource, seconds: float) -> bytes:
    frames: list[bytes] = []
    async for frame in source.frames():
        frames.append(frame)
        if len(frames) * FRAME_MS >= seconds * 1000:
            break
    return b"".join(frames)


async def run(args: argparse.Namespace) -> None:
    args.out.mkdir(parents=True, exist_ok=True)
    start = len(list(args.out.glob("*.wav")))
    source = SoundDeviceSource(args.device)
    for i in range(start, start + args.count):
        await asyncio.to_thread(
            input, f"[{i + 1 - start}/{args.count}] {PROMPTS[args.kind]}: нажмите Enter и говорите"
        )
        await source.start()
        audio = await record_one(source, args.seconds)
        await source.stop()
        import numpy as np

        write_wav(args.out / f"{args.kind}_{i:03d}.wav", np.frombuffer(audio, dtype=np.int16))
    print(f"Готово: {args.out}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wakeword record", description=__doc__)
    parser.add_argument("out", type=Path, nargs="?", help="folder for the WAV files")
    parser.add_argument("--kind", choices=sorted(PROMPTS), default="positive")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seconds", type=float, default=2.5)
    parser.add_argument("--device", help="input device name (see --list)")
    parser.add_argument("--list", action="store_true", help="show input devices and exit")
    args = parser.parse_args(argv)
    if args.list:
        for d in list_input_devices():
            print(("* " if d.is_default else "  ") + d.name)
        return
    if args.out is None:
        parser.error("укажите папку для записей")
    asyncio.run(run(args))
