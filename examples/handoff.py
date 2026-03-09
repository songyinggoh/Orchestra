"""Customer support workflow with agent handoff.

Demonstrates:
- Triage agent classifies incoming requests
- Handoff to specialist agent (billing, technical, general)
- Context distillation preserves relevant history
- Rich trace shows handoff flow

Usage:
    python examples/handoff.py
    # Or with ScriptedLLM for testing:
    python examples/handoff.py --test
"""

import asyncio
import sys
from typing import Any

from orchestra.core.agent import agent
from orchestra.core.graph import WorkflowGraph
from orchestra.core.types import LLMResponse, Message, MessageRole, ToolCall
from orchestra.testing.scripted import ScriptedLLM


@agent(name="triage")
async def triage_agent(messages: list[Message]) -> str:
    """You are a triage assistant. Determine the user's intent.
    
    If it's about billing, hand off to 'billing'.
    If it's technical, hand off to 'technical'.
    Otherwise, help them yourself.
    """
    return "Classifying request..."


@agent(name="billing")
async def billing_agent(messages: list[Message]) -> str:
    """You are a billing specialist. Help the user with their payment issues."""
    return "I can help with your invoice."


@agent(name="technical")
async def technical_agent(messages: list[Message]) -> str:
    """You are a technical support engineer. Help the user with their code or bugs."""
    return "Let's debug your integration."


async def main() -> None:
    # Build graph
    graph = WorkflowGraph()
    
    # 1. Define nodes
    graph.add_node("triage", triage_agent)
    graph.add_node("billing", billing_agent)
    graph.add_node("technical", technical_agent)
    
    # 2. Define handoffs
    def is_billing(state: dict) -> bool:
        last_msg = state.get("triage_output", "").lower()
        return "billing" in last_msg
        
    def is_technical(state: dict) -> bool:
        last_msg = state.get("triage_output", "").lower()
        return "technical" in last_msg

    graph.add_handoff("triage", "billing", condition=is_billing)
    graph.add_handoff("triage", "technical", condition=is_technical)
    
    graph.set_entry_point("triage")
    compiled = graph.compile()

    # 3. Setup Mock LLM for demonstration
    responses = [
        # Triage classifies as technical
        LLMResponse(content="This sounds like a technical issue. I'll hand you over."),
        # Technical agent responds
        LLMResponse(content="I've analyzed your logs. The error is in the API key format.")
    ]
    provider = ScriptedLLM(responses)

    # 4. Run
    print("\n--- Running Handoff Example ---")
    state = await compiled.run(
        input="My API calls are failing with a 401 error.",
        provider=provider
    )
    
    print(f"\nFinal Response: {state.get('technical_output') or state.get('output')}")


if __name__ == "__main__":
    asyncio.run(main())
