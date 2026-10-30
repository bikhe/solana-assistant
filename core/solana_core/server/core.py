"""Shared runtime state of the core: settings, tools, assistant state and confirmations."""

from __future__ import annotations

import asyncio
import uuid

from solana_core.brain.base import LLMProvider
from solana_core.config import ConfigStore, SecretStore
from solana_core.protocol import AssistantState, Risk
from solana_core.protocol.generated import (
    ConfirmRequestEvent,
    StateEvent,
)
from solana_core.server.events import EventBus
from solana_core.tools import ToolRegistry


class Core:
    def __init__(
        self,
        config: ConfigStore,
        secrets: SecretStore,
        *,
        tools: ToolRegistry | None = None,
        llm: LLMProvider | None = None,
        fake: bool = False,
    ) -> None:
        self.config = config
        self.secrets = secrets
        self.tools = tools or ToolRegistry()
        self.llm = llm  # set by WP3; None means chat is not available yet
        self.fake = fake
        self.bus = EventBus()
        self.state: AssistantState = "idle"
        self.turn_lock = asyncio.Lock()  # one voice or chat turn at a time
        self._confirmations: dict[str, asyncio.Future[bool]] = {}

    @property
    def muted(self) -> bool:
        return self.state == "muted"

    def state_event(self) -> StateEvent:
        return StateEvent(state=self.state)

    def set_state(self, state: AssistantState, reason: str | None = None) -> None:
        if state == self.state:
            return
        previous, self.state = self.state, state
        self.bus.emit("state", StateEvent(state=state, previous=previous, reason=reason))

    async def confirm(
        self,
        tool: str,
        risk: Risk,
        title: str,
        arguments: dict[str, object],
        *,
        details: str | None = None,
        timeout_s: float = 30.0,
    ) -> bool:
        """Ask the app to confirm a tool call. Returns False on refusal or timeout."""
        request_id = uuid.uuid4().hex
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._confirmations[request_id] = future
        self.bus.emit(
            "confirm.request",
            ConfirmRequestEvent(
                request_id=request_id,
                tool=tool,
                risk=risk,
                title=title,
                details=details,
                arguments=arguments,
                voice_allowed=risk != "dangerous",
                timeout_s=timeout_s,
            ),
        )
        try:
            return await asyncio.wait_for(future, timeout_s)
        except TimeoutError:
            return False
        finally:
            self._confirmations.pop(request_id, None)

    def resolve_confirmation(self, request_id: str, approved: bool) -> bool:
        """Deliver the user's answer. False if the request is unknown or already answered."""
        future = self._confirmations.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(approved)
        return True
