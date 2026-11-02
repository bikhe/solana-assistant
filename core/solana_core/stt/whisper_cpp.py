"""whisper.cpp through its ``whisper-server``: the GPU path for AMD cards (Vulkan) and Macs.

The core starts ``whisper-server`` on a free local port and posts WAV audio to ``/inference``.
The binary comes from ``$SOLANA_WHISPER_SERVER``, ``PATH`` or ``<data dir>/bin``; use a build
with ``-DGGML_VULKAN=1`` on Windows and Linux.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Any

import httpx
import platformdirs

from solana_core.protocol import Language
from solana_core.stt.audio import guess_language, normalize_language, pcm16_to_wav
from solana_core.stt.base import Transcript
from solana_core.stt.streaming import ChunkedStreamingSTT

BINARY = "whisper-server"


class WhisperCppError(RuntimeError):
    pass


def find_whisper_server() -> str | None:
    exe = BINARY + (".exe" if sys.platform == "win32" else "")
    candidates = [
        os.environ.get("SOLANA_WHISPER_SERVER"),
        shutil.which(BINARY),
        str(platformdirs.user_data_path("solana-assistant", appauthor=False) / "bin" / exe),
    ]
    return next((c for c in candidates if c and Path(c).is_file()), None)


class WhisperCppSTT(ChunkedStreamingSTT):
    name = "whisper.cpp"

    def __init__(
        self,
        model_path: Path | str | None = None,
        *,
        binary: str | None = None,
        base_url: str | None = None,
        threads: int | None = None,
        startup_timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Either ``model_path`` (we start the server) or ``base_url`` (already running)."""
        if model_path is None and base_url is None:
            raise ValueError("model_path or base_url is required")
        self.model_path = str(model_path) if model_path else None
        self.binary = binary
        self.base_url = base_url.rstrip("/") if base_url else None
        self.threads = threads or max(1, (os.cpu_count() or 4) // 2)
        self.startup_timeout_s = startup_timeout_s
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._start_lock = asyncio.Lock()

    async def load(self) -> None:
        await self._ensure_started()

    async def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript:
        client = await self._ensure_started()
        response = await client.post(
            "/inference",
            files={"file": ("audio.wav", pcm16_to_wav(audio), "audio/wav")},
            data={
                "response_format": "verbose_json",
                "language": language or "auto",
                "temperature": "0.0",
                "no_timestamps": "true",
            },
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        if "error" in body:
            raise WhisperCppError(str(body["error"]))
        text = str(body.get("text", "")).strip()
        detected = (
            language
            or normalize_language(body.get("detected_language") or body.get("language"))
            or guess_language(text)
        )
        return Transcript(text, detected)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._process.wait(), 5)
            if self._process.returncode is None:
                self._process.kill()
        self._process = None

    async def _ensure_started(self) -> httpx.AsyncClient:
        async with self._start_lock:
            if self._client is not None:
                return self._client
            base_url = self.base_url or await self._spawn()
            client = httpx.AsyncClient(
                base_url=base_url, transport=self._transport, timeout=httpx.Timeout(60.0)
            )
            if self._process is not None:
                await self._wait_ready(client)
            self._client = client
            return client

    async def _spawn(self) -> str:
        binary = self.binary or find_whisper_server()
        if binary is None:
            raise WhisperCppError(
                "whisper-server not found: set SOLANA_WHISPER_SERVER or put it on PATH"
            )
        port = _free_port()
        self._process = await asyncio.create_subprocess_exec(
            binary,
            "--model",
            str(self.model_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--threads",
            str(self.threads),
            "--language",
            "auto",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return f"http://127.0.0.1:{port}"

    async def _wait_ready(self, client: httpx.AsyncClient) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.startup_timeout_s
        while loop.time() < deadline:
            if self._process is not None and self._process.returncode is not None:
                raise WhisperCppError(f"whisper-server exited with {self._process.returncode}")
            with contextlib.suppress(httpx.TransportError):
                await client.get("/")
                return
            await asyncio.sleep(0.2)
        await self.close()
        raise WhisperCppError("whisper-server did not start in time")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port
