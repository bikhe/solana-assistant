from __future__ import annotations

import json

import pytest

from solana_core.protocol.generated import EmptyParams, PingResult, VoiceMuteParams
from solana_core.server import rpc
from solana_core.server.rpc import Dispatcher, RpcError


@pytest.fixture
def dispatcher() -> Dispatcher:
    d = Dispatcher()

    @d.method("ping")
    async def ping(_: EmptyParams) -> PingResult:
        return PingResult(pong=True, version="t", protocol_version=1, fake=True)

    @d.method("voice.mute")
    async def mute(params: VoiceMuteParams) -> VoiceMuteParams:
        if params.muted:
            raise RpcError(rpc.CONFLICT, "busy")
        return params

    @d.method("state.get")
    async def boom(_: EmptyParams) -> PingResult:
        raise RuntimeError("boom")

    return d


async def call(d: Dispatcher, message: object) -> dict[str, object]:
    raw = await d.handle_raw(json.dumps(message))
    assert raw is not None
    return dict(json.loads(raw))


async def test_success(dispatcher: Dispatcher) -> None:
    reply = await call(dispatcher, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert reply == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"pong": True, "version": "t", "protocol_version": 1, "fake": True},
    }


async def test_parse_error(dispatcher: Dispatcher) -> None:
    raw = await dispatcher.handle_raw("{not json")
    assert raw is not None
    assert json.loads(raw)["error"]["code"] == rpc.PARSE_ERROR


@pytest.mark.parametrize(
    "message",
    [[], {"id": 1, "method": "ping"}, {"jsonrpc": "2.0", "id": 1}, {"jsonrpc": "2.0", "id": {}}],
)
async def test_invalid_request(dispatcher: Dispatcher, message: object) -> None:
    reply = await call(dispatcher, message)
    assert reply["error"]["code"] == rpc.INVALID_REQUEST  # type: ignore[index]


async def test_method_not_found(dispatcher: Dispatcher) -> None:
    reply = await call(dispatcher, {"jsonrpc": "2.0", "id": 1, "method": "chat.send"})
    assert reply["error"]["code"] == rpc.METHOD_NOT_FOUND  # type: ignore[index]


async def test_invalid_params(dispatcher: Dispatcher) -> None:
    reply = await call(
        dispatcher, {"jsonrpc": "2.0", "id": 1, "method": "voice.mute", "params": {"muted": "x"}}
    )
    assert reply["error"]["code"] == rpc.INVALID_PARAMS  # type: ignore[index]
    reply = await call(
        dispatcher, {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {"extra": 1}}
    )
    assert reply["error"]["code"] == rpc.INVALID_PARAMS  # type: ignore[index]


async def test_handler_errors(dispatcher: Dispatcher) -> None:
    reply = await call(
        dispatcher, {"jsonrpc": "2.0", "id": 1, "method": "voice.mute", "params": {"muted": True}}
    )
    assert reply["error"] == {"code": rpc.CONFLICT, "message": "busy"}
    reply = await call(dispatcher, {"jsonrpc": "2.0", "id": 2, "method": "state.get"})
    assert reply["error"]["code"] == rpc.INTERNAL_ERROR  # type: ignore[index]


async def test_notification_gets_no_reply(dispatcher: Dispatcher) -> None:
    assert await dispatcher.handle_raw(json.dumps({"jsonrpc": "2.0", "method": "ping"})) is None


def test_unknown_method_cannot_be_registered() -> None:
    with pytest.raises(ValueError):
        Dispatcher().method("not.in.schema")
