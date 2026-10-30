"""Transport-independent JSON-RPC 2.0 dispatcher.

Params and results are validated against the models generated from protocol/ipc.schema.json.
Batch requests are not supported (the app never sends them).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from solana_core.protocol import METHODS

log = logging.getLogger(__name__)

# Standard JSON-RPC codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
# Solana codes (documented in protocol/README.md)
NOT_IMPLEMENTED = -32001
NOT_FOUND = -32002
CONFLICT = -32003

Handler = Callable[[Any], Awaitable[BaseModel]]


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


def not_implemented(what: str) -> RpcError:
    return RpcError(NOT_IMPLEMENTED, f"{what} is not implemented yet")


class Dispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    @property
    def methods(self) -> set[str]:
        return set(self._handlers)

    def method(self, name: str) -> Callable[[Handler], Handler]:
        """Register a handler: it gets the validated params model and returns the result model."""
        if name not in METHODS:
            raise ValueError(f"{name} is not in protocol/ipc.schema.json")

        def decorator(func: Handler) -> Handler:
            self._handlers[name] = func
            return func

        return decorator

    async def handle_raw(self, raw: str | bytes) -> str | None:
        """Handle one incoming message. Returns the response text, or None for notifications."""
        try:
            message = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _encode_error(None, RpcError(PARSE_ERROR, "Parse error"))
        response = await self.handle(message)
        return None if response is None else json.dumps(response, ensure_ascii=False)

    async def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, RpcError(INVALID_REQUEST, "Invalid Request"))
        request_id = message.get("id")
        is_notification = "id" not in message
        method = message.get("method")
        if not isinstance(method, str) or not isinstance(request_id, str | int | None):
            return _error(request_id, RpcError(INVALID_REQUEST, "Invalid Request"))
        try:
            result = await self._call(method, message.get("params", {}))
        except RpcError as exc:
            return None if is_notification else _error(request_id, exc)
        except Exception:
            log.exception("handler for %s failed", method)
            err = RpcError(INTERNAL_ERROR, "Internal error")
            return None if is_notification else _error(request_id, err)
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    async def _call(self, method: str, params: Any) -> Any:
        handler = self._handlers.get(method)
        if handler is None or method not in METHODS:
            raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")
        params_model, result_model = METHODS[method]
        try:
            parsed = params_model.model_validate(params if params is not None else {})
        except ValidationError as exc:
            raise RpcError(INVALID_PARAMS, "Invalid params", exc.errors(include_url=False)) from exc
        result = await handler(parsed)
        if not isinstance(result, result_model):
            result = result_model.model_validate(result.model_dump())
        return result.model_dump(mode="json", exclude_none=True)


def _error(request_id: Any, exc: RpcError) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": exc.to_dict()}


def _encode_error(request_id: Any, exc: RpcError) -> str:
    return json.dumps(_error(request_id, exc), ensure_ascii=False)
