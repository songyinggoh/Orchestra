# Providers API Reference

Orchestra includes eleven built-in LLM providers (HttpProvider, AnthropicProvider, ClaudeCodeProvider, GeminiCliProvider, CodexCliProvider, GoogleProvider, OllamaProvider, CallableProvider, CachedProvider, ReplayProvider, and StrategySwitchingProvider) and a protocol for implementing custom ones.

## LLMProvider Protocol

All providers implement the `LLMProvider` protocol defined in `orchestra.core.protocols`:

```python
class LLMProvider(Protocol):
    async def complete(self, messages, *, model, tools, temperature, max_tokens, output_type) -> LLMResponse: ...
    async def stream(self, messages, *, model, tools, temperature, max_tokens) -> AsyncIterator[StreamChunk]: ...
    def count_tokens(self, messages, model) -> int: ...
    def get_model_cost(self, model) -> ModelCost: ...
```

---

## HttpProvider

OpenAI-compatible HTTP provider. Works with OpenAI, Ollama, and any OpenAI-compatible endpoint.

::: orchestra.providers.http.HttpProvider
    options:
      show_source: false
      heading_level: 3
      members:
        - complete
        - stream
        - count_tokens
        - get_model_cost
        - aclose

### Usage

```python
from orchestra.providers import HttpProvider

# OpenAI
provider = HttpProvider(
    api_key="sk-...",
    default_model="gpt-4o-mini",
)

# Ollama (local)
provider = HttpProvider(
    base_url="http://localhost:11434/v1",
    default_model="llama3",
)

# Custom endpoint
provider = HttpProvider(
    base_url="https://my-api.example.com/v1",
    api_key="my-key",
    default_model="my-model",
)
```

---

## AnthropicProvider

Dedicated provider for Anthropic's Messages API with proper format handling.

::: orchestra.providers.anthropic.AnthropicProvider
    options:
      show_source: false
      heading_level: 3
      members:
        - complete
        - stream
        - count_tokens
        - get_model_cost
        - aclose

### Usage

```python
from orchestra.providers import AnthropicProvider

provider = AnthropicProvider(
    api_key="sk-ant-...",
    default_model="claude-sonnet-4-20250514",
)

result = await run(graph, input="Hello", provider=provider)
```

### API Differences from OpenAI

The `AnthropicProvider` handles several Anthropic-specific formats automatically:

- **System prompts** are extracted from the messages array and sent as a separate `system` parameter
- **Tool calls** use Anthropic's `tool_use` / `tool_result` content block format
- **Stop reasons** are mapped from Anthropic's `stop_reason` to Orchestra's `finish_reason`
- **Token usage** is parsed from Anthropic's `usage` response field
