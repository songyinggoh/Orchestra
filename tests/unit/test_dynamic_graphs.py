"""Unit tests for core/dynamic.py — SubgraphBuilder and load_graph_yaml."""

from __future__ import annotations

import pytest

from orchestra.core.dynamic import (
    DEFAULT_ALLOWED_PREFIXES,
    SubgraphBuilder,
    dump_graph_yaml,
    load_graph_yaml,
)

# ---------------------------------------------------------------------------
# SubgraphBuilder — resolve_ref
# ---------------------------------------------------------------------------


class TestSubgraphBuilderResolveRef:
    def test_default_prefixes_are_tuple(self):
        """DEFAULT_ALLOWED_PREFIXES is an immutable tuple to prevent runtime poisoning."""
        assert isinstance(DEFAULT_ALLOWED_PREFIXES, tuple)

    def test_resolve_allowed_ref(self):
        builder = SubgraphBuilder()
        # orchestra.core.graph is within the allowed "orchestra.core." prefix
        cls = builder.resolve_ref("orchestra.core.graph.WorkflowGraph")
        from orchestra.core.graph import WorkflowGraph

        assert cls is WorkflowGraph

    def test_resolve_blocked_ref_raises_import_error(self):
        builder = SubgraphBuilder()
        with pytest.raises(ImportError, match="not in the security allowlist"):
            builder.resolve_ref("os.path.join")

    def test_resolve_blocked_ref_partial_match_blocked(self):
        """A ref that starts with something close but not exactly an allowed prefix."""
        builder = SubgraphBuilder()
        with pytest.raises(ImportError):
            builder.resolve_ref("orchestra.core_evil.agent.EvilAgent")

    def test_resolve_nonexistent_module_raises_import_error(self):
        builder = SubgraphBuilder(allowed_prefixes=["orchestra.core."])
        with pytest.raises(ImportError, match="Failed to resolve"):
            builder.resolve_ref("orchestra.core.nonexistent_module.SomeClass")

    def test_custom_allowed_prefixes(self):
        builder = SubgraphBuilder(allowed_prefixes=["os.path."])
        result = builder.resolve_ref("os.path.join")
        import os.path

        assert result is os.path.join

    def test_custom_prefixes_stored_as_tuple(self):
        """Even if a list is passed, the instance stores a tuple."""
        builder = SubgraphBuilder(allowed_prefixes=["orchestra.core."])
        assert isinstance(builder._allowed_prefixes, tuple)

    def test_resolve_ref_without_dot_raises(self):
        builder = SubgraphBuilder(allowed_prefixes=["orchestra."])
        with pytest.raises(ImportError):
            builder.resolve_ref("orchestra")

    def test_resolve_bad_attribute_raises_import_error(self):
        builder = SubgraphBuilder(allowed_prefixes=["orchestra.core."])
        with pytest.raises(ImportError, match="Failed to resolve"):
            builder.resolve_ref("orchestra.core.types.NonExistentClass")


# ---------------------------------------------------------------------------
# load_graph_yaml — basic YAML hydration
# ---------------------------------------------------------------------------

_MINIMAL_YAML = """\
name: test_graph
nodes:
  echo:
    type: function
    ref: orchestra.core.graph.WorkflowGraph
entry_point: echo
edges:
  - source: echo
    target: __end__
"""

_SIMPLE_FUNCTION_YAML = """\
name: simple
nodes:
  step_a:
    type: function
    ref: orchestra.core.dynamic.dump_graph_yaml
entry_point: step_a
edges:
  - source: step_a
    target: __end__
"""


class TestLoadGraphYaml:
    def test_load_returns_compiled_graph(self):
        from orchestra.core.compiled import CompiledGraph

        yaml_str = """\
name: empty_test
nodes:
  start:
    type: function
    ref: orchestra.core.dynamic.dump_graph_yaml
entry_point: start
edges:
  - source: start
    target: __end__
"""
        compiled = load_graph_yaml(yaml_str)
        assert isinstance(compiled, CompiledGraph)

    def test_load_sets_graph_name(self):
        yaml_str = """\
name: my_named_graph
nodes:
  step:
    type: function
    ref: orchestra.core.dynamic.dump_graph_yaml
entry_point: step
edges:
  - source: step
    target: __end__
"""
        compiled = load_graph_yaml(yaml_str)
        assert compiled._name == "my_named_graph"

    def test_load_blocked_ref_raises(self):
        yaml_str = """\
name: evil
nodes:
  hack:
    type: function
    ref: os.system
entry_point: hack
edges:
  - source: hack
    target: __end__
"""
        with pytest.raises(ImportError, match="not in the security allowlist"):
            load_graph_yaml(yaml_str)

    def test_load_uses_provided_builder(self):
        # Prefix covers orchestra.core.graph.* but NOT orchestra.core.dynamic.*
        builder = SubgraphBuilder(allowed_prefixes=["orchestra.core.graph."])
        yaml_str = """\
name: custom_builder
nodes:
  step:
    type: function
    ref: orchestra.core.dynamic.dump_graph_yaml
entry_point: step
edges:
  - source: step
    target: __end__
"""
        # dump_graph_yaml is in orchestra.core.dynamic which is outside the
        # "orchestra.core.graph." prefix, so this builder should block it.
        with pytest.raises(ImportError):
            load_graph_yaml(yaml_str, builder=builder)

    def test_load_default_max_turns(self):
        yaml_str = """\
name: max_turns_test
nodes:
  node:
    type: function
    ref: orchestra.core.dynamic.dump_graph_yaml
entry_point: node
edges:
  - source: node
    target: __end__
"""
        compiled = load_graph_yaml(yaml_str)
        assert compiled._max_turns == 50

    def test_load_custom_max_turns(self):
        yaml_str = """\
name: limited
max_turns: 5
nodes:
  node:
    type: function
    ref: orchestra.core.dynamic.dump_graph_yaml
entry_point: node
edges:
  - source: node
    target: __end__
"""
        compiled = load_graph_yaml(yaml_str)
        assert compiled._max_turns == 5

    def test_load_edge_direct(self):
        yaml_str = """\
name: edge_test
nodes:
  a:
    type: function
    ref: orchestra.core.dynamic.dump_graph_yaml
  b:
    type: function
    ref: orchestra.core.dynamic.dump_graph_yaml
entry_point: a
edges:
  - source: a
    target: b
  - source: b
    target: __end__
"""
        compiled = load_graph_yaml(yaml_str)
        # both nodes should be present
        assert "a" in compiled._nodes
        assert "b" in compiled._nodes

    def test_load_no_nodes_produces_error(self):
        yaml_str = """\
name: empty
nodes: {}
"""
        with pytest.raises(Exception):
            load_graph_yaml(yaml_str)


# ---------------------------------------------------------------------------
# dump_graph_yaml
# ---------------------------------------------------------------------------


class TestDumpGraphYaml:
    def test_dump_returns_string(self):
        data = {"name": "test", "nodes": ["a", "b"]}
        result = dump_graph_yaml(data)
        assert isinstance(result, str)
        assert "test" in result

    def test_dump_roundtrip(self):
        from ruamel.yaml import YAML

        data = {"name": "roundtrip", "nodes": {"a": {"type": "function"}}}
        dumped = dump_graph_yaml(data)
        yaml = YAML(typ="safe")
        reloaded = yaml.load(dumped)
        assert reloaded["name"] == "roundtrip"

    def test_dump_empty_dict(self):
        result = dump_graph_yaml({})
        assert isinstance(result, str)
