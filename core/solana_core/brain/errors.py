"""Errors raised by LLM providers."""

from __future__ import annotations


class LLMError(Exception):
    """The provider failed. ``unreachable`` means nothing was received at all (no network,
    server down, bad URL), so the router may retry the turn on another provider."""

    def __init__(self, message: str, *, unreachable: bool = False, status: int | None = None):
        super().__init__(message)
        self.unreachable = unreachable
        self.status = status
