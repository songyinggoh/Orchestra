"""Live end-to-end demo: real agents, real LLM, real orchestration.

Proves the Orchestra framework works against a real model — not mocks.
Auto-detects your provider (Anthropic, OpenAI, Google, or Ollama).

Usage:
    python examples/live.py                          # auto-detect
    python examples/live.py --provider ollama         # explicit provider
    python examples/live.py --provider openai --model gpt-4o
    python examples/live.py --provider anthropic

Requirements:
    At least ONE of:
    - Ollama running locally (ollama serve + ollama pull llama3.1)
    - OPENAI_API_KEY environment variable set
    - ANTHROPIC_API_KEY environment variable set
    - GOOGLE_API_KEY environment variable set
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Annotated, Any

from orchestra.core.agent import BaseAgent
from orchestra.core.graph import WorkflowGraph
from orchestra.core.runner import run
from orchestra.core.state import WorkflowState, merge_dict, merge_list
from orchestra.core.types import END
from orchestra.tools.base import tool

# ---------------------------------------------------------------------------
# Provider auto-detection
# ---------------------------------------------------------------------------


def _parse_cli_args() -> tuple[str | None, str | None]:
    """Parse --provider and --model from sys.argv."""
    provider = None
    model = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--provider" and i + 1 < len(args):
            provider = args[i + 1]
        elif arg == "--model" and i + 1 < len(args):
            model = args[i + 1]
    return provider, model


async def resolve_provider(
    want_provider: str | None = None,
    want_model: str | None = None,
) -> tuple[Any, str]:
    """Detect and return (provider_instance, model_name).

    Checks in order: Anthropic, OpenAI, Google, Ollama.
    Returns the first that works, or exits with instructions.
    """

    # --- Explicit provider requested ---
    if want_provider:
        return _build_explicit(want_provider, want_model)

    # --- Auto-detect from env vars ---
    if os.environ.get("ANTHROPIC_API_KEY"):
        from orchestra.providers.anthropic import AnthropicProvider

        model = want_model or "claude-haiku-4-5-20251001"
        print("  Detected: ANTHROPIC_API_KEY")
        print(f"  Provider: AnthropicProvider / {model}")
        return AnthropicProvider(), model

    if os.environ.get("OPENAI_API_KEY"):
        from orchestra.providers.http import HttpProvider

        model = want_model or "gpt-4o-mini"
        print("  Detected: OPENAI_API_KEY")
        print(f"  Provider: HttpProvider (OpenAI) / {model}")
        return HttpProvider(), model

    if os.environ.get("GOOGLE_API_KEY"):
        from orchestra.providers.google import GoogleProvider

        model = want_model or "gemini-2.0-flash"
        print("  Detected: GOOGLE_API_KEY")
        print(f"  Provider: GoogleProvider / {model}")
        return GoogleProvider(), model

    # --- Check Ollama ---
    try:
        from orchestra.providers.ollama import OllamaProvider

        ollama = OllamaProvider()
        if await ollama.health_check():
            models = await ollama.list_models()
            if models:
                model = want_model or models[0]
                print("  Detected: Ollama running at localhost:11434")
                print(f"  Provider: OllamaProvider / {model}")
                return ollama, model
            else:
                print("  Ollama is running but no models are pulled.")
                print("  Fix: ollama pull llama3.1")
                sys.exit(1)
    except Exception:
        pass

    # --- Nothing found ---
    print("  No provider found. Set up at least one:")
    print()
    print("  Option 1 (local, free):")
    print("    brew install ollama  # or https://ollama.com")
    print("    ollama serve")
    print("    ollama pull llama3.1")
    print()
    print("  Option 2 (API key):")
    print("    export OPENAI_API_KEY=sk-...")
    print("    export ANTHROPIC_API_KEY=sk-ant-...")
    print("    export GOOGLE_API_KEY=AIza...")
    sys.exit(1)


def _build_explicit(name: str, model: str | None) -> tuple[Any, str]:
    """Build a provider from an explicit --provider flag."""
    name = name.lower()
    if name == "ollama":
        from orchestra.providers.ollama import OllamaProvider

        return OllamaProvider(), model or "llama3.1"
    elif name in ("openai", "http"):
        from orchestra.providers.http import HttpProvider

        return HttpProvider(), model or "gpt-4o-mini"
    elif name == "anthropic":
        from orchestra.providers.anthropic import AnthropicProvider

        return AnthropicProvider(), model or "claude-haiku-4-5-20251001"
    elif name == "google":
        from orchestra.providers.google import GoogleProvider

        return GoogleProvider(), model or "gemini-2.0-flash"
    else:
        print(f"  Unknown provider: {name}")
        print("  Available: ollama, openai, anthropic, google")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Demo 1: Conditional Routing (triage → specialist)
# ---------------------------------------------------------------------------


class RoutingState(WorkflowState):
    question: str = ""
    category: str = ""
    answer: str = ""


async def demo_routing(provider: Any, model: str) -> None:
    """Classifier agent routes to a specialist based on the question."""

    classifier = BaseAgent(
        name="classifier",
        model=model,
        system_prompt=(
            "You are a request classifier. Read the user's question and respond "
            "with EXACTLY one word: either 'technical' or 'creative'. "
            "Nothing else — just that one word."
        ),
        temperature=0.0,
        max_iterations=1,
    )

    technical_expert = BaseAgent(
        name="technical_expert",
        model=model,
        system_prompt=(
            "You are a senior software engineer. Give a concise, helpful answer "
            "to the user's technical question. Keep it under 3 sentences."
        ),
        temperature=0.7,
        max_iterations=1,
    )

    creative_expert = BaseAgent(
        name="creative_expert",
        model=model,
        system_prompt=(
            "You are a creative writing coach. Give an imaginative, inspiring "
            "response to the user's request. Keep it under 3 sentences."
        ),
        temperature=0.9,
        max_iterations=1,
    )

    def route_by_category(state: dict[str, Any]) -> str:
        category = state.get("category", "").strip().lower()
        if "technical" in category:
            return "technical"
        return "creative"

    graph = WorkflowGraph(state_schema=RoutingState)
    graph.add_node("classifier", classifier, output_key="category")
    graph.add_node("technical", technical_expert, output_key="answer")
    graph.add_node("creative", creative_expert, output_key="answer")
    graph.set_entry_point("classifier")
    graph.add_conditional_edge(
        "classifier",
        route_by_category,
        path_map={"technical": "technical", "creative": "creative"},
    )
    graph.add_edge("technical", END)
    graph.add_edge("creative", END)

    question = "How do I handle race conditions in async Python code?"
    print(f"  Question: {question}")

    result = await run(graph, input={"question": question}, provider=provider, persist=False)

    category = result.state.get("category", "").strip()
    answer = result.state.get("answer", "").strip()
    print(f"  Classifier decided: {category}")
    print(f"  Specialist answered: {answer[:200]}")
    print(f"  Nodes executed: {result.node_execution_order}")


# ---------------------------------------------------------------------------
# Demo 2: Parallel Fan-Out (3 researchers → synthesizer)
# ---------------------------------------------------------------------------


class ResearchState(WorkflowState):
    topic: str = ""
    findings: Annotated[dict[str, str], merge_dict] = {}
    synthesis: str = ""
    log: Annotated[list[str], merge_list] = []


async def demo_parallel(provider: Any, model: str) -> None:
    """Three researchers work in parallel, synthesizer combines findings."""

    tech_researcher = BaseAgent(
        name="tech_researcher",
        model=model,
        system_prompt=(
            "You are a technology analyst. Given a topic, identify 2-3 key "
            "technical trends or capabilities. Be specific and concise (2-3 sentences)."
        ),
        temperature=0.7,
        max_iterations=1,
    )

    market_researcher = BaseAgent(
        name="market_researcher",
        model=model,
        system_prompt=(
            "You are a market analyst. Given a topic, identify 2-3 key market "
            "trends, adoption patterns, or business opportunities. Be concise (2-3 sentences)."
        ),
        temperature=0.7,
        max_iterations=1,
    )

    risk_researcher = BaseAgent(
        name="risk_researcher",
        model=model,
        system_prompt=(
            "You are a risk analyst. Given a topic, identify 2-3 key risks, "
            "challenges, or limitations. Be concise (2-3 sentences)."
        ),
        temperature=0.7,
        max_iterations=1,
    )

    synthesizer = BaseAgent(
        name="synthesizer",
        model=model,
        system_prompt=(
            "You are a research synthesizer. You will receive findings from "
            "three analysts (technical, market, risk). Combine their insights "
            "into a brief executive summary (3-4 sentences)."
        ),
        temperature=0.5,
        max_iterations=1,
    )

    # We use FunctionNodes that call the agents manually so we can map
    # input/output correctly to the state schema.

    async def dispatch(state: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def run_tech(state: dict[str, Any]) -> dict[str, Any]:
        from orchestra.core.context import ExecutionContext

        ctx = ExecutionContext(provider=provider)
        result = await tech_researcher.run(state["topic"], ctx)
        return {
            "findings": {"technical": result.output},
            "log": ["tech_researcher done"],
        }

    async def run_market(state: dict[str, Any]) -> dict[str, Any]:
        from orchestra.core.context import ExecutionContext

        ctx = ExecutionContext(provider=provider)
        result = await market_researcher.run(state["topic"], ctx)
        return {
            "findings": {"market": result.output},
            "log": ["market_researcher done"],
        }

    async def run_risk(state: dict[str, Any]) -> dict[str, Any]:
        from orchestra.core.context import ExecutionContext

        ctx = ExecutionContext(provider=provider)
        result = await risk_researcher.run(state["topic"], ctx)
        return {
            "findings": {"risk": result.output},
            "log": ["risk_researcher done"],
        }

    async def run_synthesizer(state: dict[str, Any]) -> dict[str, Any]:
        from orchestra.core.context import ExecutionContext

        ctx = ExecutionContext(provider=provider)
        findings_text = "\n".join(f"[{area}] {text}" for area, text in state["findings"].items())
        result = await synthesizer.run(
            f"Topic: {state['topic']}\n\nFindings:\n{findings_text}", ctx
        )
        return {
            "synthesis": result.output,
            "log": ["synthesizer done"],
        }

    graph = WorkflowGraph(state_schema=ResearchState)
    graph.add_node("dispatch", dispatch)
    graph.add_node("tech", run_tech)
    graph.add_node("market", run_market)
    graph.add_node("risk", run_risk)
    graph.add_node("synthesizer", run_synthesizer)
    graph.set_entry_point("dispatch")
    graph.add_parallel("dispatch", ["tech", "market", "risk"], join_node="synthesizer")
    graph.add_edge("synthesizer", END)

    topic = "Multi-agent AI systems in production"
    print(f"  Topic: {topic}")

    result = await run(graph, input={"topic": topic}, provider=provider, persist=False)

    for area, text in result.state.get("findings", {}).items():
        print(f"  [{area}] {text[:150]}")
    print("  ---")
    print(f"  Synthesis: {result.state.get('synthesis', '')[:300]}")
    print(f"  Nodes executed: {result.node_execution_order}")


# ---------------------------------------------------------------------------
# Demo 3: Tool Calling (agent uses a @tool)
# ---------------------------------------------------------------------------


def _safe_eval(expression: str) -> float:
    """Safely evaluate a math expression using AST parsing.

    Only supports basic arithmetic: +, -, *, /, unary -, and parentheses.
    Raises ValueError on anything else.
    """
    import ast
    import operator

    _ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.USub: operator.neg,
    }

    def _eval_node(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _ops:
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            return _ops[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ops:
            return _ops[type(node.op)](_eval_node(node.operand))
        raise ValueError(f"Unsupported expression: {ast.dump(node)}")

    tree = ast.parse(expression, mode="eval")
    return _eval_node(tree)


@tool
async def calculate(expression: str) -> str:
    """Evaluate a math expression and return the numeric result."""
    try:
        result = _safe_eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {e}"


async def demo_tools(provider: Any, model: str) -> None:
    """Agent with a calculator tool — LLM decides to call it."""

    math_agent = BaseAgent(
        name="math_assistant",
        model=model,
        system_prompt=(
            "You are a math assistant. When the user asks a math question, "
            "you MUST use the calculate tool to compute the answer. "
            "Do not do arithmetic in your head — always use the tool. "
            "After getting the tool result, report the final answer."
        ),
        tools=[calculate],
        temperature=0.0,
        max_iterations=3,
    )

    question = "What is 47 * 89 + 123?"
    print(f"  Question: {question}")

    try:
        from orchestra.core.context import ExecutionContext

        ctx = ExecutionContext(provider=provider)
        result = await math_agent.run(question, ctx)

        if result.tool_calls_made:
            for tc in result.tool_calls_made:
                print(f"  Tool called: {tc.tool_call.name}({tc.tool_call.arguments})")
                print(f"  Tool result: {tc.result}")
        else:
            print("  (No tool calls — model answered directly)")

        print(f"  Final answer: {result.output[:200]}")
    except Exception as e:
        err = str(e)
        if "tool" in err.lower() or "function" in err.lower() or "400" in err:
            print("  Tool calling not supported by this model. Skipping.")
            print(
                "  (Try a model with tool support: llama3.1,"
                " gpt-4o-mini, claude-haiku-4-5-20251001)"
            )
        else:
            raise


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    print("=" * 60)
    print("  Orchestra — Live E2E Demo")
    print("=" * 60)
    print()

    # --- Preflight ---
    print("[Preflight]")
    cli_provider, cli_model = _parse_cli_args()
    provider, model = await resolve_provider(cli_provider, cli_model)
    print()

    # --- Demo 1: Routing ---
    print("[Demo 1: Conditional Routing]")
    t0 = time.monotonic()
    try:
        await demo_routing(provider, model)
    except Exception as e:
        print(f"  Error: {e}")
    print(f"  Time: {(time.monotonic() - t0) * 1000:.0f}ms")
    print()

    # --- Demo 2: Parallel ---
    print("[Demo 2: Parallel Fan-Out]")
    t0 = time.monotonic()
    try:
        await demo_parallel(provider, model)
    except Exception as e:
        print(f"  Error: {e}")
    print(f"  Time: {(time.monotonic() - t0) * 1000:.0f}ms")
    print()

    # --- Demo 3: Tools ---
    print("[Demo 3: Tool Calling]")
    t0 = time.monotonic()
    try:
        await demo_tools(provider, model)
    except Exception as e:
        print(f"  Error: {e}")
    print(f"  Time: {(time.monotonic() - t0) * 1000:.0f}ms")
    print()

    # --- Done ---
    print("=" * 60)
    print("  All demos complete.")
    print("=" * 60)

    # Cleanup provider if it has aclose
    if hasattr(provider, "aclose"):
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())
