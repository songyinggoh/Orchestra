"""Basic handoff: Triage agent routes to specialist agents.

This demonstrates the Swarm-style handoff pattern using
Orchestra's conditional edges. The triage agent analyzes
the request and hands off to the appropriate specialist.

Run:
    python examples/handoff_basic.py
"""

import asyncio
from typing import Annotated, Any

from orchestra.core.graph import WorkflowGraph
from orchestra.core.state import WorkflowState, merge_list
from orchestra.core.types import END


class SupportState(WorkflowState):
    user_message: str = ""
    department: str = ""
    response: str = ""
    log: Annotated[list[str], merge_list] = []


async def triage_agent(state: dict[str, Any]) -> dict[str, Any]:
    """Analyze user message and determine department."""
    message = state["user_message"].lower()
    if "bill" in message or "charge" in message or "payment" in message:
        department = "billing"
    elif "bug" in message or "error" in message or "broken" in message or "crash" in message:
        department = "technical"
    else:
        department = "general"
    return {
        "department": department,
        "log": [f"Triage: routed to {department}"],
    }


async def billing_agent(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "response": f"[Billing] Looking into your billing concern: {state['user_message']}",
        "log": ["Billing agent handled request"],
    }


async def technical_agent(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "response": f"[Technical] Investigating your issue: {state['user_message']}",
        "log": ["Technical agent handled request"],
    }


async def general_agent(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "response": f"[General] Happy to help with: {state['user_message']}",
        "log": ["General agent handled request"],
    }


def route_to_department(state: dict[str, Any]) -> str:
    return state["department"]


async def main() -> None:
    graph = WorkflowGraph(state_schema=SupportState)

    graph.add_node("triage", triage_agent)
    graph.add_node("billing", billing_agent)
    graph.add_node("technical", technical_agent)
    graph.add_node("general", general_agent)

    graph.set_entry_point("triage")
    graph.add_conditional_edge(
        "triage",
        route_to_department,
        path_map={
            "billing": "billing",
            "technical": "technical",
            "general": "general",
        },
    )
    graph.add_edge("billing", END)
    graph.add_edge("technical", END)
    graph.add_edge("general", END)

    compiled = graph.compile()

    for msg in [
        "I was charged twice on my bill",
        "The app crashes when I click submit",
        "How do I change my password?",
    ]:
        result = await compiled.run({"user_message": msg})
        print(f"User: {msg}")
        print(f"Routed to: {result['department']}")
        print(f"Response: {result['response']}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
