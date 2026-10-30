"""IPC protocol: pydantic models generated from protocol/ipc.schema.json plus helper maps.

Never edit ``generated.py`` by hand: change the schema and run ``scripts/gen_protocol.py``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from solana_core.protocol.generated import EventMap, RequestMap

PROTOCOL_VERSION = 1

AssistantState = Literal["idle", "wake", "listening", "thinking", "speaking", "muted", "error"]
Language = Literal["ru", "en"]
Risk = Literal["safe", "confirm", "dangerous"]


def _model_of(owner: type[BaseModel], field: str) -> type[BaseModel]:
    annotation = owner.model_fields[field].annotation
    assert isinstance(annotation, type) and issubclass(annotation, BaseModel)
    return annotation


def _alias(owner: type[BaseModel], field: str) -> str:
    return owner.model_fields[field].alias or field


# method name -> (params model, result model)
METHODS: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    _alias(RequestMap, name): (
        _model_of(_model_of(RequestMap, name), "params"),
        _model_of(_model_of(RequestMap, name), "result"),
    )
    for name in RequestMap.model_fields
}

# event name -> params model
EVENTS: dict[str, type[BaseModel]] = {
    _alias(EventMap, name): _model_of(EventMap, name) for name in EventMap.model_fields
}

__all__ = [
    "EVENTS",
    "METHODS",
    "PROTOCOL_VERSION",
    "AssistantState",
    "Language",
    "Risk",
]
