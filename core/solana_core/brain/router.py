"""Chooses the cloud or local model for each turn, from the current settings.

Modes: ``cloud`` and ``local`` use one side, falling back to the other if it is unreachable;
``hybrid`` sends simple commands to the local model and the rest to the cloud. Without
network everything goes local. Settings and keys are re-read on every turn, so switching
provider or model needs no restart.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass

from solana_core.brain import fast
from solana_core.brain.anthropic import AnthropicProvider
from solana_core.brain.base import LLMEvent, LLMProvider, Message, ToolSpec
from solana_core.brain.errors import LLMError
from solana_core.brain.openai_compat import OpenAICompatProvider
from solana_core.config import SecretStore
from solana_core.config.models import BrainSettings

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    base_url: str | None
    secret: str | None  # keyring entry with the API key
    env: str | None = None  # environment variable fallback for the key


# ``cloud_provider`` / ``local_provider`` values in settings.
PRESETS: dict[str, ProviderPreset] = {
    "anthropic": ProviderPreset(None, "anthropic_api_key", "ANTHROPIC_API_KEY"),
    "openai": ProviderPreset("https://api.openai.com/v1", "openai_api_key", "OPENAI_API_KEY"),
    "openrouter": ProviderPreset(
        "https://openrouter.ai/api/v1", "openrouter_api_key", "OPENROUTER_API_KEY"
    ),
    "openai-compatible": ProviderPreset(None, "openai_compatible_api_key"),
    "ollama": ProviderPreset("http://127.0.0.1:11434/v1", None),
    "lmstudio": ProviderPreset("http://127.0.0.1:1234/v1", None),
    "llamacpp": ProviderPreset("http://127.0.0.1:8080/v1", None),
}


def api_key(provider: str, secrets: SecretStore) -> str | None:
    preset = PRESETS.get(provider)
    if preset is None or preset.secret is None:
        return None
    return secrets.get(preset.secret) or (os.environ.get(preset.env) if preset.env else None)


def make_provider(
    provider: str, model: str, base_url: str | None, key: str | None, *, local: bool
) -> LLMProvider:
    preset = PRESETS.get(provider, PRESETS["openai-compatible"])
    if provider == "anthropic":
        return AnthropicProvider(key, model, base_url=base_url)
    url = base_url or preset.base_url
    if not url:
        raise LLMError(f"{provider}: base URL is not set")
    return OpenAICompatProvider(provider, url, model, api_key=key, local=local)


# (provider, model, base_url, api_key, local) -> provider
ProviderFactory = Callable[[str, str, str | None, str | None, bool], LLMProvider]


def _default_factory(
    provider: str, model: str, url: str | None, key: str | None, local: bool
) -> LLMProvider:
    return make_provider(provider, model, url, key, local=local)


# Requests that want a smart model even when short.
_COMPLEX = re.compile(
    r"почему|зачем|объясни|расскажи|напиши|сочини|придумай|переведи|сравни|посоветуй|"
    r"проанализируй|составь|план|код|програм|why|explain|tell me|write|compose|translate|"
    r"compare|recommend|analy[sz]e|plan|code",
)
SIMPLE_MAX_WORDS = 6


def is_simple(text: str) -> bool:
    """Hybrid mode: can the small local model handle this phrase well enough?"""
    if fast.parse(text):
        return True
    phrase = fast.normalize(text)
    return len(phrase.split()) <= SIMPLE_MAX_WORDS and not _COMPLEX.search(phrase)


class BrainRouter(LLMProvider):
    name = "router"

    def __init__(
        self,
        settings: Callable[[], BrainSettings],
        secrets: SecretStore,
        *,
        factory: ProviderFactory | None = None,
    ) -> None:
        self._settings = settings
        self._secrets = secrets
        self._factory = factory or _default_factory
        # One provider per side; rebuilt when its settings or key change.
        self._built: dict[bool, tuple[tuple[str, str, str | None, str | None], LLMProvider]] = {}
        self.last: LLMProvider | None = None  # provider that answered the last turn

    @property
    def local(self) -> bool:  # type: ignore[override]
        return self._settings().mode == "local"

    def _provider(self, provider: str, model: str, url: str | None, local: bool) -> LLMProvider:
        spec = (provider, model, url, api_key(provider, self._secrets))
        built = self._built.get(local)
        if built is None or built[0] != spec:
            built = self._built[local] = (spec, self._factory(*spec, local))
        return built[1]

    def cloud(self) -> LLMProvider:
        s = self._settings()
        return self._provider(s.cloud_provider, s.cloud_model, s.cloud_base_url, False)

    def local_provider(self) -> LLMProvider:
        s = self._settings()
        return self._provider(s.local_provider, s.local_model, s.local_base_url, True)

    async def candidates(self, messages: Sequence[Message]) -> list[LLMProvider]:
        """Providers to try for this turn, best first."""
        s = self._settings()
        cloud, local = self.cloud(), self.local_provider()
        if s.mode == "local":
            order = [local, cloud]
        elif s.mode == "cloud":
            order = [cloud, local]
        else:
            last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
            order = [local, cloud] if is_simple(last_user) else [cloud, local]
        # A cloud provider without a key is skipped right away; local ones are just tried.
        return [p for p in order if p.local or await p.available()]

    async def available(self) -> bool:
        return bool(await self.candidates([]))

    async def stream(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[LLMEvent]:
        candidates = await self.candidates(messages)
        if not candidates:
            raise LLMError("no LLM provider is configured")
        for i, provider in enumerate(candidates):
            started = False
            try:
                async for event in provider.stream(messages, tools):
                    started = True
                    self.last = provider
                    yield event
                return
            except LLMError as exc:
                if started or not exc.unreachable or i == len(candidates) - 1:
                    raise
                log.warning(
                    "%s unreachable (%s), trying %s", provider.name, exc, candidates[i + 1].name
                )
