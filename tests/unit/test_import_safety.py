"""Tests that orchestra imports cleanly even when optional deps are absent."""
import importlib
import sys
import pytest


def _block_import(monkeypatch, *package_names):
    """Simulate absence of packages by inserting None sentinels."""
    for name in package_names:
        monkeypatch.setitem(sys.modules, name, None)


def test_import_orchestra_no_extras(monkeypatch):
    _block_import(monkeypatch, "numpy", "joserfc", "watchfiles", "rebuff")
    # Force reimport of _compat
    for mod in list(sys.modules):
        if "orchestra" in mod:
            monkeypatch.delitem(sys.modules, mod, raising=False)
    import orchestra  # noqa: F401
    assert orchestra is not None


def test_import_memory_no_numpy(monkeypatch):
    _block_import(monkeypatch, "numpy")
    for mod in list(sys.modules):
        if "orchestra.memory" in mod or "orchestra._compat" in mod:
            monkeypatch.delitem(sys.modules, mod, raising=False)
    import orchestra.memory  # noqa: F401


def test_import_routing_no_numpy(monkeypatch):
    _block_import(monkeypatch, "numpy")
    for mod in list(sys.modules):
        if "orchestra.routing" in mod or "orchestra._compat" in mod:
            monkeypatch.delitem(sys.modules, mod, raising=False)
    import orchestra.routing  # noqa: F401


def test_import_identity_no_joserfc(monkeypatch):
    _block_import(monkeypatch, "joserfc")
    for mod in list(sys.modules):
        if "orchestra.identity" in mod or "orchestra._compat" in mod:
            monkeypatch.delitem(sys.modules, mod, raising=False)
    import orchestra.identity  # noqa: F401
