"""Helper functions for OpenTelemetry span attribute mapping.

Maps Orchestra event fields to gen_ai.* semantic conventions.
All functions are pure helpers with no OTel SDK dependency.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from orchestra.storage.events import LLMCalled

# Provider inference from model name prefixes
_MODEL_PROVIDER_MAP: dict[str, str] = {
    "gpt": "openai",
    "o1": "openai",
    "o3": "openai",
    "o4": "openai",
    "chatgpt": "openai",
    "claude": "anthropic",
    "gemini": "google",
    "palm": "google",
    "command": "cohere",
    "llama": "meta",
    "mistral": "mistralai",
    "mixtral": "mistralai",
    "deepseek": "deepseek",
    "qwen": "alibaba",
}


def extract_provider(model: str) -> str:
    """Infer provider name from a model string.

    Examples:
        >>> extract_provider("gpt-4o-mini")
        'openai'
        >>> extract_provider("claude-3-opus")
        'anthropic'
        >>> extract_provider("unknown-model")
        'unknown'
    """
    if not model:
        return "unknown"
    model_lower = model.lower()
    for prefix, provider in _MODEL_PROVIDER_MAP.items():
        if model_lower.startswith(prefix):
            return provider
    return "unknown"


def llm_event_to_attributes(event: "LLMCalled") -> dict[str, Any]:
    """Map LLMCalled event fields to gen_ai.* semantic convention attributes.

    Returns a dict of span attributes following the OpenTelemetry
    gen_ai semantic conventions.
    """
    model = getattr(event, "model", "") or ""
    provider = extract_provider(model)

    attrs: dict[str, Any] = {
        "gen_ai.system": provider,
        "gen_ai.request.model": model,
        "gen_ai.usage.input_tokens": getattr(event, "input_tokens", 0) or 0,
        "gen_ai.usage.output_tokens": getattr(event, "output_tokens", 0) or 0,
    }

    finish_reason = getattr(event, "finish_reason", "") or ""
    if finish_reason:
        attrs["gen_ai.response.finish_reasons"] = [finish_reason]

    # PII-sensitive content: only include when explicitly opted in
    if should_capture_content():
        content = getattr(event, "content", None)
        if content is not None:
            attrs["gen_ai.completion"] = content

    return attrs


def should_capture_content() -> bool:
    """Check whether content capture is enabled via environment variable.

    Returns True only if ORCHESTRA_OTEL_CAPTURE_CONTENT is explicitly
    set to a truthy value (true, 1, yes).
    """
    val = os.environ.get("ORCHESTRA_OTEL_CAPTURE_CONTENT", "").lower()
    return val in ("true", "1", "yes")
