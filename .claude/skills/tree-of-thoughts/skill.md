# Tree of Thoughts Skill

## Description
Apply Tree of Thoughts (ToT) reasoning to solve complex problems or set up a ToT agent in the Orchestra framework. Use when a planning agent is overplanning, when a single chain-of-thought keeps going wrong, or when a problem has multiple viable approaches that need exploration before committing.

## When to Use
- Setting up a TreeOfThoughtsAgent for a planning or reasoning task
- Replacing a flat planning agent that generates too many steps upfront
- Choosing BFS vs DFS search strategy for a specific problem
- Tuning breadth/beam/depth for performance vs quality tradeoff
- Combining ToT with SelfCheckGPT for verified reasoning
- Debugging a ToT run by reading the thought_tree state

## Quick Integration

```python
from orchestra import TreeOfThoughtsAgent, ToTSearchStrategy

agent = TreeOfThoughtsAgent(
    name="planner",
    model="gpt-4o-mini",
    system_prompt="You are a strategic problem solver.",
    tot_breadth=3,        # thoughts generated per node
    tot_beam=2,           # thoughts kept per BFS level
    tot_max_depth=4,      # max planning depth
    tot_strategy=ToTSearchStrategy.BFS,
)

result = await agent.run(problem_statement, context)
# result.output                         → final answer
# result.state_updates["thought_chain"] → winning path
# result.state_updates["thought_tree"]  → full tree (for debugging)
```

## Strategy Selection

**Use BFS when:**
- Multiple approaches could work (you want to explore them)
- You're not sure which direction is right early on
- Open-ended planning, creative tasks, strategy design

**Use DFS when:**
- Problems have obvious dead-ends (math, puzzles, constraint satisfaction)
- You want to go deep before trying alternatives
- Backtracking is meaningful (e.g. trying one approach fully before another)

## Parameter Tuning

| Problem | breadth | beam | depth | strategy |
|---|---|---|---|---|
| Open planning | 3–5 | 2–3 | 4–6 | BFS |
| Constraint tasks | 3 | 1 | 6–8 | DFS |
| Creative writing | 4–6 | 3 | 3–4 | BFS |
| Code/math | 3 | 2 | 5 | DFS |
| Quick decisions | 2 | 1 | 2–3 | BFS |

**Token cost** ≈ `breadth × beam × depth × 2` LLM calls (generate + evaluate).
Start with breadth=3, beam=2, depth=4 for most tasks.

## Combining with Hallucination Detection

```python
from orchestra import (
    TreeOfThoughtsAgent, ToTSearchStrategy,
    make_selfcheck_node, SelfCheckMethod,
    WorkflowGraph,
)

tot = TreeOfThoughtsAgent(
    name="tot_planner",
    tot_breadth=3, tot_beam=2, tot_max_depth=4,
)
graph = WorkflowGraph()
graph.add_node("plan", tot)
graph.add_node("verify", make_selfcheck_node(method=SelfCheckMethod.NLI))
graph.add_edge("plan", "verify")
# ToT prevents overplanning; SelfCheck verifies the final output
```

## Reading the Thought Tree (observability)

```python
tree = result.state_updates["thought_tree"]
chain = result.state_updates["thought_chain"]

# Chain: list of thoughts on the winning path
for i, thought in enumerate(chain):
    print(f"Step {i}: {thought}")

# Tree: nested dict of all nodes including pruned ones
# {"thought": "...", "value": 0.9, "depth": 1, "children": [...]}
```

## Overplanning Symptoms This Solves
- Agent generates a 10-step plan before taking any action
- Plan step 3 assumes results from step 1 that don't materialise
- Single chain-of-thought agent keeps producing wrong answers
- Planning node wastes tokens on paths that get abandoned
- Executor fails because the plan didn't account for real constraints

## Steps
1. Identify the planning/reasoning task that needs ToT
2. Choose BFS or DFS based on problem type
3. Set breadth/beam/depth (start with 3/2/4)
4. Wire `TreeOfThoughtsAgent` as a node in the graph
5. Pass `state["thought_chain"]` to the executor node downstream
6. Optionally add a `selfcheck` node after for output verification
7. Use `state["thought_tree"]` for debugging pruned paths
