from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

from solana_core.protocol import EVENTS, METHODS, PROTOCOL_VERSION
from solana_core.protocol.generated import IpcProtocol

SCHEMA = Path(__file__).resolve().parents[2] / "protocol" / "ipc.schema.json"


def test_maps_cover_schema() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    defs = schema["$defs"]
    assert set(METHODS) == set(defs["RequestMap"]["properties"])
    assert set(EVENTS) == set(defs["EventMap"]["properties"])


def test_protocol_version_matches_schema() -> None:
    annotation = IpcProtocol.model_fields["protocol_version"].annotation
    assert get_args(annotation) == (PROTOCOL_VERSION,)


def test_contract_names_from_plan() -> None:
    for method in ("settings.get", "settings.set", "chat.send", "voice.mute", "confirm.reply"):
        assert method in METHODS
    for event in (
        "state",
        "transcript.partial",
        "transcript.final",
        "assistant.delta",
        "assistant.done",
        "tool.started",
        "tool.finished",
        "confirm.request",
        "download.progress",
        "error",
    ):
        assert event in EVENTS
