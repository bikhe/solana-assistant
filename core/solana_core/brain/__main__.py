"""Talk to the brain from a terminal, for manual checks with real models.

    uv run python -m solana_core.brain --mode local --local-model qwen3:8b
    uv run python -m solana_core.brain --mode cloud --set-key anthropic

Uses your settings file and keyring; flags override settings for this run only.
PC actions are fake: tool calls are printed, nothing happens to the computer.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from typing import Any, ClassVar

from solana_core.brain.base import TextDelta
from solana_core.brain.dialog import Dialog, ToolFinished, ToolStarted, TurnDone
from solana_core.brain.router import PRESETS, BrainRouter
from solana_core.config import ConfigStore, KeyringSecretStore
from solana_core.tools import Tool, ToolContext, ToolRegistry, ToolResult

# The PC tools agreed with WP5, as harmless fakes.
_DEMO_TOOLS: dict[str, tuple[str, dict[str, Any]]] = {
    "pc.volume_set": ("Установить громкость 0..100", {"level": {"type": "integer"}}),
    "pc.volume_change": ("Изменить громкость на delta", {"delta": {"type": "integer"}}),
    "pc.mute": ("Выключить или включить звук", {"muted": {"type": "boolean"}}),
    "pc.media": (
        "Управление медиа",
        {"action": {"type": "string", "enum": ["play_pause", "play", "pause", "next", "previous"]}},
    ),
    "pc.app_open": ("Открыть приложение по названию", {"name": {"type": "string"}}),
    "pc.app_close": ("Закрыть приложение по названию", {"name": {"type": "string"}}),
    "pc.url_open": ("Открыть ссылку в браузере", {"url": {"type": "string"}}),
    "pc.web_search": ("Поиск в интернете", {"query": {"type": "string"}}),
}


class _DemoTool(Tool):
    parameters: ClassVar[dict[str, Any]] = {}

    def __init__(self, name: str, description: str, props: dict[str, Any]) -> None:
        self.name = name  # type: ignore[misc]
        self.description = description  # type: ignore[misc]
        self.parameters = {"type": "object", "properties": props, "required": list(props)}  # type: ignore[misc]

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult("ok")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m solana_core.brain")
    parser.add_argument("--mode", choices=["cloud", "local", "hybrid"])
    parser.add_argument("--cloud-provider")
    parser.add_argument("--cloud-model")
    parser.add_argument("--local-provider")
    parser.add_argument("--local-model")
    parser.add_argument("--local-base-url")
    parser.add_argument("--language", choices=["ru", "en"], default="ru")
    parser.add_argument("--set-key", metavar="PROVIDER", help="save an API key to the keyring")
    args = parser.parse_args()

    secrets = KeyringSecretStore()
    if args.set_key:
        preset = PRESETS.get(args.set_key)
        if preset is None or preset.secret is None:
            sys.exit(f"{args.set_key}: этому провайдеру ключ не нужен")
        secrets.set(preset.secret, getpass.getpass(f"API-ключ {args.set_key}: "))
        print("Ключ сохранён.")

    config = ConfigStore()
    overrides = {
        k: v
        for k, v in {
            "mode": args.mode,
            "cloud_provider": args.cloud_provider,
            "cloud_model": args.cloud_model,
            "local_provider": args.local_provider,
            "local_model": args.local_model,
            "local_base_url": args.local_base_url,
        }.items()
        if v is not None
    }
    brain = config.settings.brain.model_copy(update=overrides)
    router = BrainRouter(lambda: brain, secrets)
    tools = ToolRegistry()
    for name, (description, props) in _DEMO_TOOLS.items():
        tools.register(_DemoTool(name, description, props))

    async def approve(tool: Tool, call: object) -> bool:
        return True

    dialog = Dialog(router, tools, approve=approve)
    print(
        f"mode={brain.mode} cloud={brain.cloud_provider}:{brain.cloud_model} "
        f"local={brain.local_provider}:{brain.local_model}. Пустая строка: выход."
    )
    asyncio.run(_repl(dialog, router, args.language))


async def _repl(dialog: Dialog, router: BrainRouter, language: Any) -> None:
    loop = asyncio.get_running_loop()
    while True:
        text = (await loop.run_in_executor(None, input, "\n> ")).strip()
        if not text:
            return
        started = loop.time()
        first: float | None = None
        async for event in dialog.turn(text, language=language):
            if first is None and not isinstance(event, TurnDone):
                first = loop.time() - started
            if isinstance(event, TextDelta):
                print(event.text, end="", flush=True)
            elif isinstance(event, ToolStarted):
                print(f"\n  [tool] {event.call.name} {event.call.arguments}")
            elif isinstance(event, ToolFinished):
                print(f"  [result] ok={event.result.ok} {event.result.content}")
            elif isinstance(event, TurnDone):
                who = "fast" if event.fast else (router.last.name if router.last else "?")
                total = loop.time() - started
                print(f"\n  ({who}, first event {first or 0:.2f}s, total {total:.2f}s)")


if __name__ == "__main__":
    main()
