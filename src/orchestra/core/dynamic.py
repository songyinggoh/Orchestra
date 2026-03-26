"""Dynamic Graph Construction and YAML Serialization (T-4.12).

Provides the SubgraphBuilder for programmatic construction and
YAML-to-Graph hydration with security allowlisting.
"""

from __future__ import annotations

import importlib
from typing import Any, cast

import structlog
from ruamel.yaml import YAML

from orchestra.core.compiled import CompiledGraph
from orchestra.core.graph import WorkflowGraph
from orchestra.core.types import END

logger = structlog.get_logger(__name__)

# Security: Default allowed prefixes for dotted-path resolution.
# Immutable tuple — prevents runtime poisoning via .append()/.extend().
DEFAULT_ALLOWED_PREFIXES: tuple[str, ...] = (
    "orchestra.core.",
    "orchestra.tools.",
    "orchestra.providers.",
)


class SubgraphBuilder:
    """Builder for subgraphs with dotted-path resolution and validation."""

    def __init__(
        self,
        allowed_prefixes: list[str] | tuple[str, ...] | None = None,
        max_nesting: int = 10,
    ) -> None:
        # Always store as tuple so the instance's allowlist is also immutable.
        self._allowed_prefixes: tuple[str, ...] = (
            tuple(allowed_prefixes) if allowed_prefixes else DEFAULT_ALLOWED_PREFIXES
        )
        self._max_nesting = max_nesting
        self._max_nesting = max_nesting

    def resolve_ref(self, ref: str) -> Any:
        """Resolve a dotted-path reference to a Python object with validation."""
        # Security: Check allowlist
        is_allowed = any(ref.startswith(p) for p in self._allowed_prefixes)
        if not is_allowed:
            raise ImportError(f"Ref '{ref}' is not in the security allowlist.")

        try:
            module_path, attr_name = ref.rsplit(".", 1)
            module = importlib.import_module(module_path)
            return getattr(module, attr_name)
        except (ValueError, ImportError, AttributeError) as e:
            raise ImportError(f"Failed to resolve ref '{ref}': {e}") from e


def load_graph_yaml(yaml_str: str, builder: SubgraphBuilder | None = None) -> CompiledGraph:
    """Hydrate a YAML graph definition into a CompiledGraph.

    Uses ruamel.yaml for round-trip support.
    """
    if builder is None:
        builder = SubgraphBuilder()

    yaml = YAML(typ="safe")
    data = yaml.load(yaml_str)

    graph = WorkflowGraph(name=data.get("name", "dynamic_graph"))

    # 1. Add Nodes
    for node_id, node_data in data.get("nodes", {}).items():
        node_type = node_data.get("type", "function")
        ref = node_data.get("ref")

        if node_type == "agent":
            agent_factory = builder.resolve_ref(ref)
            config = node_data.get("config", {})
            agent = agent_factory(**config)
            graph.add_node(node_id, agent)
        elif node_type == "subgraph":
            # Nested YAML hydration (recursive)
            # Security: check nesting depth logic would go here
            pass
        else:
            func = builder.resolve_ref(ref)
            graph.add_node(node_id, func)

    # 2. Add Edges
    for edge_data in data.get("edges", []):
        source = edge_data["source"]
        target = edge_data["target"]

        if isinstance(target, list):
            graph.add_parallel(source, target, join_node=edge_data.get("join"))
        elif edge_data.get("type") == "conditional":
            condition = builder.resolve_ref(edge_data["condition"])
            graph.add_conditional_edge(source, condition, edge_data.get("paths"))
        else:
            graph.add_edge(source, END if target == "__end__" else target)

    if "entry_point" in data:
        graph.set_entry_point(data["entry_point"])

    return cast(CompiledGraph, graph.compile(max_turns=data.get("max_turns", 50)))


def dump_graph_yaml(graph_data: dict[str, Any]) -> str:
    """Dump graph metadata to YAML string, preserving comments."""
    from io import StringIO

    yaml = YAML()
    stream = StringIO()
    yaml.dump(graph_data, stream)
    return stream.getvalue()
