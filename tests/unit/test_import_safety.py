"""Tests that orchestra imports succeed even when optional deps are absent."""
import sys
import pytest


def _block(monkeypatch, *names):
    for name in names:
        monkeypatch.setitem(sys.modules, name, None)


def _clear_orchestra(monkeypatch):
    for mod in list(sys.modules):
        if mod == "orchestra" or mod.startswith("orchestra."):
            monkeypatch.delitem(sys.modules, mod, raising=False)


def test_import_orchestra_no_extras(monkeypatch):
    _block(monkeypatch, "numpy", "joserfc", "watchfiles", "rebuff")
    _clear_orchestra(monkeypatch)
    import orchestra  # noqa: F401


def test_import_memory_no_numpy(monkeypatch):
    _block(monkeypatch, "numpy")
    _clear_orchestra(monkeypatch)
    import orchestra.memory  # noqa: F401


def test_import_routing_no_numpy(monkeypatch):
    _block(monkeypatch, "numpy")
    _clear_orchestra(monkeypatch)
    import orchestra.routing  # noqa: F401


def test_import_identity_no_joserfc(monkeypatch):
    _block(monkeypatch, "joserfc")
    _clear_orchestra(monkeypatch)
    import orchestra.identity  # noqa: F401
