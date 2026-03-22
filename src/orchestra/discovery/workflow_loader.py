"""Workflow loader: YAML -> CompiledGraph with name-based agent resolution.

Extends the existing ``load_graph_yaml`` / ``SubgraphBuilder`` pattern to
resolve agent names from the discovery registry before falling back to
dotted-path resolution.  Also supports ``state:`` sections in YAML for
dynamic WorkflowState generation and ``state_ref:`` for Python escape hatches.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import structlog
from ruamel.yaml import YAML

from orchestra.core.agent import BaseAgent
from orchestra.core.compiled import CompiledGraph
from orchestra.core.dynamic import SubgraphBuilder
from orchestra.core.graph import WorkflowGraph
from orchestra.core.state import (
    WorkflowState,
    concat_str,
    keep_first,
    last_write_wins,
    max_value,
    merge_dict,
    merge_list,
    merge_set,
    min_value,
    sum_numbers,
)
from orchestra.core.types import END
from orchestra.discovery.errors import WorkflowLoadError

logger = structlog.get_logger(__name__)


def _resolve_target(target: str) -> Any:
    """Map the YAML ``__end__`` sentinel string to the runtime END object."""
    if target == "__end__":
        return END
    return target


def _check_lib_ref(ref: str) -> None:
    """Raise WorkflowLoadError with a clear message for any ``lib.*`` ref.

    ``lib.*`` refs require the project's ``lib/`` directory to be on
    ``sys.path``, which Orchestra never does automatically (doing so would
    allow a malicious ``lib/os.py`` to shadow the stdlib module for the
    entire process — see CVE-2025-50817).  Users who need to load code from
    ``lib/`` must configure ``PYTHONPATH`` themselves before starting the
    server.
    """
    if ref.startswith("lib."):
        raise WorkflowLoadError(
            f"Ref '{ref}' starts with 'lib.' which requires manual PYTHONPATH "
            "configuration. Orchestra does not modify sys.path automatically. "
            "See documentation for safe lib/ usage."
        )


# Maps YAML type strings -> Python types
TYPE_MAP: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
}

# Maps YAML reducer names -> reducer functions
REDUCER_MAP: dict[str, Any] = {
    "merge_list": merge_list,
    "merge_dict": merge_dict,
    "sum": sum_numbers,
    "last_write_wins": last_write_wins,
    "merge_set": merge_set,
    "concat": concat_str,
    "keep_first": keep_first,
    "max": max_value,
    "min": min_value,
}


def build_state_class(state_def: dict[str, Any]) -> type[WorkflowState]:
    """Build a ``WorkflowState`` subclass from a YAML ``state:`` section.

    Supported YAML formats::

        state:
          topic: str                 # simple type
          output: str
          findings:                  # type + reducer
            type: dict
            reducer: merge_dict
          step_count:                # type + reducer + default
            type: int
            reducer: sum
            default: 0
    """
    annotations: dict[str, Any] = {}
    defaults: dict[str, Any] = {}

    for field_name, field_spec in state_def.items():
        if isinstance(field_spec, str):
            py_type = TYPE_MAP.get(field_spec, str)
            annotations[field_name] = py_type
            defaults[field_name] = py_type()
        elif isinstance(field_spec, dict):
            py_type = TYPE_MAP.get(field_spec.get("type", "str"), str)
            reducer_name = field_spec.get("reducer")
            if reducer_name and reducer_name in REDUCER_MAP:
                annotations[field_name] = Annotated[py_type, REDUCER_MAP[reducer_name]]
            else:
                annotations[field_name] = py_type
            defaults[field_name] = field_spec.get("default", py_type())
        else:
            # Treat as string field with no reducer
            annotations[field_name] = str
            defaults[field_name] = ""

    ns = {"__annotations__": annotations, **defaults}
    return type("DynamicState", (WorkflowState,), ns)


def _resolve_state(
    data: dict[str, Any],
    builder: SubgraphBuilder,
) -> type[WorkflowState] | None:
    """Resolve the state schema from workflow YAML.

    Priority:
    1. ``state_ref:`` — Python dotted path to a WorkflowState subclass
    2. ``state:`` — YAML-defined state schema (build dynamically)
    3. None — no state specified (WorkflowGraph will use default)
    """
    if "state_ref" in data:
        ref = data["state_ref"]
        _check_lib_ref(ref)
        try:
            cls = builder.resolve_ref(ref)
            if not (isinstance(cls, type) and issubclass(cls, WorkflowState)):
                raise WorkflowLoadError(
                    f"state_ref '{ref}' does not point to a WorkflowState subclass"
                )
            return cls
        except ImportError as exc:
            raise WorkflowLoadError(f"Cannot resolve state_ref '{ref}': {exc}") from exc

    if "state" in data:
        return build_state_class(data["state"])

    return None


def load_workflow(
    yaml_path: Path,
    agent_registry: dict[str, BaseAgent],
    tool_registry: dict[str, Any] | None = None,
    builder: SubgraphBuilder | None = None,
) -> CompiledGraph:
    """Load a workflow from a YAML file with name-based agent resolution.

    Node ``ref:`` values are resolved in order:
    1. Agent registry (name matches discovered agent)
    2. Dotted-path via ``SubgraphBuilder.resolve_ref()``

    Args:
        yaml_path: Path to the workflow YAML file.
        agent_registry: Discovered agents keyed by name.
        tool_registry: Discovered tools (unused currently, for future extension).
        builder: SubgraphBuilder for dotted-path resolution.

    Returns:
        A compiled workflow graph.

    Raises:
        WorkflowLoadError: On parse or resolution errors.
    """
    if builder is None:
        builder = SubgraphBuilder()

    try:
        yaml = YAML(typ="safe")
        data: dict[str, Any] | None = yaml.load(yaml_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise WorkflowLoadError(f"Cannot parse {yaml_path}: {exc}") from exc

    if not data or not isinstance(data, dict):
        raise WorkflowLoadError(f"Workflow YAML {yaml_path} is empty or not a mapping")

    # Resolve state schema
    state_class = _resolve_state(data, builder)

    graph = WorkflowGraph(
        name=data.get("name", yaml_path.stem),
        state_schema=state_class,
    )

    # Add nodes
    for node_id, node_data in data.get("nodes", {}).items():
        node_type = node_data.get("type", "agent")
        ref = node_data.get("ref", node_id)
        output_key = node_data.get("output_key")

        if node_type == "agent":
            # Try agent registry first, then dotted path
            if ref in agent_registry:
                agent = agent_registry[ref]
            else:
                _check_lib_ref(ref)
                try:
                    agent = builder.resolve_ref(ref)
                except ImportError as err:
                    available = sorted(agent_registry.keys())
                    raise WorkflowLoadError(
                        f"Node '{node_id}' references agent '{ref}' which was not "
                        f"found in the agent registry or as a dotted path. "
                        f"Available agents: {available}"
                    ) from err
            graph.add_node(node_id, agent, output_key=output_key)
        elif node_type == "function":
            _check_lib_ref(ref)
            try:
                func = builder.resolve_ref(ref)
            except ImportError as exc:
                raise WorkflowLoadError(
                    f"Node '{node_id}' cannot resolve function ref '{ref}': {exc}"
                ) from exc
            graph.add_node(node_id, func, output_key=output_key)
        else:
            raise WorkflowLoadError(
                f"Unknown node type '{node_type}' for node '{node_id}'. Supported: agent, function"
            )

    # Add edges
    for edge_data in data.get("edges", []):
        source = edge_data["source"]
        raw_target = edge_data["target"]

        if isinstance(raw_target, list):
            # Parallel fan-out
            targets = [_resolve_target(t) for t in raw_target]
            join_node = edge_data.get("join")
            graph.add_parallel(source, targets, join_node=join_node)
        elif edge_data.get("type") == "conditional":
            condition_ref = edge_data.get("condition_ref")
            if not condition_ref:
                raise WorkflowLoadError(f"Conditional edge from '{source}' missing 'condition_ref'")
            _check_lib_ref(condition_ref)
            try:
                condition_fn = builder.resolve_ref(condition_ref)
            except ImportError as exc:
                raise WorkflowLoadError(
                    f"Cannot resolve condition_ref '{condition_ref}': {exc}"
                ) from exc
            paths = edge_data.get("paths", {})
            graph.add_conditional_edge(source, condition_fn, path_map=paths)
        else:
            target = _resolve_target(raw_target)
            graph.add_edge(source, target)

    # Entry point
    if "entry_point" in data:
        graph.set_entry_point(data["entry_point"])

    return graph.compile(max_turns=data.get("max_turns", 50))
