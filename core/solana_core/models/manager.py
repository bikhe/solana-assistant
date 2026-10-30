"""Downloads model weights into the user data folder, with progress, resume and hash checks.

Layout: ``<root>/<model id>/<file>`` plus ``manifest.json`` written after every file of the
model passed its check. A model counts as installed only when its manifest exists.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx
import platformdirs

from solana_core.models.catalog import CATALOG, ModelFile, ModelSpec
from solana_core.protocol.generated import DownloadProgressEvent, ModelInfo

log = logging.getLogger(__name__)

MANIFEST = "manifest.json"
_CHUNK = 1 << 20
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def default_models_dir() -> Path:
    return platformdirs.user_data_path("solana-assistant", appauthor=False) / "models"


class ModelError(Exception):
    """A model is unknown, not installed, or failed to download."""


class HashMismatchError(ModelError):
    pass


@dataclass(frozen=True, slots=True)
class Progress:
    model_id: str
    downloaded_bytes: int
    total_bytes: int | None
    done: bool = False
    error: str | None = None


ProgressCallback = Callable[[Progress], None]


class ModelManager:
    def __init__(
        self,
        root: Path | None = None,
        catalog: Mapping[str, ModelSpec] = CATALOG,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        progress_interval_s: float = 0.25,
    ) -> None:
        self.root = root or default_models_dir()
        self.catalog = catalog
        self._transport = transport
        self._progress_interval_s = progress_interval_s
        self._downloads: dict[str, asyncio.Task[Path]] = {}

    def spec(self, model_id: str) -> ModelSpec:
        try:
            return self.catalog[model_id]
        except KeyError:
            raise ModelError(f"Unknown model: {model_id}") from None

    def path(self, model_id: str) -> Path:
        return self.root / self.spec(model_id).id

    def is_installed(self, model_id: str) -> bool:
        return (self.path(model_id) / MANIFEST).is_file()

    def require(self, model_id: str) -> Path:
        """Folder of an installed model, or ``ModelError`` asking to download it first."""
        if not self.is_installed(model_id):
            raise ModelError(f"Model is not downloaded: {model_id}")
        return self.path(model_id)

    def infos(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id=spec.id,
                kind=spec.kind,
                name=spec.name,
                size_bytes=spec.size_bytes,
                installed=self.is_installed(spec.id),
            )
            for spec in self.catalog.values()
        ]

    def remove(self, model_id: str) -> bool:
        folder = self.path(model_id)
        if not folder.exists():
            return False
        shutil.rmtree(folder)
        return True

    def verify(self, model_id: str) -> bool:
        """Recompute the hash of every file against the manifest."""
        folder = self.path(model_id)
        try:
            manifest = json.loads((folder / MANIFEST).read_text("utf-8"))
        except (OSError, ValueError):
            return False
        hashes: dict[str, str] = manifest.get("sha256", {})
        return all(
            (folder / name).is_file() and _file_sha256(folder / name) == digest
            for name, digest in hashes.items()
        )

    async def download(self, model_id: str, on_progress: ProgressCallback | None = None) -> Path:
        """Download a model unless it is installed. Concurrent calls share one download."""
        spec = self.spec(model_id)
        if self.is_installed(model_id):
            if on_progress:
                on_progress(Progress(model_id, spec.size_bytes, spec.size_bytes, done=True))
            return self.path(model_id)
        task = self._downloads.get(model_id)
        if task is None:
            task = asyncio.create_task(self._download(spec, on_progress))
            self._downloads[model_id] = task
            task.add_done_callback(lambda _: self._downloads.pop(model_id, None))
        return await asyncio.shield(task)

    async def _download(self, spec: ModelSpec, on_progress: ProgressCallback | None) -> Path:
        folder = self.root / spec.id
        folder.mkdir(parents=True, exist_ok=True)
        total = spec.size_bytes
        done_bytes = 0
        last_report = 0.0

        def report(current: int, *, force: bool = False) -> None:
            nonlocal last_report
            now = time.monotonic()
            if on_progress and (force or now - last_report >= self._progress_interval_s):
                last_report = now
                on_progress(Progress(spec.id, current, max(total, current)))

        hashes: dict[str, str] = {}
        async with httpx.AsyncClient(
            transport=self._transport, follow_redirects=True, timeout=httpx.Timeout(30.0)
        ) as client:
            for file in spec.files:
                base = done_bytes

                def on_file_bytes(
                    n: int, size: int | None, file: ModelFile = file, base: int = base
                ) -> None:
                    nonlocal total
                    if size is not None and size != file.size:
                        total += size - file.size
                    report(base + n)

                hashes[file.path] = await self._fetch(client, file, folder, on_file_bytes)
                done_bytes = base + (folder / file.path).stat().st_size
                report(done_bytes, force=True)

        manifest = {"id": spec.id, "engine": spec.engine, "sha256": hashes}
        (folder / MANIFEST).write_text(json.dumps(manifest, indent=2), "utf-8")
        if on_progress:
            on_progress(Progress(spec.id, done_bytes, done_bytes, done=True))
        log.info("model %s installed in %s", spec.id, folder)
        return folder

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        file: ModelFile,
        folder: Path,
        on_bytes: Callable[[int, int | None], None],
    ) -> str:
        target = folder / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        digest = hashlib.sha256()
        have = part.stat().st_size if part.exists() else 0
        if have:
            digest = await asyncio.to_thread(_hash_file, part)
        headers = {"Range": f"bytes={have}-"} if have else {}

        async with client.stream("GET", file.url, headers=headers) as response:
            if have and response.status_code == 200:  # server ignored Range: start over
                have, digest = 0, hashlib.sha256()
                part.unlink()
            elif response.status_code == 416:  # the .part already holds the whole file
                await response.aread()
            else:
                response.raise_for_status()
            expected = file.sha256 or _server_sha256(response)
            length = response.headers.get("Content-Length")
            size = have + int(length) if length and response.status_code != 416 else None
            if response.status_code != 416:
                with part.open("ab") as out:
                    received = have
                    async for chunk in response.aiter_bytes(_CHUNK):
                        out.write(chunk)
                        digest.update(chunk)
                        received += len(chunk)
                        on_bytes(received, size)

        actual = digest.hexdigest()
        if expected and actual != expected:
            part.unlink(missing_ok=True)
            raise HashMismatchError(f"{file.path}: sha256 {actual} != {expected}")
        part.replace(target)
        return actual

    async def start_download(
        self, model_id: str, emit: Callable[[DownloadProgressEvent], None]
    ) -> tuple[str, asyncio.Task[None]]:
        """Run a download in the background, reporting ``download.progress`` events."""
        self.spec(model_id)
        download_id = uuid.uuid4().hex

        def forward(p: Progress) -> None:
            emit(
                DownloadProgressEvent(
                    download_id=download_id,
                    model_id=p.model_id,
                    downloaded_bytes=p.downloaded_bytes,
                    total_bytes=p.total_bytes,
                    done=p.done,
                    error=p.error,
                )
            )

        async def run() -> None:
            try:
                await self.download(model_id, forward)
            except Exception as exc:
                log.warning("download of %s failed: %s", model_id, exc)
                forward(
                    Progress(model_id, 0, None, done=True, error=str(exc) or type(exc).__name__)
                )

        return download_id, asyncio.create_task(run())


def _server_sha256(response: httpx.Response) -> str | None:
    """SHA-256 of an LFS file as Hugging Face reports it, if any response carried one."""
    for r in (*response.history, response):
        for header in ("x-linked-etag", "etag"):
            value = str(r.headers.get(header, "")).removeprefix("W/").strip('"').lower()
            if _SHA256.match(value):
                return value
    return None


def _hash_file(path: Path) -> hashlib._Hash:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(_CHUNK):
            digest.update(block)
    return digest


def _file_sha256(path: Path) -> str:
    return _hash_file(path).hexdigest()
