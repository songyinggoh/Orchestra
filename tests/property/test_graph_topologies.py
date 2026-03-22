"""Property-based tests for graph topology compilation using Hypothesis."""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from orchestra.core.graph import WorkflowGraph

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop(state: dict[str, Any]) -> dict[str, Any]:
    """Minimal no-op async function usable as a graph node."""
    return state


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(st.integers(min_value=1, max_value=5))
@settings(max_examples=10)
def test_linear_chain_compiles(n: int) -> None:
    """Any linear chain of N nodes should compile without error."""
    g = WorkflowGraph()
    for i in range(n):
        g.then(_noop, name=f"node_{i}")
    compiled = g.compile()
    assert compiled is not None


@given(
    st.lists(
        st.text(
            min_size=1,
            max_size=10,
            alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        ),
        min_size=1,
        max_size=4,
        unique=True,
    )
)
@settings(max_examples=10)
def test_nodes_with_various_names_compile(names: list[str]) -> None:
    """Graphs with various node names should compile without error."""
    g = WorkflowGraph()
    for name in names:
        g.then(_noop, name=name)
    compiled = g.compile()
    assert compiled is not None
