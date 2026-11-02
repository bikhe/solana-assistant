"""Model downloads: progress, resume, hash checks and hardware-based choice."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import httpx
import pytest

from solana_core.models import (
    Hardware,
    HashMismatchError,
    ModelError,
    ModelFile,
    ModelManager,
    ModelSpec,
    Progress,
    recommend_stt,
)
from solana_core.models.hardware import default_stt_model
from solana_core.protocol.generated import DownloadProgressEvent

WEIGHTS = bytes(range(256)) * 4096  # 1 MiB
CONFIG = b'{"a": 1}'
SHA = hashlib.sha256(WEIGHTS).hexdigest()


def spec(sha256: str | None = None) -> ModelSpec:
    return ModelSpec(
        "test-model",
        "stt",
        "Test",
        "faster-whisper",
        (
            ModelFile("https://hf.test/config.json", "config.json", 10),
            ModelFile("https://hf.test/model.bin", "model.bin", 1_000, sha256),
        ),
        ("ru",),
        "MIT",
    )


class Server:
    """Serves WEIGHTS like Hugging Face: a redirect carrying X-Linked-Etag, Range support."""

    def __init__(self, etag: str = SHA, body: bytes = WEIGHTS) -> None:
        self.etag = etag
        self.body = body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/config.json":
            return httpx.Response(200, content=CONFIG, headers={"ETag": '"abc123"'})
        if request.url.host == "hf.test":
            return httpx.Response(
                302,
                headers={"Location": "https://cdn.test/blob", "X-Linked-Etag": f'"{self.etag}"'},
            )
        start = 0
        if rng := request.headers.get("Range"):
            start = int(rng.removeprefix("bytes=").rstrip("-"))
            if start >= len(self.body):
                return httpx.Response(416)
            return httpx.Response(206, content=self.body[start:])
        return httpx.Response(200, content=self.body)


def manager(tmp_path: Path, server: Server, sha256: str | None = None) -> ModelManager:
    s = spec(sha256)
    return ModelManager(
        tmp_path, {s.id: s}, transport=httpx.MockTransport(server), progress_interval_s=0
    )


async def test_download_reports_progress_and_installs(tmp_path: Path) -> None:
    mm = manager(tmp_path, Server())
    assert [m.installed for m in mm.infos()] == [False]
    events: list[Progress] = []
    folder = await mm.download("test-model", events.append)

    assert (folder / "model.bin").read_bytes() == WEIGHTS
    assert mm.is_installed("test-model") and mm.verify("test-model")
    assert [m.installed for m in mm.infos()] == [True]
    assert events[-1].done and events[-1].downloaded_bytes == len(WEIGHTS) + len(CONFIG)
    sizes = [e.downloaded_bytes for e in events]
    assert sizes == sorted(sizes)
    assert not list(folder.glob("*.part"))


async def test_installed_model_is_not_downloaded_again(tmp_path: Path) -> None:
    server = Server()
    mm = manager(tmp_path, server)
    await mm.download("test-model")
    count = len(server.requests)
    await mm.download("test-model")
    assert len(server.requests) == count


async def test_hash_mismatch_rejects_file(tmp_path: Path) -> None:
    mm = manager(tmp_path, Server(etag="0" * 64))
    with pytest.raises(HashMismatchError):
        await mm.download("test-model")
    assert not mm.is_installed("test-model")
    assert not (mm.path("test-model") / "model.bin").exists()


async def test_pinned_hash_wins_over_server(tmp_path: Path) -> None:
    mm = manager(tmp_path, Server(etag="f" * 64), sha256=SHA)
    await mm.download("test-model")
    assert mm.is_installed("test-model")


async def test_resume_from_partial_file(tmp_path: Path) -> None:
    server = Server()
    mm = manager(tmp_path, server)
    folder = mm.path("test-model")
    folder.mkdir(parents=True)
    (folder / "model.bin.part").write_bytes(WEIGHTS[:1000])
    await mm.download("test-model")
    assert (folder / "model.bin").read_bytes() == WEIGHTS
    assert any(r.headers.get("Range") == "bytes=1000-" for r in server.requests)


async def test_verify_detects_corruption(tmp_path: Path) -> None:
    mm = manager(tmp_path, Server())
    folder = await mm.download("test-model")
    (folder / "model.bin").write_bytes(b"broken")
    assert not mm.verify("test-model")
    assert mm.remove("test-model") and not mm.is_installed("test-model")


async def test_concurrent_downloads_share_one_transfer(tmp_path: Path) -> None:
    server = Server()
    mm = manager(tmp_path, server)
    await asyncio.gather(mm.download("test-model"), mm.download("test-model"))
    assert sum(r.url.path == "/blob" for r in server.requests) == 1


async def test_start_download_emits_protocol_events(tmp_path: Path) -> None:
    mm = manager(tmp_path, Server(etag="0" * 64))
    events: list[DownloadProgressEvent] = []
    download_id, task = await mm.start_download("test-model", events.append)
    await task
    assert all(e.download_id == download_id for e in events)
    assert events[-1].done and events[-1].error and "sha256" in events[-1].error

    with pytest.raises(ModelError):
        await mm.start_download("nope", events.append)


def test_unknown_and_missing_models(tmp_path: Path) -> None:
    mm = manager(tmp_path, Server())
    with pytest.raises(ModelError):
        mm.spec("nope")
    with pytest.raises(ModelError, match="не скачана"):
        mm.require("test-model")


def test_catalog_is_consistent() -> None:
    mm = ModelManager(Path("unused"))
    infos = mm.infos()
    assert {m.kind for m in infos} == {"stt", "tts"}
    for model in mm.catalog.values():
        assert model.files and all(f.url.startswith("https://") for f in model.files)
        assert len({f.path for f in model.files}) == len(model.files)


@pytest.mark.parametrize(
    ("hw", "whisper_cpp", "expected"),
    [
        (Hardware(8, 16, cuda=True), False, ("faster-whisper", "cuda")),
        # Reference machine: RX 6600 through Vulkan once whisper-server is installed.
        (Hardware(12, 32, vulkan=True), True, ("whisper.cpp", "vulkan")),
        (Hardware(12, 32, vulkan=True), False, ("faster-whisper", "cpu")),
        (Hardware(8, 16, metal=True), True, ("whisper.cpp", "metal")),
        (Hardware(2, 3), False, ("faster-whisper", "cpu")),
    ],
)
def test_recommend_stt(hw: Hardware, whisper_cpp: bool, expected: tuple[str, str]) -> None:
    choice = recommend_stt(hw, whisper_cpp_available=whisper_cpp)
    assert (choice.stt_provider, choice.device) == expected
    assert ModelManager(Path("unused")).spec(choice.stt_model).engine == choice.stt_provider


def test_default_stt_model() -> None:
    weak, strong = Hardware(2, 3), Hardware(12, 32, vulkan=True)
    assert default_stt_model("faster-whisper", weak) == "faster-whisper-base"
    assert default_stt_model("faster-whisper", strong) == "faster-whisper-small"
    assert default_stt_model("whisper.cpp", strong) == "whisper-cpp-large-v3-turbo"
    assert default_stt_model("gigaam", weak) == "gigaam-v3-ctc"


async def test_rpc_models_methods_use_the_manager(tmp_path: Path) -> None:
    import json

    from solana_core.config import ConfigStore, MemorySecretStore
    from solana_core.server.core import Core
    from solana_core.server.handlers import build_dispatcher

    core = Core(ConfigStore(tmp_path / "config.toml"), MemorySecretStore())
    events = core.bus.subscribe()
    rpc = build_dispatcher(core, manager(tmp_path, Server()))

    listed = await rpc.handle({"jsonrpc": "2.0", "id": 1, "method": "models.list"})
    assert listed is not None and listed["result"]["models"][0]["id"] == "test-model"
    reply = await rpc.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "models.download",
            "params": {"model_id": "test-model"},
        }
    )
    assert reply is not None
    download_id = reply["result"]["download_id"]
    while True:
        event = json.loads(await asyncio.wait_for(events.get(), 2))
        if event["method"] == "download.progress" and event["params"]["done"]:
            break
    assert event["params"]["download_id"] == download_id and "error" not in event["params"]
    missing = await rpc.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "models.download", "params": {"model_id": "nope"}}
    )
    assert missing is not None and missing["error"]["code"] == -32002
