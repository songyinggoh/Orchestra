# State & Reducers

Every Orchestra workflow operates on a typed state object. State flows through the graph, with each node reading from it and returning updates.

## Defining State

Subclass `WorkflowState` (a Pydantic `BaseModel`) to define your workflow's state:

```python
from orchestra.core.state import WorkflowState

class MyState(WorkflowState):
    topic: str = ""
    output: str = ""
    step_count: int = 0
```

All fields need defaults — state is initialized from your provided `initial_state` dict, with defaults filling in missing fields.

## Reducers

Reducers control how state fields merge when updated — especially important for parallel fan-in where multiple nodes write to the same field.

Annotate fields with reducer functions using `typing.Annotated`:

```python
from typing import Annotated
from orchestra.core.state import WorkflowState, merge_list, merge_dict, sum_numbers

class ResearchState(WorkflowState):
    topic: str = ""                                        # last-write-wins (no reducer)
    findings: Annotated[dict[str, str], merge_dict] = {}   # merge dicts
    messages: Annotated[list[str], merge_list] = []        # append lists
    api_calls: Annotated[int, sum_numbers] = 0             # sum values
```

### Built-in Reducers

| Reducer | Type | Behavior |
|---------|------|----------|
| `merge_list` | `list` | Appends new items to existing list |
| `merge_dict` | `dict` | Shallow-merges new dict into existing |
| `sum_numbers` | `int/float` | Adds new value to existing |
| `last_write_wins` | any | Replaces existing with new (default behavior) |
| `merge_set` | `set` | Union of existing and new sets |
| `concat_str` | `str` | Concatenates strings |
| `keep_first` | any | Keeps the existing value, ignores new |
| `max_value` | `int/float` | Keeps the larger value |
| `min_value` | `int/float` | Keeps the smaller value |

### Custom Reducers

Any callable with signature `(existing, new) -> merged` works as a reducer:

```python
def weighted_average(existing: float, new: float) -> float:
    return existing * 0.7 + new * 0.3

class MyState(WorkflowState):
    score: Annotated[float, weighted_average] = 0.0
```

## How State Updates Work

Node functions return a partial dict of updates. Only returned fields are modified:

```python
async def my_node(state: dict[str, Any]) -> dict[str, Any]:
    # Only updates 'output' and 'messages'; other fields are preserved
    return {
        "output": "processed",
        "messages": ["step completed"],
    }
```

The update process:

1. **Fields with reducers** — `reducer(current_value, new_value)` is called
2. **Fields without reducers** — New value replaces the old (last-write-wins)
3. **Fields not in the update** — Preserved unchanged
4. **Unknown fields** — Raises `StateValidationError`

A new state instance is returned on each update (immutable updates).

## Parallel State Merging

When parallel nodes complete, their updates are merged sequentially using reducers:

```python
# Three parallel nodes return these updates:
update_a = {"findings": {"tech": "..."}, "messages": ["A done"]}
update_b = {"findings": {"market": "..."}, "messages": ["B done"]}
update_c = {"findings": {"legal": "..."}, "messages": ["C done"]}

# With merge_dict on findings and merge_list on messages:
# findings = {"tech": "...", "market": "...", "legal": "..."}
# messages = ["A done", "B done", "C done"]
```

Without reducers on parallel-written fields, last-write-wins applies and you lose data from earlier nodes.

!!! warning
    Always use reducers on fields written by parallel nodes. Without them, only the last node's value survives.

## State Functions

| Function | Description |
|----------|-------------|
| `extract_reducers(state_class)` | Returns `{field_name: reducer_fn}` for all annotated fields |
| `apply_state_update(state, update, reducers)` | Applies a partial update, returns a new state |
| `merge_parallel_updates(state, updates, reducers)` | Merges a list of parallel updates sequentially |
