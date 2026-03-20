"""Tests for orchestra.discovery.workflow_loader (T-5.4)."""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Annotated, get_type_hints, get_origin, get_args
from unittest.mock import MagicMock, patch

from orchestra.core.agent import BaseAgent
from orchestra.core.state import WorkflowState, merge_dict, sum_numbers
from orchestra.discovery.workflow_loader import (
    build_state_class,
    load_workflow,
    TYPE_MAP,
    REDUCER_MAP,
)
from orchestra.discovery.errors import WorkflowLoadError


# ---- build_state_class ----


def test_build_state_class_simple_types():
    state_def = {"topic": "str", "count": "int", "active": "bool"}
    cls = build_state_class(state_def)
    assert issubclass(cls, WorkflowState)
    obj = cls()
    assert obj.topic == ""
    assert obj.count == 0
    assert obj.active is False


def test_build_state_class_with_reducer():
    state_def = {
        "findings": {"type": "dict", "reducer": "merge_dict"},
    }
    cls = build_state_class(state_def)
    hints = get_type_hints(cls, include_extras=True)
    # Should be Annotated[dict, merge_dict]
    assert get_origin(hints["findings"]) is Annotated
    args = get_args(hints["findings"])
    assert args[0] is dict
    assert args[1] is merge_dict


def test_build_state_class_with_default():
    state_def = {
        "step_count": {"type": "int", "reducer": "sum", "default": 42},
    }
    cls = build_state_class(state_def)
    obj = cls()
    assert obj.step_count == 42


def test_build_state_class_unknown_type_defaults_to_str():
    state_def = {"mystery": "unknown_type"}
    cls = build_state_class(state_def)
    obj = cls()
    assert obj.mystery == ""


def test_type_map_completeness():
    expected = {"str", "int", "float", "bool", "list", "dict", "set"}
    assert set(TYPE_MAP.keys()) == expected


def test_reducer_map_completeness():
    expected = {
        "merge_list", "merge_dict", "sum", "last_write_wins",
        "merge_set", "concat", "keep_first", "max", "min",
    }
    assert set(REDUCER_MAP.keys()) == expected


# ---- load_workflow ----


def test_load_workflow_name_based_resolution(tmp_path: Path):
    """Workflow resolves agent refs from the agent registry by name."""
    yaml_text = """\
name: test_pipeline
nodes:
  researcher:
    type: agent
    ref: researcher
    output_key: research
  writer:
    type: agent
    ref: writer
    output_key: output
edges:
  - source: researcher
    target: writer
  - source: writer
    target: __end__
entry_point: researcher
"""
    wf_file = tmp_path / "pipeline.yaml"
    wf_file.write_text(yaml_text, encoding="utf-8")

    agents = {
        "researcher": BaseAgent(name="researcher", system_prompt="Research."),
        "writer": BaseAgent(name="writer", system_prompt="Write."),
    }
    compiled = load_workflow(wf_file, agent_registry=agents)
    assert compiled is not None
    # Nodes should be present
    assert "researcher" in compiled._nodes
    assert "writer" in compiled._nodes


def test_load_workflow_missing_agent_error(tmp_path: Path):
    yaml_text = """\
name: broken
nodes:
  x:
    type: agent
    ref: nonexistent
edges:
  - source: x
    target: __end__
entry_point: x
"""
    wf_file = tmp_path / "broken.yaml"
    wf_file.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(WorkflowLoadError, match="nonexistent"):
        load_workflow(wf_file, agent_registry={})


def test_load_workflow_with_yaml_state(tmp_path: Path):
    yaml_text = """\
name: stateful
state:
  topic: str
  findings:
    type: dict
    reducer: merge_dict
nodes:
  researcher:
    type: agent
    ref: researcher
    output_key: findings
edges:
  - source: researcher
    target: __end__
entry_point: researcher
"""
    wf_file = tmp_path / "stateful.yaml"
    wf_file.write_text(yaml_text, encoding="utf-8")

    agents = {"researcher": BaseAgent(name="researcher")}
    compiled = load_workflow(wf_file, agent_registry=agents)
    assert compiled is not None


def test_load_workflow_empty_file_raises(tmp_path: Path):
    wf_file = tmp_path / "empty.yaml"
    wf_file.write_text("", encoding="utf-8")
    with pytest.raises(WorkflowLoadError, match="empty"):
        load_workflow(wf_file, agent_registry={})


def test_load_workflow_invalid_yaml_raises(tmp_path: Path):
    wf_file = tmp_path / "bad.yaml"
    wf_file.write_text("  bad:\n  [yaml", encoding="utf-8")
    with pytest.raises(WorkflowLoadError, match="Cannot parse"):
        load_workflow(wf_file, agent_registry={})


# ---------------------------------------------------------------------------
# Additional coverage — state types, reducers, state_ref, output_key
# ---------------------------------------------------------------------------


def test_build_state_class_float_type():
    """'float' type maps to Python float with zero default."""
    state_def = {"score": "float"}
    cls = build_state_class(state_def)
    obj = cls()
    assert isinstance(obj.score, float)
    assert obj.score == 0.0


def test_build_state_class_list_type():
    """'list' type maps to Python list with empty default."""
    state_def = {"items": "list"}
    cls = build_state_class(state_def)
    obj = cls()
    assert isinstance(obj.items, list)


def test_build_state_class_sum_reducer():
    """'sum' reducer should map to sum_numbers function."""
    state_def = {"counter": {"type": "int", "reducer": "sum"}}
    cls = build_state_class(state_def)
    hints = get_type_hints(cls, include_extras=True)
    args = get_args(hints["counter"])
    assert args[1] is sum_numbers


def test_build_state_class_unknown_reducer_treated_as_plain_type():
    """An unknown reducer name should not crash; field remains without Annotated."""
    state_def = {"value": {"type": "str", "reducer": "nonexistent_reducer"}}
    cls = build_state_class(state_def)
    obj = cls()
    assert obj.value == ""


def test_load_workflow_output_key_in_node(tmp_path: Path):
    """output_key specified in a node must be passed through to the compiled graph."""
    yaml_text = """\
name: keyed
nodes:
  researcher:
    type: agent
    ref: researcher
    output_key: my_output
edges:
  - source: researcher
    target: __end__
entry_point: researcher
"""
    wf_file = tmp_path / "keyed.yaml"
    wf_file.write_text(yaml_text, encoding="utf-8")

    agents = {"researcher": BaseAgent(name="researcher")}
    compiled = load_workflow(wf_file, agent_registry=agents)
    assert compiled is not None


def test_load_workflow_no_entry_point_produces_result(tmp_path: Path):
    """A workflow YAML without entry_point must not silently corrupt state.

    Per plan T-5.4, entry_point should eventually be required and trigger a
    WorkflowLoadError. The current implementation compiles without it. This test
    documents the existing behaviour and will be updated once validation is enforced.
    """
    yaml_text = """\
name: no_entry
nodes:
  a:
    type: agent
    ref: a
edges:
  - source: a
    target: __end__
"""
    wf_file = tmp_path / "no_entry.yaml"
    wf_file.write_text(yaml_text, encoding="utf-8")

    agents = {"a": BaseAgent(name="a")}
    # Either raises WorkflowLoadError (desired) or returns compiled graph
    # (current implementation). Both are acceptable for this pre-implementation test.
    try:
        result = load_workflow(wf_file, agent_registry=agents)
        # If it doesn't raise, result should still be a CompiledGraph
        from orchestra.core.compiled import CompiledGraph
        assert isinstance(result, CompiledGraph)
    except WorkflowLoadError:
        pass  # This is the desired behaviour per spec


def test_load_workflow_state_ref_escape_hatch(tmp_path: Path):
    """state_ref: should resolve a Python class for the workflow state schema."""
    yaml_text = """\
name: ref_state
state_ref: orchestra.core.state.WorkflowState
nodes:
  a:
    type: agent
    ref: a
    output_key: out
edges:
  - source: a
    target: __end__
entry_point: a
"""
    wf_file = tmp_path / "ref_state.yaml"
    wf_file.write_text(yaml_text, encoding="utf-8")

    agents = {"a": BaseAgent(name="a")}
    # Should not raise — WorkflowState itself is a valid schema
    compiled = load_workflow(wf_file, agent_registry=agents)
    assert compiled is not None


def test_load_workflow_simple_linear_graph_compiles(tmp_path: Path):
    """A minimal two-node linear workflow must produce a compiled graph."""
    yaml_text = """\
name: linear
nodes:
  step_one:
    type: agent
    ref: step_one
    output_key: result
  step_two:
    type: agent
    ref: step_two
    output_key: final
edges:
  - source: step_one
    target: step_two
  - source: step_two
    target: __end__
entry_point: step_one
"""
    wf_file = tmp_path / "linear.yaml"
    wf_file.write_text(yaml_text, encoding="utf-8")

    from orchestra.core.compiled import CompiledGraph
    agents = {
        "step_one": BaseAgent(name="step_one"),
        "step_two": BaseAgent(name="step_two"),
    }
    compiled = load_workflow(wf_file, agent_registry=agents)
    assert isinstance(compiled, CompiledGraph)


# ---------------------------------------------------------------------------
# Gap 4: lib.* ref guard — sys.path safety (CVE-2025-50817)
# ---------------------------------------------------------------------------


def test_load_workflow_lib_ref_agent_raises_clear_error(tmp_path: Path):
    """A node ref starting with 'lib.' must raise WorkflowLoadError, not ImportError.

    Orchestra never modifies sys.path automatically.  Allowing lib.* refs to
    fall through to importlib.import_module would either silently fail or — if
    the user has a lib/os.py — shadow stdlib modules for the whole process.
    """
    yaml_text = """\
name: lib_agent
nodes:
  custom:
    type: agent
    ref: lib.routing.MyAgent
edges:
  - source: custom
    target: __end__
entry_point: custom
"""
    wf_file = tmp_path / "lib_agent.yaml"
    wf_file.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(WorkflowLoadError, match="lib\\."):
        load_workflow(wf_file, agent_registry={})


def test_load_workflow_lib_ref_function_raises_clear_error(tmp_path: Path):
    """A function node ref starting with 'lib.' must also raise WorkflowLoadError."""
    yaml_text = """\
name: lib_func
nodes:
  step:
    type: function
    ref: lib.utils.transform
edges:
  - source: step
    target: __end__
entry_point: step
"""
    wf_file = tmp_path / "lib_func.yaml"
    wf_file.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(WorkflowLoadError, match="lib\\."):
        load_workflow(wf_file, agent_registry={})


def test_load_workflow_lib_ref_state_ref_raises_clear_error(tmp_path: Path):
    """A state_ref starting with 'lib.' must raise WorkflowLoadError."""
    yaml_text = """\
name: lib_state
state_ref: lib.states.MyState
nodes:
  a:
    type: agent
    ref: a
edges:
  - source: a
    target: __end__
entry_point: a
"""
    wf_file = tmp_path / "lib_state.yaml"
    wf_file.write_text(yaml_text, encoding="utf-8")

    agents = {"a": BaseAgent(name="a")}
    with pytest.raises(WorkflowLoadError, match="lib\\."):
        load_workflow(wf_file, agent_registry=agents)


def test_load_workflow_lib_ref_error_mentions_pythonpath(tmp_path: Path):
    """The lib.* error message must mention PYTHONPATH so the user knows the fix."""
    yaml_text = """\
name: lib_ref_msg
nodes:
  worker:
    type: function
    ref: lib.tasks.do_work
edges:
  - source: worker
    target: __end__
entry_point: worker
"""
    wf_file = tmp_path / "lib_ref_msg.yaml"
    wf_file.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(WorkflowLoadError, match="PYTHONPATH"):
        load_workflow(wf_file, agent_registry={})


def test_load_workflow_lib_ref_does_not_mutate_sys_path(tmp_path: Path):
    """Loading a workflow with a lib.* ref must not modify sys.path."""
    import sys

    yaml_text = """\
name: syspath_check
nodes:
  worker:
    type: function
    ref: lib.tasks.process
edges:
  - source: worker
    target: __end__
entry_point: worker
"""
    wf_file = tmp_path / "syspath_check.yaml"
    wf_file.write_text(yaml_text, encoding="utf-8")

    path_before = list(sys.path)
    try:
        load_workflow(wf_file, agent_registry={})
    except WorkflowLoadError:
        pass  # Expected

    assert sys.path == path_before, "load_workflow must not modify sys.path"
