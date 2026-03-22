"""Event serialization/deserialization (JSON).

Provides JSON and JSONL roundtrip for all event types using
Pydantic's discriminated union via TypeAdapter.
"""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from orchestra.storage.events import AnyEvent, WorkflowEvent

# TypeAdapter for the discriminated union -- handles polymorphic deserialization
_event_adapter = TypeAdapter(AnyEvent)


def event_to_dict(event: WorkflowEvent) -> dict[str, Any]:
    """Serialize an event to a JSON-safe dict (all values are JSON primitives)."""
    return event.model_dump(mode="json")


def dict_to_event(data: dict[str, Any]) -> WorkflowEvent:
    """Deserialize a dict to the correct event subtype.

    Uses Pydantic's discriminated union on event_type.
    Unknown event types raise ValidationError.
    """
    return _event_adapter.validate_python(data)


def event_to_json(event: WorkflowEvent) -> str:
    """Serialize an event to a JSON string."""
    return event.model_dump_json()


def json_to_event(json_str: str) -> WorkflowEvent:
    """Deserialize a JSON string to the correct event subtype."""
    return _event_adapter.validate_json(json_str)


def events_to_jsonl(events: list[WorkflowEvent]) -> str:
    """Serialize a list of events to JSONL format (one JSON object per line)."""
    return "\n".join(event_to_json(e) for e in events)


def jsonl_to_events(jsonl_str: str) -> list[WorkflowEvent]:
    """Deserialize JSONL to a list of events."""
    lines = [line.strip() for line in jsonl_str.strip().split("\n") if line.strip()]
    return [json_to_event(line) for line in lines]
