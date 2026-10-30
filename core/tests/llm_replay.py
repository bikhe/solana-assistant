"""Replays recorded LLM HTTP streams from ``tests/fixtures/llm`` instead of the network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).parent / "fixtures" / "llm"


class Replay:
    """httpx transport: each POST gets the next recorded stream; requests are kept."""

    def __init__(self, *names: str) -> None:
        self._responses: list[httpx.Response | Exception] = [self.sse(n) for n in names]
        self.requests: list[httpx.Request] = []

    @staticmethod
    def sse(name: str) -> httpx.Response:
        body = (FIXTURES / name).read_bytes()
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    def then(self, response: httpx.Response | Exception) -> Replay:
        self._responses.append(response)
        return self

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))
