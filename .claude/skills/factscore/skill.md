# FActScore Skill

## Description
Integrate FActScore factual precision evaluation into an agent or workflow. Use when verifying factual claims in long-form text against a knowledge source, especially biographical or entity-centric content.

## When to Use
- Verifying factual precision in biographies, entity descriptions, historical text
- Comparing SelfCheckGPT vs FActScore for a use case
- Setting up a custom knowledge source (company docs, internal wiki)
- Wiring FActScore as a graph node with conditional routing
- Deciding between `FactScorerAgent` and `make_factscore_node`

## SelfCheckGPT vs FActScore — Decision Guide

| Criteria | Use SelfCheckGPT | Use FActScore |
|---|---|---|
| External knowledge available? | No | Yes |
| Content type | Any LLM output | Factual / biographical |
| Granularity needed | Sentence | Atomic fact |
| Speed | Faster | Slower (retrieval) |
| API dependency | Optional (NLI method) | OpenAI required |
| Setup complexity | Low | Medium (download data) |

**Rule of thumb**: Use FActScore when you have a knowledge source and need atomic-level precision. Use SelfCheckGPT when you need a quick, zero-resource check.

## Setup
```bash
pip install factscore
python -m spacy download en_core_web_sm
# Download Wikipedia knowledge source (~10GB):
python -m factscore.download_data --llama_7B_HF_path "llama-7B"
```

## Integration Patterns

### Pattern 1: Tool on an existing agent
```python
from orchestra import factscore_tool

agent.tools.append(factscore_tool(
    openai_key="sk-...",
    knowledge_source="enwiki-20230401",
))
# Agent calls: factscore(topic="Marie Curie", response="...")
```

### Pattern 2: FactScorerAgent subclass
```python
from orchestra import FactScorerAgent

agent = FactScorerAgent(
    name="biographer",
    model="gpt-4o-mini",
    system_prompt="Write accurate biographies.",
    openai_key="sk-...",
    knowledge_source="enwiki-20230401",
    topic_state_key="topic",   # reads entity from state["topic"]
)
# state_updates["factscore"] contains result after every run()
```

### Pattern 3: Graph node with conditional routing
```python
from orchestra import make_factscore_node, WorkflowGraph

graph = WorkflowGraph()
graph.add_node("writer", writer_agent)
graph.add_node("factscore", make_factscore_node(
    openai_key="sk-...",
    knowledge_source="enwiki-20230401",
    response_key="output",    # reads from state["output"]
    topic_key="topic",        # reads entity from state["topic"]
    result_key="factscore",   # writes to state["factscore"]
))
graph.add_conditional_edge(
    "factscore",
    lambda s: "done" if s["factscore"]["hallucination_risk"] == "low" else "revise",
)
```

### Pattern 4: Custom knowledge source
```python
from orchestra import FactScoreChecker

checker = FactScoreChecker(openai_key="sk-...")
checker.register_knowledge_source(
    name="company_wiki",
    data_path="data/wiki.jsonl",   # {"title": "...", "text": "..."}
    db_path="data/wiki.db",
)
result = await checker.check(
    topic="Product X",
    response=generated_text,
    knowledge_source="company_wiki",
)
```

### Batch checking (more efficient):
```python
results = await checker.check_batch(
    topics=["Einstein", "Curie", "Turing"],
    responses=[text1, text2, text3],
)
```

## Accessing Results
```python
fs = result.state_updates["factscore"]
fs["factscore"]            # float 0.0–1.0
fs["init_score"]           # score without length penalty
fs["hallucination_risk"]   # "low" | "medium" | "high"
fs["num_facts"]            # avg atomic facts per response
fs["respond_ratio"]        # fraction that didn't abstain
```

## Cost Estimate
~$0.01 per 100 sentences using retrieval+ChatGPT pipeline.
Set `gamma=0` to disable length penalty (faster, less penalisation of long responses).

## Steps
1. Confirm FActScore is installed and data is downloaded
2. Identify the topic (named entity) for each response
3. Choose integration pattern (tool / subclass / node)
4. Set `topic_state_key` so the agent can find the entity name
5. Optionally register a custom knowledge source
6. Add conditional routing downstream based on `hallucination_risk`
