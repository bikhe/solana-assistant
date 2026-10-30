"""Build solana-core into one executable and put it where Tauri expects its sidecar.

Run from ``core/``::

    uv run python packaging/build_sidecar.py           # build
    uv run python packaging/build_sidecar.py --smoke   # build, then start it and ping it

Tauri looks for ``app/src-tauri/binaries/solana-core-<target-triple>[.exe]`` (see
``app/src-tauri/tauri.release.conf.json``) and installs it next to the app executable as
``solana-core[.exe]``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import websockets

PYINSTALLER = "pyinstaller==6.22.3"
NAME = "solana-core"
READY_PREFIX = "SOLANA_CORE_READY "

PACKAGING = Path(__file__).resolve().parent
CORE = PACKAGING.parent
ROOT = CORE.parent
BUILD = PACKAGING / "build"
BINARIES = ROOT / "app" / "src-tauri" / "binaries"
EXE = ".exe" if sys.platform == "win32" else ""


def host_triple() -> str:
    """The Rust target triple of this machine, which Tauri appends to sidecar names."""
    if shutil.which("rustc"):
        out = subprocess.run(["rustc", "-vV"], check=True, capture_output=True, text=True).stdout
        for line in out.splitlines():
            if line.startswith("host: "):
                return line.removeprefix("host: ").strip()
    arch = {"amd64": "x86_64", "arm64": "aarch64"}.get(platform.machine().lower())
    arch = arch or platform.machine().lower()
    system = {"win32": "pc-windows-msvc", "darwin": "apple-darwin"}.get(sys.platform)
    return f"{arch}-{system or 'unknown-linux-gnu'}"


def build(triple: str) -> Path:
    cmd = [
        "uv",
        "run",
        "--with",
        PYINSTALLER,
        "pyinstaller",
        str(PACKAGING / "entry.py"),
        "--name",
        NAME,
        "--onefile",
        "--console",  # the app reads stdout; it hides the window itself on Windows
        "--noconfirm",
        "--clean",
        "--log-level",
        "WARN",
        # Providers and tools are looked up by name at runtime; ship every module.
        "--collect-submodules",
        "solana_core",
        "--distpath",
        str(BUILD / "dist"),
        "--workpath",
        str(BUILD / "work"),
        "--specpath",
        str(BUILD),
    ]
    subprocess.run(cmd, check=True, cwd=CORE)
    BINARIES.mkdir(parents=True, exist_ok=True)
    target = BINARIES / f"{NAME}-{triple}{EXE}"
    shutil.copy2(BUILD / "dist" / f"{NAME}{EXE}", target)
    return target


async def _ping(port: int, token: str) -> dict[str, object]:
    async with websockets.connect(f"ws://127.0.0.1:{port}/?token={token}") as ws:
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}))
        while True:  # skip events such as the initial ``state``
            reply: dict[str, object] = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if reply.get("id") == 1:
                return reply


def smoke(binary: Path, timeout: float = 120.0) -> None:
    """Start the binary in fake mode, wait for the ready line and ping it over WebSocket."""
    started = time.monotonic()
    proc = subprocess.Popen(
        [str(binary), "--fake", "--port", "0", "--token", "smoke"],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.startswith(READY_PREFIX):
                info = json.loads(line.removeprefix(READY_PREFIX))
                break
            if time.monotonic() - started > timeout:
                raise TimeoutError("no ready line")
        else:
            raise RuntimeError(f"{binary.name} exited with {proc.wait()} before it was ready")
        ready_after = time.monotonic() - started
        reply = asyncio.run(_ping(info["port"], info["token"]))
        result = reply.get("result")
        if not isinstance(result, dict) or result.get("pong") is not True:
            raise RuntimeError(f"unexpected ping reply: {reply}")
        print(f"smoke ok: ready in {ready_after:.1f}s, core {result.get('version')}")
    finally:
        if sys.platform == "win32":  # the one-file bootloader runs the core in a child process
            subprocess.run(["taskkill", "/pid", str(proc.pid), "/t", "/f"], capture_output=True)
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", help="Rust target triple (default: rustc host)")
    parser.add_argument("--smoke", action="store_true", help="run the built binary and ping it")
    parser.add_argument("--smoke-only", action="store_true", help="skip the build")
    args = parser.parse_args()

    triple = args.target or host_triple()
    binary = BINARIES / f"{NAME}-{triple}{EXE}"
    if not args.smoke_only:
        binary = build(triple)
        size = binary.stat().st_size / 2**20
        print(f"built {binary.relative_to(ROOT)} ({size:.1f} MB)")
    if args.smoke or args.smoke_only:
        smoke(binary)


if __name__ == "__main__":
    main()
