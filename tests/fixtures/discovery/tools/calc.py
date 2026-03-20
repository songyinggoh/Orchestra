"""Fixture tool file: calculator tool."""
from orchestra.tools.base import tool


@tool(name="calculate")
async def run_calculation(expression: str) -> str:
    """Evaluate a mathematical expression and return the result."""
    return f"Result: {expression}"
