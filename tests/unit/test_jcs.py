"""Tests for JCS canonicalization (RFC 8785)."""

from __future__ import annotations
from orchestra.interop.zkp import jcs_canonicalize


def test_jcs_basic_sort():
    state = {"b": 2, "a": 1}
    # JCS should sort keys
    assert jcs_canonicalize(state) == b'{"a":1,"b":2}'


def test_jcs_nested_sort():
    state = {
        "z": 0,
        "a": {
            "y": 2,
            "x": 1
        }
    }
    # Should sort nested keys recursively
    assert jcs_canonicalize(state) == b'{"a":{"x":1,"y":2},"z":0}'


def test_jcs_separators():
    state = {"a": 1, "b": 2}
    # Should have no whitespace
    assert b" " not in jcs_canonicalize(state)
    assert b"\n" not in jcs_canonicalize(state)


def test_jcs_unicode():
    state = {"greeting": "hello 🌍"}
    # Should handle unicode correctly as UTF-8
    assert b"hello \xf0\x9f\x8c\x8d" in jcs_canonicalize(state)
