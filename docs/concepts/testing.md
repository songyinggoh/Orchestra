# Testing

Orchestra includes `ScriptedLLM`, a deterministic mock that implements the `LLMProvider` protocol. It returns pre-defined responses in order, enabling fast and reproducible tests without API calls.

## Basic Usage

```python
from orchestra.testing import ScriptedLLM

llm = ScriptedLLM([
    "First response from the LLM.",
    "Second response from the LLM.",
])

response = await llm.complete(messages)  # Returns "First response from the LLM."
response = await llm.complete(messages)  # Returns "Second response from the LLM."
```

Strings are automatically wrapped in `LLMResponse` objects.

## Testing Agent Workflows

Use `ScriptedLLM` as the provider when running workflows:

```python
import pytest
from orchestra import WorkflowGraph, BaseAgent, run
from orchestra.testing import ScriptedLLM

@pytest.mark.asyncio
async def test_research_pipeline():
    llm = ScriptedLLM([
        "Key facts about quantum computing: superposition, entanglement.",
        "Quantum computing harnesses quantum mechanics for computation.",
    ])

    researcher = BaseAgent(name="researcher", system_prompt="Research the topic.")
    writer = BaseAgent(name="writer", system_prompt="Write a summary.")

    graph = WorkflowGraph().then(researcher).then(writer)
    result = await run(graph, input="quantum computing", provider=llm)

    assert "quantum" in result.output.lower()
    llm.assert_all_consumed()
```

## Assertion Helpers

### `assert_all_consumed()`

Verifies that all scripted responses were used. Catches cases where the workflow exited earlier than expected:

```python
llm = ScriptedLLM(["response 1", "response 2", "response 3"])
# ... run workflow that only uses 2 responses ...
llm.assert_all_consumed()  # Raises AssertionError: "1 unconsumed response(s)"
```

### `assert_prompt_received(call_index, pattern)`

Verifies that a specific LLM call received messages matching a regex pattern:

```python
llm = ScriptedLLM(["response"])
# ... run workflow ...
llm.assert_prompt_received(0, r"research.*quantum")  # Check first call
```

Arguments:

- `call_index` — Zero-based index of the LLM call to check
- `pattern` — Regex pattern to search for in the concatenated message content

## Inspecting Call History

Access the call log for detailed assertions:

```python
llm = ScriptedLLM(["response"])
# ... run workflow ...

print(llm.call_count)   # Number of calls made
print(llm.call_log)     # List of {messages, model, tools, temperature}
print(llm.call_log[0]["messages"])  # Messages sent in the first call
```

## Tool Call Responses

Script LLM responses that include tool calls using `LLMResponse` directly:

```python
from orchestra.core.types import LLMResponse, ToolCall

llm = ScriptedLLM([
    LLMResponse(
        content="",
        tool_calls=[
            ToolCall(name="web_search", arguments={"query": "AI trends"})
        ],
        finish_reason="tool_calls",
    ),
    "Based on the search results, here is the summary.",
])
```

## Resetting

Reuse a `ScriptedLLM` across tests by calling `reset()`:

```python
llm = ScriptedLLM(["response 1", "response 2"])
# ... first test ...
llm.reset()  # Resets index and call log
# ... second test uses same responses ...
```

## Testing Function-Node Workflows

Workflows built entirely from function nodes (no LLM calls) don't need `ScriptedLLM` at all:

```python
@pytest.mark.asyncio
async def test_data_pipeline():
    graph = WorkflowGraph(state_schema=MyState).then(step_a).then(step_b)
    compiled = graph.compile()
    result = await compiled.run({"input": "test data"})
    assert result["output"] == "expected result"
```

This is the pattern used for testing the example workflows in `tests/integration/test_examples.py`.
