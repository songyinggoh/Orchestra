"""Serialization helpers for tiered memory.

Provides msgpack-based serialization with support for common Orchestra types
(Pydantic, dataclasses, datetime) and auto-reconstruction via a secure registry.
"""

from __future__ import annotations

import datetime
from dataclasses import asdict, is_dataclass
from typing import Any, Type

import msgpack
import structlog
from pydantic import BaseModel

from orchestra.core import types

logger = structlog.get_logger(__name__)

# CRITICAL-4.4: Explicit registry of types permitted during deserialization.
# This replaces insecure dynamic imports (importlib) with a static allowlist.
# Only types listed here can be reconstructed from serialized data.
# To register a new type: add an entry below with key "{module}.{classname}".
SERIALIZATION_REGISTRY: dict[str, Type[Any]] = {
    "orchestra.core.types.AgentResult": types.AgentResult,
    "orchestra.core.types.LLMResponse": types.LLMResponse,
    "orchestra.core.types.Message": types.Message,
    "orchestra.core.types.ModelCost": types.ModelCost,
    "orchestra.core.types.Send": types.Send,
    "orchestra.core.types.StreamChunk": types.StreamChunk,
    "orchestra.core.types.TokenUsage": types.TokenUsage,
    "orchestra.core.types.ToolCall": types.ToolCall,
    "orchestra.core.types.ToolCallRecord": types.ToolCallRecord,
    "orchestra.core.types.ToolResult": types.ToolResult,
}


def _default(obj: Any) -> Any:
    """Custom msgpack encoder for Orchestra types."""
    if isinstance(obj, datetime.datetime):
        return {
            "__type__": "datetime",
            "as_str": obj.isoformat(),
        }
    if isinstance(obj, BaseModel):
        return {
            "__type__": "pydantic",
            "module": obj.__class__.__module__,
            "name": obj.__class__.__name__,
            "data": obj.model_dump(),
        }
    if is_dataclass(obj) and not isinstance(obj, type):
        return {
            "__type__": "dataclass",
            "module": obj.__class__.__module__,
            "name": obj.__class__.__name__,
            "data": asdict(obj),
        }
    raise TypeError(f"Object of type {obj.__class__.__name__} is not msgpack serializable")


def _object_hook(obj: Any) -> Any:
    """Custom msgpack decoder for Orchestra types."""
    if not isinstance(obj, dict) or "__type__" not in obj:
        return obj

    obj_type = obj["__type__"]

    if obj_type == "datetime":
        return datetime.datetime.fromisoformat(obj["as_str"])

    if obj_type in ("pydantic", "dataclass"):
        module_path: str = obj.get("module", "")
        class_name: str = obj.get("name", "")
        lookup_key = f"{module_path}.{class_name}"

        # CRITICAL-4.4: Secure lookup via registry instead of importlib.import_module.
        cls = SERIALIZATION_REGISTRY.get(lookup_key)

        if cls is None:
            # Type not in registry — security boundary reached.
            # Log so developers know to register the type; return raw dict.
            logger.warning(
                "serialization_registry_miss",
                registry_key=lookup_key,
                hint="Add this type to SERIALIZATION_REGISTRY in serialization.py",
            )
            return obj.get("data", obj)

        try:
            if obj_type == "pydantic":
                if issubclass(cls, BaseModel):
                    return cls.model_validate(obj["data"])
            elif is_dataclass(cls):
                return cls(**obj["data"])
        except (ValueError, TypeError):
            # Fallback to raw dict if reconstruction fails
            return obj.get("data", obj)

    return obj


def pack(value: Any) -> bytes:
    """Pack an object into msgpack bytes."""
    return msgpack.packb(value, default=_default, use_bin_type=True)


def unpack(data: bytes) -> Any:
    """Unpack msgpack bytes into an object."""
    return msgpack.unpackb(data, object_hook=_object_hook, raw=False)
