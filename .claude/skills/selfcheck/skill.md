# SelfCheck Skill

## Description
Integrate SelfCheckGPT hallucination detection into an agent or workflow. Use when adding hallucination checking to an existing agent, wiring a verification step into a graph, or choosing the right SelfCheckGPT method for a use case.

## When to Use
- Adding hallucination detection to a new or existing agent
- Choosing between NLI / BERTScore / N-gram / LLM-as-judge methods
- Wiring a selfcheck node into a WorkflowGraph
- Debugging why an agent is producing inconsistent outputs
- Deciding between `SelfCheckAgent`, `SessionAuditorAgent`, or `make_selfcheck_node`

## Method Selection Guide

| Method | When to use | Tradeoffs |
|---|---|---|
| `SelfCheckMethod.NLI` | Default, no API needed | Loads DeBERTa (~400MB), slow first run |
| `SelfCheckMethod.LLM` | Highest accuracy, have API budget | Extra LLM calls per sentence |
| `SelfCheckMethod.BERTSCORE` | Semantic similarity needed | Needs bert_score package |
| `SelfCheckMethod.NGRAM` | Speed matters, simple outputs | Least accurate |

## Integration Patterns

### Pattern 1: Tool on an existing agent (agent decides when to verify)
```python
from orchestra import selfcheck_tool, SelfCheckMethod

# Add to any existing agent's tools list
agent.tools.append(selfcheck_tool(method=SelfCheckMethod.NLI, num_samples=3))

# Update system prompt to use it
agent.system_prompt += (
    "\nBefore returning any factual answer, call the selfcheck tool to verify "
    "your response is consistent. Revise if hallucination_risk is 'high'."
)
```

### Pattern 2: SelfCheckAgent subclass (always checks, optional retry)
```python
from orchestra import SelfCheckAgent, SelfCheckMethod

agent = SelfCheckAgent(
    name="my_agent",
    model="gpt-4o-mini",
    system_prompt="...",
    selfcheck_method=SelfCheckMethod.NLI,
    selfcheck_samples=3,
    retry_on_high_risk=True,
)
# Access results: result.state_updates["selfcheck"]["hallucination_risk"]
```

### Pattern 3: Graph node (post-process any agent's output)
```python
from orchestra import make_selfcheck_node, SelfCheckMethod, WorkflowGraph

graph = WorkflowGraph()
graph.add_node("agent", my_agent)
graph.add_node("verify", make_selfcheck_node(
    method=SelfCheckMethod.NLI,
    num_samples=3,
    response_key="output",    # reads from state["output"]
    result_key="selfcheck",   # writes to state["selfcheck"]
))
graph.add_edge("agent", "verify")

# Route on risk level
graph.add_conditional_edge(
    "verify",
    lambda s: "done" if s["selfcheck"]["hallucination_risk"] != "high" else "retry",
)
```

### Pattern 4: Standalone session auditor
```python
from orchestra import SessionAuditorAgent

auditor = SessionAuditorAgent(
    selfcheck_method=SelfCheckMethod.NLI,
    selfcheck_samples=3,
)
# Reads state["output"] + state["messages"], writes state["audit"]
```

## Accessing Results
```python
sc = result.state_updates["selfcheck"]
sc["consistency_score"]   # float 0.0–1.0
sc["hallucination_risk"]  # "low" | "medium" | "high"
sc["flagged"]             # list of high-risk sentences
sc["sentence_scores"]     # [{"sentence": ..., "score": ...}, ...]
```

## Cost Estimate
Each `check()` call makes `num_samples` additional LLM calls.
With NLI method: no extra LLM calls (uses local model).
With LLM method: `num_samples × num_sentences` extra LLM calls.

## Steps
1. Identify where in the workflow hallucination risk is highest
2. Choose the integration pattern (tool / subclass / node / auditor)
3. Choose the scoring method based on latency/accuracy tradeoff
4. Set `num_samples` (3 is a good default, 5 for higher confidence)
5. Decide on `retry_on_high_risk` if using SelfCheckAgent
6. Add routing logic downstream of the check if using a graph node
