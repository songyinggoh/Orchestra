"""Safe JSON serialization for workflow state objects."""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)


def _json_fallback(obj: object) -> object:
    """JSON default encoder for types not natively handled."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, set):
        return sorted(str(x) for x in obj)
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    # Pydantic models
    try:
        return obj.model_dump()  # type: ignore[union-attr]
    except AttributeError:
        pass
    return repr(obj)


def safe_serialize(state: object) -> str:
    """Serialize state to JSON, falling back gracefully for exotic types."""
    # Primary: Pydantic's Rust serializer
    try:
        return state.model_dump_json()  # type: ignore[union-attr]
    except AttributeError:
        pass
    except Exception as exc:
        logger.debug("model_dump_json failed, using fallback: %s", exc)

    # Fallback: standard json with type coercion
    if isinstance(state, dict):
        return json.dumps(state, default=_json_fallback)

    try:
        return json.dumps(state, default=_json_fallback)
    except Exception as exc:
        logger.warning("safe_serialize failed for %r: %s", type(state), exc)
        return json.dumps({"__serialization_error__": repr(exc), "__type__": repr(type(state))})
