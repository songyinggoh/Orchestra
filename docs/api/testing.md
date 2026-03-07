# Testing API Reference

## ScriptedLLM

::: orchestra.testing.scripted.ScriptedLLM
    options:
      show_source: false
      heading_level: 3
      members:
        - complete
        - stream
        - count_tokens
        - get_model_cost
        - call_count
        - call_log
        - reset
        - assert_all_consumed
        - assert_prompt_received

### Constructor

```python
ScriptedLLM(responses: list[LLMResponse | str])
```

- **responses** — List of responses to return in order. Strings are auto-wrapped in `LLMResponse(content=string)`.

### Usage

```python
from orchestra.testing import ScriptedLLM
from orchestra.core.types import LLMResponse, ToolCall

# Simple string responses
llm = ScriptedLLM(["First response", "Second response"])

# Mixed string and LLMResponse objects
llm = ScriptedLLM([
    "Simple text response",
    LLMResponse(
        content="",
        tool_calls=[ToolCall(name="search", arguments={"q": "test"})],
        finish_reason="tool_calls",
    ),
    "Final response after tool call",
])
```

---

## ScriptExhaustedError

::: orchestra.testing.scripted.ScriptExhaustedError
    options:
      show_source: false
      heading_level: 3

Raised when `complete()` is called but all scripted responses have been consumed. This typically indicates the workflow made more LLM calls than expected.
