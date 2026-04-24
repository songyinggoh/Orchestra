"""Graph introspection endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from orchestra.server.dependencies import get_graph_registry
from orchestra.server.models import GraphInfo

router = APIRouter(prefix="/graphs", tags=["graphs"])


@router.get("", response_model=list[GraphInfo])
async def list_graphs(request: Request) -> list[GraphInfo]:
    """List all registered graphs with their node/edge structure."""
    registry = get_graph_registry(request)
    return registry.list_graphs()


@router.get("/{name}", response_model=GraphInfo)
async def get_graph(name: str, request: Request) -> GraphInfo:
    """Get detailed information about a specific graph, including Mermaid diagram."""
    registry = get_graph_registry(request)
    graph = registry.get(name)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"Graph '{name}' not found.")

    from typing import Any

    edges_list: list[dict[str, Any]] = []
    for edge in graph._edges:
        target = getattr(edge, "target", getattr(edge, "targets", ""))
        if not isinstance(target, (str, list)):
            target = str(target)
        elif isinstance(target, list):
            target = [str(t) if not isinstance(t, str) else t for t in target]
        edge_dict: dict[str, Any] = {
            "type": type(edge).__name__,
            "source": getattr(edge, "source", ""),
            "target": target,
        }
        # Include join_node for ParallelEdge so the UI can bound branch attribution.
        join_node = getattr(edge, "join_node", None)
        if join_node is not None:
            from orchestra.core.types import END as _END
            edge_dict["join_node"] = None if join_node is _END else str(join_node)
        edges_list.append(edge_dict)
    for h_edge in getattr(graph, "_handoff_edges", []):
        edges_list.append(
            {
                "type": type(h_edge).__name__,
                "source": h_edge.source,
                "target": h_edge.target,
                "conditional": h_edge.condition is not None,
            }
        )

    return GraphInfo(
        name=name,
        nodes=list(graph._nodes.keys()),
        edges=edges_list,
        entry_point=graph._entry_point,
        mermaid=graph.to_mermaid(),
    )
