"""Convert raw messages into typed events."""
from __future__ import annotations

from typing import Iterable

from .classify import classify
from .extract import extract
from .fetch import RawMessage


def to_event(msg: RawMessage | dict) -> dict:
    """Classify + extract a single message into an event dict.

    Always returns at minimum {id, ts, type, has_photo}; extracted fields
    are merged in.
    """
    if isinstance(msg, RawMessage):
        d = msg.as_dict()
    else:
        d = dict(msg)
    msg_type = classify(d.get("text", ""))
    fields = extract(msg_type, d.get("text", ""))
    return {
        "id": d["id"],
        "ts": d["ts"],
        "type": msg_type,
        "has_photo": d.get("has_photo", False),
        **fields,
    }


def to_events(msgs: Iterable[RawMessage | dict]) -> list[dict]:
    return [to_event(m) for m in msgs]
