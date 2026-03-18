"""WorkflowGraph builder with fluent API.

Provides both explicit (add_node/add_edge) and fluent (.then/.parallel/.branch)
APIs for constructing workflow graphs.

Usage:
    # Fluent
    graph = WorkflowGraph().then(researcher).then(writer)

    # Explicit
    graph = WorkflowGraph(state_schema=MyState)
    graph.add_node("research", researcher)
    graph.add_node("write", writer)
    graph.add_edge("research", "write")
    graph.set_entry_point("research")

    compiled = graph.compile()
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from orchestra.core.edges import ConditionalEdge, Edge, EdgeCondition, ParallelEdge
from orchestra.core.errors import GraphCompileError
from orchestra.core.handoff import HandoffEdge
from orchestra.core.nodes import AgentNode, FunctionNode, GraphNode, NodeFunction, SubgraphNode
from orchestra.core.types import END, START


def _get_node_name(node_or_agent: Any) -> str:
    """Extract a name from an agent, function, or node."""
    if hasattr(node_or_agent, "name"):
        name = node_or_agent.name
        if callable(name):
            return str(name())
        return str(name)
    if hasattr(node_or_agent, "__name__"):
        return str(node_or_agent.__name__)
    return str(id(node_or_agent))


def _wrap_as_node(
    item: Any,
    node_id: str,
    interrupt_before: bool = False,
    interrupt_after: bool = False,
) -> GraphNode:
    """Wrap an agent, function, or node into a GraphNode."""
    if isinstance(item, AgentNode):
        return AgentNode(
            agent=item.agent,
            output_key=item.output_key,
            map_output=item.map_output,
            input_mapper=item.input_mapper,
            output_mapper=item.output_mapper,
            interrupt_before=interrupt_before or item.interrupt_before,
            interrupt_after=interrupt_after or item.interrupt_after,
        )
    if isinstance(item, FunctionNode):
        return FunctionNode(
            func=item.func,
            name=item.name,
            interrupt_before=interrupt_before or item.interrupt_before,
            interrupt_after=interrupt_after or item.interrupt_after,
        )
    if isinstance(item, SubgraphNode):
        return SubgraphNode(
            graph=item.graph,
            input_mapper=item.input_mapper,
            output_mapper=item.output_mapper,
            interrupt_before=interrupt_before or item.interrupt_before,
            interrupt_after=interrupt_after or item.interrupt_after,
        )

    # If it's an agent-like object (has system_prompt and run method)
    if hasattr(item, "system_prompt") and hasattr(item, "run"):
        return AgentNode(
            agent=item,
            interrupt_before=interrupt_before,
            interrupt_after=interrupt_after,
        )

    # If it's a plain async function
    if callable(item):
        return FunctionNode(
            func=item,
            name=node_id,
            interrupt_before=interrupt_before,
            interrupt_after=interrupt_after,
        )

    raise GraphCompileError(
        f"Cannot wrap '{item}' as a graph node.\n"
        f"  Expected: Agent, async function, or GraphNode instance.\n"
        f"  Got: {type(item).__name__}"
    )



class WorkflowGraph:
    """Builder for workflow graphs.

    Provides a fluent API for adding nodes and edges, then
    compiles into an executable CompiledGraph.
    """

    def __init__(
        self, state_schema: type[Any] | None = None, name: str = ""
    ) -> None:
        self._state_schema = state_schema
        self._name = name
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[Edge | ConditionalEdge | ParallelEdge] = []
        self._handoff_edges: list[HandoffEdge] = []
        self._entry_point: str | None = None
        self._last_node: str | None = None
        self._parallel_nodes: list[str] | None = None

    # ---- Explicit API ----

    def add_node(
        self,
        node_id: str,
        node: GraphNode | NodeFunction | Any,
        *,
        output_key: str | None = None,
        interrupt_before: bool = False,
        interrupt_after: bool = False,
    ) -> WorkflowGraph:
        """Add a node to the graph."""
        if node_id in (END, START):
            raise GraphCompileError(
                f"'{node_id}' is a reserved node ID.\n"
                f"  Fix: Choose a different name for your node."
            )
        if node_id in self._nodes:
            raise GraphCompileError(
                f"Node '{node_id}' already exists.\n"
                f"  Fix: Use a unique name for each node."
            )

        wrapped = _wrap_as_node(
            node,
            node_id,
            interrupt_before=interrupt_before,
            interrupt_after=interrupt_after,
        )

        # Apply output_key to AgentNodes
        if output_key and isinstance(wrapped, AgentNode):
            wrapped = AgentNode(
                agent=wrapped.agent,
                output_key=output_key,
                map_output=wrapped.map_output,
                input_mapper=wrapped.input_mapper,
                output_mapper=wrapped.output_mapper,
            )

        self._nodes[node_id] = wrapped

        if self._entry_point is None:
            self._entry_point = node_id

        return self

    def add_edge(self, source: str, target: Any) -> WorkflowGraph:
        """Add an unconditional edge: source -> target."""
        self._edges.append(Edge(source=source, target=target))
        return self

    def add_conditional_edge(
        self,
        source: str,
        condition: EdgeCondition,
        path_map: dict[str, Any] | None = None,
    ) -> WorkflowGraph:
        """Add a conditional edge: source -> condition(state) -> target."""
        self._edges.append(
            ConditionalEdge(source=source, condition=condition, path_map=path_map)
        )
        return self

    def add_parallel(
        self,
        source: str,
        targets: list[str],
        join_node: Any = None,
    ) -> WorkflowGraph:
        """Add parallel fan-out: source -> [targets] concurrently."""
        self._edges.append(
            ParallelEdge(source=source, targets=targets, join_node=join_node)
        )
        return self

    def add_handoff(
        self,
        from_agent: str,
        to_agent: str,
        *,
        condition: EdgeCondition | None = None,
        distill: bool = True,
    ) -> "WorkflowGraph":
        """Add a handoff edge between agents.

        Handoffs are Swarm-style agent-to-agent transfers with optional
        context distillation. The source and target nodes must already
        be registered via add_node() or the fluent API.

        Usage:
            graph.add_handoff("triage", "specialist", condition=needs_expert)
            graph.add_handoff("researcher", "writer")  # Unconditional
        """
        edge = HandoffEdge(source=from_agent, target=to_agent, condition=condition, distill=distill)
        self._handoff_edges.append(edge)
        return self

    def set_entry_point(self, node_id: str) -> WorkflowGraph:
        """Set the starting node for execution."""
        self._entry_point = node_id
        return self

    # ---- Fluent API ----

    def then(
        self,
        agent_or_fn: Any,
        *,
        name: str | None = None,
        interrupt_before: bool = False,
        interrupt_after: bool = False,
    ) -> WorkflowGraph:
        """Add a node and connect it sequentially to the previous node.

        Usage:
            graph = WorkflowGraph().then(researcher).then(writer).then(editor)
        """
        node_id = name or _get_node_name(agent_or_fn)
        self.add_node(
            node_id,
            agent_or_fn,
            interrupt_before=interrupt_before,
            interrupt_after=interrupt_after,
        )

        if self._last_node is not None:
            self.add_edge(self._last_node, node_id)

        self._last_node = node_id
        return self

    def subgraph(
        self,
        name: str,
        graph_or_factory: Any,
        *,
        input_mapper: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        output_mapper: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        interrupt_before: bool = False,
        interrupt_after: bool = False,
    ) -> WorkflowGraph:
        """Add a nested subgraph.

        Usage:
            graph.subgraph("sub", lambda: WorkflowGraph().then(a).compile())
        """
        # If it's a factory function, call it
        if callable(graph_or_factory) and not hasattr(graph_or_factory, "run"):
            nested_graph = graph_or_factory()
        else:
            nested_graph = graph_or_factory

        # Ensure it's compiled
        if hasattr(nested_graph, "compile"):
            nested_graph = nested_graph.compile()

        node = SubgraphNode(
            graph=nested_graph,
            input_mapper=input_mapper,
            output_mapper=output_mapper,
            interrupt_before=interrupt_before,
            interrupt_after=interrupt_after,
        )
        self.add_node(name, node)

        if self._last_node is not None:
            self.add_edge(self._last_node, name)

        self._last_node = name
        return self

    def parallel(self, *agents_or_fns: Any, names: list[str] | None = None) -> WorkflowGraph:
        """Fan out to multiple nodes in parallel.

        Must be followed by .join() to merge results.

        Usage:
            graph = (
                WorkflowGraph()
                .then(planner)
                .parallel(researcher_a, researcher_b, researcher_c)
                .join(synthesizer)
            )
        """
        node_names = []
        for i, item in enumerate(agents_or_fns):
            node_id = names[i] if names and i < len(names) else _get_node_name(item)
            # Deduplicate if needed
            if node_id in self._nodes:
                node_id = f"{node_id}_{i}"
            self.add_node(node_id, item)
            node_names.append(node_id)

        if self._parallel_nodes is not None:
            raise GraphCompileError(
                "Cannot call .parallel() again before calling .join().\n"
                "  Fix: Call .join(joiner) to merge the previous parallel group first."
            )

        if self._last_node is not None:
            self._edges.append(
                ParallelEdge(source=self._last_node, targets=node_names, join_node=None)
            )

        # Store parallel node names for join()
        self._parallel_nodes = node_names
        self._last_node = None  # Must call .join() next
        return self

    def join(self, agent_or_fn: Any, *, name: str | None = None) -> WorkflowGraph:
        """Join parallel branches into a single node.

        Must be called after .parallel().
        """
        if self._parallel_nodes is None:
            raise GraphCompileError(
                "Cannot join without a preceding .parallel() call.\n"
                "  Fix: Call .parallel(agent_a, agent_b) before .join(joiner)."
            )

        node_id = name or _get_node_name(agent_or_fn)
        self.add_node(node_id, agent_or_fn)

        # Update the parallel edge with join_node
        for i, edge in enumerate(self._edges):
            if (
                isinstance(edge, ParallelEdge)
                and edge.targets == self._parallel_nodes
                and edge.join_node is None
            ):
                self._edges[i] = ParallelEdge(
                    source=edge.source,
                    targets=edge.targets,
                    join_node=node_id,
                )
                break
        self._parallel_nodes = None

        self._last_node = node_id
        return self

    def branch(
        self,
        condition: EdgeCondition,
        path_map: dict[str, Any],
    ) -> WorkflowGraph:
        """Add conditional branching from the last node.

        Usage:
            graph = (
                WorkflowGraph()
                .then(classifier)
                .branch(
                    lambda s: s.get("category"),
                    {"technical": tech_agent, "creative": creative_agent}
                )
            )
        """
        if self._last_node is None:
            raise GraphCompileError(
                "Cannot branch without a preceding node.\n"
                "  Fix: Call .then() before .branch()."
            )

        resolved_map: dict[str, Any] = {}
        for key, target in path_map.items():
            if target is END or target == END:
                resolved_map[key] = END
            elif isinstance(target, str):
                resolved_map[key] = target
            else:
                node_id = _get_node_name(target)
                if node_id not in self._nodes:
                    self.add_node(node_id, target)
                resolved_map[key] = node_id

        self.add_conditional_edge(self._last_node, condition, resolved_map)
        self._last_node = None
        return self

    def if_then(
        self,
        condition: Callable[[dict[str, Any]], bool],
        then_agent: Any,
        else_agent: Any | None = None,
    ) -> WorkflowGraph:
        """Simple if/else branching.

        Usage:
            graph = (
                WorkflowGraph()
                .then(checker)
                .if_then(lambda s: s["approved"], publisher, reviser)
            )
        """
        then_id = _get_node_name(then_agent)
        if then_id not in self._nodes:
            self.add_node(then_id, then_agent)

        path_map: dict[str, Any] = {"__then__": then_id}

        if else_agent is not None:
            else_id = _get_node_name(else_agent)
            if else_id not in self._nodes:
                self.add_node(else_id, else_agent)
            path_map["__else__"] = else_id
        else:
            path_map["__else__"] = END

        def _condition_wrapper(state: dict[str, Any]) -> str:
            return "__then__" if condition(state) else "__else__"

        if self._last_node is not None:
            self.add_conditional_edge(self._last_node, _condition_wrapper, path_map)

        self._last_node = None
        return self

    def loop(
        self,
        agent_or_fn: Any,
        *,
        condition: Callable[[dict[str, Any]], bool],
        max_iterations: int = 10,
        name: str | None = None,
    ) -> WorkflowGraph:
        """Add a loop node that repeats until condition returns False.

        Usage:
            graph = (
                WorkflowGraph()
                .then(writer)
                .loop(reviewer, condition=lambda s: not s["approved"], max_iterations=5)
            )
        """
        node_id = name or _get_node_name(agent_or_fn)
        if node_id not in self._nodes:
            self.add_node(node_id, agent_or_fn)

        if self._last_node is not None and self._last_node != node_id:
            self.add_edge(self._last_node, node_id)

        # Loop counters are stored per-run on the ExecutionContext (injected
        # into state_dict as "__loop_counters__" by CompiledGraph._resolve_next).
        # This makes the graph reentrant — concurrent runs each have their own
        # counter scope.
        loop_id = f"__loop_{node_id}"

        def _loop_condition(state: dict[str, Any]) -> Any:
            counters = state.get("__loop_counters__", {})
            count = counters.get(loop_id, 0) + 1
            counters[loop_id] = count
            if count >= max_iterations:
                counters.pop(loop_id, None)
                return END
            if condition(state):
                return node_id
            counters.pop(loop_id, None)
            return END

        self.add_conditional_edge(node_id, _loop_condition)
        self._last_node = node_id
        return self

    # ---- Compilation ----

    def compile(self, *, max_turns: int = 50) -> Any:
        """Validate the graph and return a CompiledGraph for execution."""
        self._validate()

        # If last node has no outgoing edge, add edge to END
        if self._last_node is not None:
            has_outgoing = any(
                (isinstance(e, Edge) and e.source == self._last_node)
                or (isinstance(e, ConditionalEdge) and e.source == self._last_node)
                or (isinstance(e, ParallelEdge) and e.source == self._last_node)
                for e in self._edges
            )
            if not has_outgoing:
                self.add_edge(self._last_node, END)

        from orchestra.core.compiled import CompiledGraph

        return CompiledGraph(
            nodes=dict(self._nodes),
            edges=list(self._edges),
            entry_point=self._entry_point or "",
            state_schema=self._state_schema,
            max_turns=max_turns,
            name=self._name,
            handoff_edges=list(self._handoff_edges),
        )

    def _validate(self) -> None:
        """Validate graph structure."""
        if not self._nodes:
            raise GraphCompileError(
                "Graph has no nodes.\n"
                "  Fix: Add at least one node with .add_node() or .then()."
            )

        if not self._entry_point:
            raise GraphCompileError(
                "No entry point set.\n"
                "  Fix: Call set_entry_point() or use the fluent API (.then())."
            )

        if self._entry_point not in self._nodes:
            raise GraphCompileError(
                f"Entry point '{self._entry_point}' does not exist in nodes.\n"
                f"  Available nodes: {list(self._nodes.keys())}\n"
                f"  Fix: Use an existing node name as entry point."
            )

        valid_targets = set(self._nodes.keys()) | {END}
        for edge in self._edges:
            if isinstance(edge, Edge):
                if edge.source not in self._nodes:
                    raise GraphCompileError(
                        f"Edge source '{edge.source}' not found in nodes.\n"
                        f"  Fix: Add a node named '{edge.source}' or fix the edge."
                    )
                if edge.target not in valid_targets and edge.target != END:
                    raise GraphCompileError(
                        f"Edge target '{edge.target}' not found in nodes.\n"
                        f"  Fix: Add a node named '{edge.target}' or use END."
                    )
            elif isinstance(edge, ConditionalEdge):
                if edge.source not in self._nodes:
                    raise GraphCompileError(
                        f"Conditional edge source '{edge.source}' not found.\n"
                        f"  Fix: Add a node named '{edge.source}'."
                    )
                if edge.path_map:
                    for target in edge.path_map.values():
                        if target not in valid_targets and target != END:
                            raise GraphCompileError(
                                f"Conditional edge target '{target}' not found.\n"
                                f"  Fix: Add a node named '{target}' or use END."
                            )
            elif isinstance(edge, ParallelEdge):
                if edge.source not in self._nodes:
                    raise GraphCompileError(
                        f"Parallel edge source '{edge.source}' not found.\n"
                        f"  Fix: Add a node named '{edge.source}'."
                    )
                for target in edge.targets:
                    if target not in valid_targets:
                        raise GraphCompileError(
                            f"Parallel target '{target}' not found.\n"
                            f"  Fix: Add a node named '{target}'."
                        )
