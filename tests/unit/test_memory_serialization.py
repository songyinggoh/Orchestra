import datetime
import msgpack
import pytest
from orchestra.core.types import Message, MessageRole
from orchestra.memory.serialization import pack, unpack


def test_roundtrip_primitives():
    data = {"a": 1, "b": "hello", "c": [1, 2, 3], "d": True, "e": None}
    packed = pack(data)
    unpacked = unpack(packed)
    assert unpacked == data


def test_roundtrip_datetime():
    now = datetime.datetime.now(datetime.timezone.utc)
    data = {"ts": now}
    packed = pack(data)
    unpacked = unpack(packed)
    assert unpacked == data
    assert isinstance(unpacked["ts"], datetime.datetime)


def test_roundtrip_pydantic():
    # Use a real Orchestra Pydantic model so its module path is under orchestra.*
    obj = Message(role=MessageRole.USER, content="hello")
    packed = pack(obj)
    unpacked = unpack(packed)
    assert isinstance(unpacked, Message)
    assert unpacked.role == MessageRole.USER
    assert unpacked.content == "hello"


def test_roundtrip_nested():
    now = datetime.datetime.now(datetime.timezone.utc)
    msg = Message(role=MessageRole.ASSISTANT, content="hi")
    data = {"msg": msg, "created_at": now}
    packed = pack(data)
    unpacked = unpack(packed)
    assert isinstance(unpacked["msg"], Message)
    assert unpacked["msg"].content == "hi"
    assert unpacked["created_at"] == now


def test_unserializable_raises():
    class Unserializable:
        pass

    with pytest.raises(TypeError):
        pack(Unserializable())


def test_reconstruction_fallback_missing_module():
    # Module not in allowlist — should fall back to raw data dict, not raise.
    fake_data = {
        "__type__": "dataclass",
        "module": "non.existent.module",
        "name": "MissingClass",
        "data": {"key": "value"},
    }
    packed = msgpack.packb(fake_data)
    unpacked = unpack(packed)
    assert unpacked == {"key": "value"}


def test_allowlist_blocks_untrusted_module():
    # A crafted payload pointing at a stdlib module must be silently rejected.
    for module_path in ("os", "subprocess", "builtins", "importlib"):
        payload = {
            "__type__": "pydantic",
            "module": module_path,
            "name": "some_attr",
            "data": {},
        }
        packed = msgpack.packb(payload)
        result = unpack(packed)
        # Must return raw data dict, never call into the untrusted module.
        assert result == {}, f"Untrusted module '{module_path}' was not blocked"


@pytest.mark.parametrize("module_path", [
    "os",
    "subprocess",
    "sys",
    "builtins",
    "importlib",
    "__main__",
])
def test_serialization_blocks_dangerous_module_paths(module_path):
    """Crafted payloads pointing at dangerous stdlib modules must be rejected
    by the allowlist before any import is attempted, returning the raw data dict."""
    import msgpack

    for obj_type in ("pydantic", "dataclass"):
        payload = {
            "__type__": obj_type,
            "module": module_path,
            "name": "some_attr",
            "data": {"key": "value"},
        }
        packed = msgpack.packb(payload)
        result = unpack(packed)
        # Allowlist check fires before importlib.import_module; result is raw data.
        assert result == {"key": "value"}, (
            f"Dangerous module '{module_path}' (type={obj_type}) was not blocked "
            f"by the serialization allowlist — got {result!r}"
        )


def test_allowlist_blocks_non_basemodel():
    # Even if the module is in the allowlist, the class must actually be a BaseModel.
    # orchestra.core.types.MessageRole is an Enum, not a BaseModel — should fall back.
    payload = {
        "__type__": "pydantic",
        "module": "orchestra.core.types",
        "name": "MessageRole",
        "data": {},
    }
    packed = msgpack.packb(payload)
    result = unpack(packed)
    assert result == {}
