---
phase: "02-differentiation"
plan: "03"
subsystem: "providers"
tags: ["llm-provider", "google", "gemini", "ollama", "local-llm", "httpx", "streaming"]
dependency_graph:
  requires: ["orchestra.core.protocols.LLMProvider", "orchestra.core.types", "orchestra.core.errors"]
  provides: ["orchestra.providers.google.GoogleProvider", "orchestra.providers.ollama.OllamaProvider"]
  affects: ["orchestra.providers.__init__"]
tech_stack:
  added: []
  patterns: ["httpx.MockTransport for provider testing", "Gemini contents/parts message format", "Ollama OpenAI-compatible API"]
key_files:
  created:
    - src/orchestra/providers/google.py
    - src/orchestra/providers/ollama.py
    - tests/unit/test_providers.py
  modified:
    - src/orchestra/providers/__init__.py
    - pyproject.toml
decisions:
  - "Used x-goog-api-key header AND ?key= query param for Gemini auth (belt-and-suspenders)"
  - "OllamaProvider wraps ConnectError with actionable 'ollama serve' message"
  - "__init__.py uses __getattr__ lazy imports so google/ollama SDKs are not hard deps"
metrics:
  duration: "5 minutes"
  completed: "2026-03-09"
  tasks_completed: 4
  files_created: 3
  files_modified: 2
---

# Phase 02 Plan 03: LLM Provider Adapters Summary

**One-liner:** Gemini (httpx, SSE streaming, functionDeclarations) and Ollama (OpenAI-compat, ConnectError wrapping) providers conforming to LLMProvider protocol with 19 unit tests.

## What Was Built

### Task 3.1: GoogleProvider (`src/orchestra/providers/google.py`)

Implements `LLMProvider` protocol for Google's Gemini API using `httpx` directly (no `google-generativeai` SDK required at runtime):

- `complete()` — POSTs to `/v1beta/models/{model}:generateContent?key={api_key}`, converts Orchestra `Message` list to Gemini `contents[].parts[]` format, maps `functionCall` parts to `ToolCall`, supports JSON mode via `responseMimeType`/`responseSchema`
- `stream()` — POSTs to `streamGenerateContent?alt=sse`, parses SSE lines, yields `StreamChunk`
- `count_tokens()` — 4-chars-per-token heuristic (synchronous, no extra API call)
- `get_model_cost()` — cost table for gemini-2.0-flash, gemini-2.0-flash-lite, gemini-2.5-pro/flash previews

Error mapping: 400-context -> `ContextWindowError`, 403 -> `AuthenticationError`, 429 -> `RateLimitError`, 500+ -> `ProviderUnavailableError`.

Message converter `_messages_to_gemini_format()` extracts system messages into `systemInstruction`, converts tool results to `functionResponse` parts, maps ASSISTANT role to Gemini "model" role.

### Task 3.2: OllamaProvider (`src/orchestra/providers/ollama.py`)

Implements `LLMProvider` protocol for local Ollama inference using the OpenAI-compatible `/v1/chat/completions` endpoint:

- `complete()` / `stream()` — identical to `HttpProvider` request shape but targeted at `localhost:11434`
- `get_model_cost()` — always returns `ModelCost(0.0, 0.0)` (local = free)
- `health_check()` — GETs `/` via native client, checks for "ollama" in response
- `list_models()` — GETs `/api/tags` (Ollama-native endpoint)
- Graceful degradation: models without tool support receive `tools` param; Ollama silently ignores it

Error handling: `httpx.ConnectError` -> `ProviderUnavailableError` with "`ollama serve`" in message; 404 model not found -> `ProviderError` with "`ollama pull <model>`" suggestion.

### Task 3.3: Provider Tests (`tests/unit/test_providers.py`)

19 tests using `httpx.MockTransport` — zero real API calls:

**GoogleProvider (8):** complete no-tools, complete with functionCall, stream SSE, 403 AuthError, 429 RateLimitError, 400 ContextWindowError, count_tokens, get_model_cost
**OllamaProvider (9):** complete no-tools, complete with tool_calls, stream SSE, ConnectError->Unavailable, 404 model not found, count_tokens, get_model_cost zero, health_check running, health_check not running
**Shared (2):** Gemini message format conversion edge cases

All 19 pass.

### `__init__.py` update

Switched from hard imports to `__getattr__`-based lazy imports so `GoogleProvider` and `OllamaProvider` are accessible via `orchestra.providers.GoogleProvider` without requiring their optional SDKs to be installed. `HttpProvider` remains a direct import (zero extra deps).

## Decisions Made

1. **Gemini auth via header + query param:** `x-goog-api-key` header is set on the `AsyncClient` for all requests, and `?key=` query param is appended to each endpoint URL. The streaming endpoint requires the query param approach so both are included.

2. **No `google-generativeai` SDK dependency:** The plan specified httpx-direct, same as `AnthropicProvider`. The `google` optional group in `pyproject.toml` still lists the SDK for projects that want it, but `GoogleProvider` itself does not import it.

3. **Lazy `__getattr__` in `__init__.py`:** Prevents `ImportError` at module-import time if `anthropic` SDK is absent. `HttpProvider` stays a direct import as it has no optional deps.

4. **OllamaProvider dual clients:** Separate `_client` (pointed at `/v1` for OpenAI-compat) and `_native_client` (pointed at root for `/api/tags`, health check). This avoids path-prefix conflicts.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `stream()` is an AsyncGenerator, not a coroutine**

- **Found during:** Task 3.3 (test run)
- **Issue:** Test code used `async for chunk in await provider.stream(...)` — but `stream()` is an `async def` that `yield`s, making it an AsyncGenerator. Awaiting it raised `TypeError: object async_generator can't be used in 'await' expression`.
- **Fix:** Removed `await` from the two streaming test cases (`async for chunk in provider.stream(...)`).
- **Files modified:** `tests/unit/test_providers.py`
- **Commit:** a094d7f (included in same test commit)

### Additional Items

- Added 1 extra health check test (`test_health_check_when_not_running`) beyond the plan's 8 Ollama tests, for a total of 19 tests (plan specified 16 minimum). The extra test is directionally useful and costs nothing.

## Self-Check

Files exist:
- `src/orchestra/providers/google.py` — created
- `src/orchestra/providers/ollama.py` — created
- `tests/unit/test_providers.py` — created

Protocol conformance verified:
- `isinstance(GoogleProvider(api_key='test'), LLMProvider)` -> True
- `isinstance(OllamaProvider(), LLMProvider)` -> True

All 19 tests pass: `pytest tests/unit/test_providers.py` -> 19 passed

## Self-Check: PASSED
