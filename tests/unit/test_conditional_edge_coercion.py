"""Tests for ConditionalEdge.resolve scalar coercion.

The path_map mechanism accepts JSON-canonical scalar return values from
routing functions (str, bool, None, int, float) so that path_map can be
authored cross-language without forcing every routing function to wrap
its return value in a bool->str lambda.
"""

from __future__ import annotations

import pytest

from orchestra.core.edges import ConditionalEdge, _coerce_path_key
from orchestra.core.errors import GraphCompileError
from orchestra.core.types import END


class TestCoercePathKey:
    """Unit tests for the scalar coercion helper."""

    def test_string_passthrough(self) -> None:
        assert _coerce_path_key("hello") == "hello"
        assert _coerce_path_key("") == ""

    def test_bool_to_json_lowercase(self) -> None:
        assert _coerce_path_key(True) == "true"
        assert _coerce_path_key(False) == "false"

    def test_none_to_null(self) -> None:
        assert _coerce_path_key(None) == "null"

    def test_int_to_string(self) -> None:
        assert _coerce_path_key(0) == "0"
        assert _coerce_path_key(42) == "42"
        assert _coerce_path_key(-1) == "-1"

    def test_float_to_string(self) -> None:
        assert _coerce_path_key(0.5) == "0.5"
        assert _coerce_path_key(-3.14) == "-3.14"

    def test_non_coercible_returns_none(self) -> None:
        assert _coerce_path_key([1, 2]) is None
        assert _coerce_path_key({"k": "v"}) is None
        assert _coerce_path_key(object()) is None
        assert _coerce_path_key(lambda: None) is None


class TestConditionalEdgeResolveBackwardCompat:
    """Existing behavior must be preserved exactly."""

    def test_string_result_with_path_map(self) -> None:
        edge = ConditionalEdge(
            source="src",
            condition=lambda s: "go_a",
            path_map={"go_a": "node_a", "go_b": "node_b"},
        )
        assert edge.resolve({}) == "node_a"

    def test_string_result_without_path_map(self) -> None:
        edge = ConditionalEdge(
            source="src",
            condition=lambda s: "node_x",
        )
        assert edge.resolve({}) == "node_x"

    def test_missing_key_raises_with_helpful_message(self) -> None:
        edge = ConditionalEdge(
            source="src",
            condition=lambda s: "go_c",
            path_map={"go_a": "node_a", "go_b": "node_b"},
        )
        with pytest.raises(GraphCompileError) as exc:
            edge.resolve({})
        msg = str(exc.value)
        assert "'go_c'" in msg
        assert "Available keys" in msg
        assert "'go_a'" in msg or "go_a" in msg

    def test_end_sentinel_passthrough_without_path_map(self) -> None:
        edge = ConditionalEdge(
            source="src",
            condition=lambda s: END,
        )
        assert edge.resolve({}) is END


class TestConditionalEdgeResolveScalarCoercion:
    """New: bool/None/numeric returns coerce before path_map lookup."""

    def test_bool_true_lookup(self) -> None:
        edge = ConditionalEdge(
            source="src",
            condition=lambda s: True,
            path_map={"true": "blocked", "false": "allowed"},
        )
        assert edge.resolve({}) == "blocked"

    def test_bool_false_lookup(self) -> None:
        edge = ConditionalEdge(
            source="src",
            condition=lambda s: False,
            path_map={"true": "blocked", "false": "allowed"},
        )
        assert edge.resolve({}) == "allowed"

    def test_none_lookup(self) -> None:
        edge = ConditionalEdge(
            source="src",
            condition=lambda s: None,
            path_map={"null": "missing", "true": "blocked", "false": "allowed"},
        )
        assert edge.resolve({}) == "missing"

    def test_int_lookup(self) -> None:
        edge = ConditionalEdge(
            source="src",
            condition=lambda s: 42,
            path_map={"42": "answer", "0": "zero"},
        )
        assert edge.resolve({}) == "answer"

    def test_float_lookup(self) -> None:
        edge = ConditionalEdge(
            source="src",
            condition=lambda s: 0.5,
            path_map={"0.5": "half", "1.0": "whole"},
        )
        assert edge.resolve({}) == "half"

    def test_bool_returned_without_path_map_passthrough(self) -> None:
        """Without a path_map, scalar passthrough is preserved (current behavior)."""
        edge = ConditionalEdge(
            source="src",
            condition=lambda s: True,
        )
        assert edge.resolve({}) is True

    def test_non_coercible_with_path_map_passthrough(self) -> None:
        """A list/dict/sentinel return value with path_map falls through unchanged."""
        marker = object()
        edge = ConditionalEdge(
            source="src",
            condition=lambda s: marker,
            path_map={"a": "node_a"},
        )
        assert edge.resolve({}) is marker

    def test_missing_bool_key_includes_coerced_form_in_error(self) -> None:
        """Error message must show users the lookup key to add to path_map."""
        edge = ConditionalEdge(
            source="src",
            condition=lambda s: True,
            path_map={"yes": "allowed", "no": "blocked"},
        )
        with pytest.raises(GraphCompileError) as exc:
            edge.resolve({})
        msg = str(exc.value)
        # The coerced key should appear in the "Fix" hint so users know
        # what to add to their path_map.
        assert "'true'" in msg


class TestRealisticPatterns:
    """Integration-style: the patterns Path 3 was designed to enable."""

    def test_factscore_style_enum_routing(self) -> None:
        """Routing function returns a state field directly; path_map enumerates."""
        edge = ConditionalEdge(
            source="factscore",
            condition=lambda s: s["factscore"]["hallucination_risk"],
            path_map={"low": "done", "medium": "retry", "high": "retry"},
        )
        assert edge.resolve({"factscore": {"hallucination_risk": "low"}}) == "done"
        assert edge.resolve({"factscore": {"hallucination_risk": "medium"}}) == "retry"
        assert edge.resolve({"factscore": {"hallucination_risk": "high"}}) == "retry"

    def test_rebuff_style_truthy_routing(self) -> None:
        """Routing function returns a bool field directly; path_map handles both."""
        edge = ConditionalEdge(
            source="guard",
            condition=lambda s: s.get("rebuff", {}).get("injection_detected", False),
            path_map={"true": "blocked", "false": "researcher"},
        )
        assert edge.resolve({"rebuff": {"injection_detected": True}}) == "blocked"
        assert edge.resolve({"rebuff": {"injection_detected": False}}) == "researcher"
        assert edge.resolve({}) == "researcher"
