"""Orchestra reasoning module — structured multi-step reasoning strategies.

TreeOfThoughtsAgent
  A BaseAgent that reasons via Tree of Thoughts (Yao et al., 2023).
  Prevents overplanning by generating small, scoped thoughts at each step,
  evaluating them before expanding, and pruning dead ends early.

ToTSearchStrategy
  BFS — breadth-first beam search (default, best for open-ended problems)
  DFS — depth-first with backtracking (best for constraint satisfaction)

ThoughtNode
  Internal tree node; exposed for observability and custom search strategies.

Usage:
    from orchestra.reasoning import TreeOfThoughtsAgent, ToTSearchStrategy

    agent = TreeOfThoughtsAgent(
        name="planner",
        model="gpt-4o-mini",
        system_prompt="You are a strategic problem solver.",
        tot_breadth=3,
        tot_beam=2,
        tot_max_depth=4,
        tot_strategy=ToTSearchStrategy.BFS,
    )
"""

from orchestra.reasoning.tot import ThoughtNode, ToTSearchStrategy, TreeOfThoughtsAgent

__all__ = [
    "ThoughtNode",
    "ToTSearchStrategy",
    "TreeOfThoughtsAgent",
]
