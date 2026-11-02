"""Scripted command runner for backend tests: no real programs are started."""

from __future__ import annotations

from collections.abc import Sequence

from solana_core.pc.common import CommandResult


class FakeRunner:
    def __init__(self, replies: dict[str, CommandResult | str] | None = None) -> None:
        self.replies = replies or {}
        self.calls: list[tuple[list[str], str | None]] = []

    async def __call__(self, argv: Sequence[str], stdin: str | None) -> CommandResult:
        self.calls.append((list(argv), stdin))
        line = " ".join(argv)
        # Longest matching prefix wins, so specific replies beat generic ones.
        for prefix in sorted(self.replies, key=len, reverse=True):
            if line.startswith(prefix):
                reply = self.replies[prefix]
                return CommandResult(0, reply) if isinstance(reply, str) else reply
        return CommandResult(0, "")

    @property
    def argvs(self) -> list[list[str]]:
        return [argv for argv, _ in self.calls]
