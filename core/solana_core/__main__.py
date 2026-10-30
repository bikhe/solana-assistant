"""``solana-core`` command line entry point.

After the server is listening the core prints one line to stdout:
``SOLANA_CORE_READY {"port": <port>, "token": "<token>"}``. The app reads it to connect.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import secrets
import signal
import sys
import tempfile
from pathlib import Path

from solana_core import __version__
from solana_core.brain.base import FakeLLM
from solana_core.brain.router import BrainRouter
from solana_core.config import ConfigStore, KeyringSecretStore, MemorySecretStore
from solana_core.fake.scenario import FakeScenario
from solana_core.server.core import Core
from solana_core.server.handlers import build_dispatcher
from solana_core.server.ws import CoreServer
from solana_core.tools.base import FakeTool

READY_PREFIX = "SOLANA_CORE_READY "


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="solana-core", description="Solana assistant core")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument(
        "--token",
        default=os.environ.get("SOLANA_TOKEN"),
        help="auth token for the app (default: $SOLANA_TOKEN or random)",
    )
    parser.add_argument("--fake", action="store_true", help="play scripted demo events")
    parser.add_argument(
        "--fake-speed", type=float, default=1.0, help="speed up the --fake scenario"
    )
    parser.add_argument("--config", type=Path, help="settings file (default: user config dir)")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--version", action="version", version=f"solana-core {__version__}")
    return parser.parse_args(argv)


def build_core(args: argparse.Namespace) -> Core:
    if not args.fake:
        config, secrets_store = ConfigStore(args.config), KeyringSecretStore()
        llm = BrainRouter(lambda: config.settings.brain, secrets_store)
        return Core(config, secrets_store, llm=llm)
    # Fake mode never touches the real settings file or keyring.
    config_path = args.config or Path(tempfile.gettempdir()) / "solana-fake-config.toml"
    core = Core(ConfigStore(config_path), MemorySecretStore(), llm=FakeLLM(), fake=True)
    core.tools.register(FakeTool())
    return core


async def run(args: argparse.Namespace) -> None:
    core = build_core(args)
    server = CoreServer(core, build_dispatcher(core), args.token or secrets.token_urlsafe(24))
    await server.start(args.host, args.port)
    ready = json.dumps({"port": server.port, "token": server.token})
    print(READY_PREFIX + ready, flush=True)
    logging.getLogger(__name__).info(
        "solana-core %s listening on %s:%s%s",
        __version__,
        args.host,
        server.port,
        " (fake)" if args.fake else "",
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, stop.set)

    tasks: list[asyncio.Task[object]] = [asyncio.create_task(stop.wait())]
    if args.fake:
        tasks.append(asyncio.create_task(FakeScenario(core, args.fake_speed).run()))
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await server.close()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
