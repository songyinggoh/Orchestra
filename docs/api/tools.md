# Tools API Reference

Tools are functions that agents can call during their reasoning loop. The `@tool` decorator auto-generates JSON Schema from Python type hints.

## @tool Decorator

::: orchestra.tools.base.tool
    options:
      show_source: false
      heading_level: 3

### Usage

```python
from orchestra import tool

# Simple form
@tool
async def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for information."""
    return f"Results for: {query}"

# With custom name
@tool(name="search", description="Search the internet")
async def web_search(query: str) -> str:
    return f"Results for: {query}"
```

The decorator generates a JSON Schema from the function signature:

```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string"},
    "max_results": {"type": "integer"}
  },
  "required": ["query"]
}
```

Parameters with defaults are optional in the schema. The `self` and `context` parameters are excluded.

---

## ToolWrapper

::: orchestra.tools.base.ToolWrapper
    options:
      show_source: false
      heading_level: 3
      members:
        - name
        - description
        - parameters_schema
        - execute

---

## ToolRegistry

::: orchestra.tools.registry.ToolRegistry
    options:
      show_source: false
      heading_level: 3
      members:
        - register
        - get
        - has
        - list_tools
        - get_schemas
        - unregister
        - clear

### Usage

```python
from orchestra.tools.registry import ToolRegistry

registry = ToolRegistry()
registry.register(web_search)
registry.register(calculator)

schemas = registry.get_schemas()  # JSON schemas for all registered tools
tool = registry.get("web_search")  # Get a specific tool
```

---

## Tool Protocol

Any object implementing the `Tool` protocol can be used as a tool:

```python
from orchestra.core.protocols import Tool

class MyTool:
    @property
    def name(self) -> str: return "my_tool"

    @property
    def description(self) -> str: return "Does something"

    @property
    def parameters_schema(self) -> dict: return {"type": "object", "properties": {}}

    async def execute(self, arguments: dict, *, context=None) -> ToolResult:
        return ToolResult(tool_call_id="", name="my_tool", content="result")
```

## Supported Type Mappings

| Python Type | JSON Schema Type |
|-------------|-----------------|
| `str` | `string` |
| `int` | `integer` |
| `float` | `number` |
| `bool` | `boolean` |
| `list` | `array` |
| `list[str]` | `array` with `items: {type: string}` |
| `dict` | `object` |
