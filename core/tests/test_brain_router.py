from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import pytest

from solana_core.brain.anthropic import AnthropicProvider
from solana_core.brain.base import (
    Done,
    FakeLLM,
    LLMEvent,
    LLMProvider,
    Message,
    TextDelta,
    ToolSpec,
)
from solana_core.brain.errors import LLMError
from solana_core.brain.openai_compat import OpenAICompatProvider
from solana_core.brain.router import BrainRouter, api_key, is_simple, make_provider
from solana_core.config import MemorySecretStore
from solana_core.config.models import BrainSettings


class Named(FakeLLM):
    def __init__(self, name: str, local: bool, *, key: bool = True) -> None:
        super().__init__()
        self.name = name
        self.local = local
        self.key = key

    async def available(self) -> bool:
        return self.key

    async def stream(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[LLMEvent]:
        self.calls.append(list(messages))
        yield TextDelta(self.name)
        yield Done()


class Down(Named):
    async def stream(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[LLMEvent]:
        self.calls.append(list(messages))
        raise LLMError("connection refused", unreachable=True)
        yield TextDelta("")  # pragma: no cover


class Setup:
    def __init__(self, mode: str = "hybrid", cloud_down: bool = False, cloud_key: bool = True):
        self.settings = BrainSettings(mode=mode)
        self.built: list[tuple[str, str, bool]] = []
        self.cloud_down = cloud_down
        self.cloud_key = cloud_key
        self.router = BrainRouter(lambda: self.settings, MemorySecretStore(), factory=self.factory)

    def factory(
        self, provider: str, model: str, url: str | None, key: str | None, local: bool
    ) -> LLMProvider:
        self.built.append((provider, model, local))
        if local:
            return Named(f"local:{model}", True)
        cls = Down if self.cloud_down else Named
        return cls(f"cloud:{model}", False, key=self.cloud_key)

    async def ask(self, text: str) -> str:
        events = [e async for e in self.router.stream([Message("user", text)])]
        return "".join(e.text for e in events if isinstance(e, TextDelta))


@pytest.mark.parametrize(
    ("mode", "text", "expected"),
    [
        ("cloud", "громче", "cloud:claude-sonnet-5-5"),
        ("local", "объясни теорию относительности", "local:qwen3:8b"),
        ("hybrid", "громче", "local:qwen3:8b"),
        ("hybrid", "который час", "local:qwen3:8b"),
        ("hybrid", "объясни теорию относительности простыми словами", "cloud:claude-sonnet-5-5"),
    ],
)
async def test_modes(mode: str, text: str, expected: str) -> None:
    assert await Setup(mode).ask(text) == expected


async def test_offline_falls_back_to_local() -> None:
    setup = Setup("cloud", cloud_down=True)
    assert await setup.ask("напиши стихотворение про осень") == "local:qwen3:8b"
    assert setup.router.last is not None and setup.router.last.local


async def test_no_cloud_key_skips_cloud() -> None:
    setup = Setup("hybrid", cloud_key=False)
    assert await setup.ask("объясни, почему небо голубое") == "local:qwen3:8b"


async def test_settings_switch_without_restart() -> None:
    setup = Setup("cloud")
    assert await setup.ask("привет") == "cloud:claude-sonnet-5-5"
    assert await setup.ask("привет") == "cloud:claude-sonnet-5-5"
    builds = len(setup.built)
    setup.settings = BrainSettings(mode="cloud", cloud_model="claude-opus-5-5")
    assert await setup.ask("привет") == "cloud:claude-opus-5-5"
    assert len(setup.built) == builds + 1  # only the changed side is rebuilt
    setup.settings = BrainSettings(mode="local", local_model="gemma3:4b")
    assert await setup.ask("привет") == "local:gemma3:4b"


async def test_hybrid_keeps_provider_for_tool_steps() -> None:
    setup = Setup("hybrid")
    from solana_core.brain.base import ToolCall

    messages = [
        Message("user", "объясни, что сейчас играет и почему это хорошая музыка"),
        Message("assistant", "", (ToolCall("1", "pc.now_playing", {}),)),
        Message("tool", "Queen — Bohemian Rhapsody", tool_call_id="1"),
    ]
    events = [e async for e in setup.router.stream(messages)]
    assert events[0] == TextDelta("cloud:claude-sonnet-5-5")


def test_is_simple() -> None:
    assert is_simple("пауза")
    assert is_simple("сколько времени")
    assert not is_simple("переведи на английский фразу доброе утро")
    assert not is_simple("что лучше посмотреть вечером если я люблю фантастику и детективы")


def test_make_provider_presets(monkeypatch: pytest.MonkeyPatch) -> None:
    secrets = MemorySecretStore()
    secrets.set("anthropic_api_key", "from-keyring")
    assert api_key("anthropic", secrets) == "from-keyring"
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    assert api_key("openrouter", secrets) == "from-env"
    assert api_key("ollama", secrets) is None

    claude = make_provider("anthropic", "claude-sonnet-5-5", None, "k", local=False)
    assert isinstance(claude, AnthropicProvider)
    ollama = make_provider("ollama", "qwen3:8b", None, None, local=True)
    assert isinstance(ollama, OpenAICompatProvider) and ollama.local
    assert ollama.base_url == "http://127.0.0.1:11434/v1"
    lms = make_provider("lmstudio", "x", None, None, local=True)
    assert isinstance(lms, OpenAICompatProvider) and lms.base_url == "http://127.0.0.1:1234/v1"
    with pytest.raises(LLMError):
        make_provider("openai-compatible", "x", None, None, local=False)


async def test_lmstudio_uses_its_own_default_url() -> None:
    setup = Setup("local")
    setup.settings = BrainSettings(mode="local", local_provider="lmstudio")
    built: list[str | None] = []
    setup.router._factory = lambda p, m, url, k, local: built.append(url) or Named("x", True)  # type: ignore[func-returns-value]
    setup.router.local_provider()
    assert built == [None]


def test_broken_keyring_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    class NoKeyring(MemorySecretStore):
        def get(self, key: str) -> str | None:
            raise RuntimeError("No recommended backend was available")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    assert api_key("anthropic", NoKeyring()) == "env-key"
