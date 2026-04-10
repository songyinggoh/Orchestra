import base64
import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from uuid import uuid4

from orchestra.storage.state_serialization import safe_serialize


class Color(Enum):
    RED = "red"


def test_datetime():
    result = json.loads(safe_serialize({"ts": datetime(2026, 1, 1)}))
    assert result["ts"] == "2026-01-01T00:00:00"


def test_uuid():
    uid = uuid4()
    result = json.loads(safe_serialize({"id": uid}))
    assert result["id"] == str(uid)


def test_set():
    result = json.loads(safe_serialize({"s": {"b", "a"}}))
    assert sorted(result["s"]) == ["a", "b"]


def test_bytes():
    result = json.loads(safe_serialize({"d": b"hi"}))
    assert result["d"] == base64.b64encode(b"hi").decode()


def test_enum():
    result = json.loads(safe_serialize({"c": Color.RED}))
    assert result["c"] == "red"


def test_path():
    path_val = Path("/tmp")
    result = json.loads(safe_serialize({"p": path_val}))
    assert result["p"] == str(path_val)
