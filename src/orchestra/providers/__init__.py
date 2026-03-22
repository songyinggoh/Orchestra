"""Orchestra LLM providers."""

from orchestra.providers.callable import CallableProvider
from orchestra.providers.http import HttpProvider

__all__ = ["CallableProvider", "HttpProvider", "auto_provider"]


def auto_provider() -> object:
    """Return a ready-to-use provider based on available env vars.

    Checks in priority order:
        1. ORCHESTRA_BASE_URL + ORCHESTRA_API_KEY  → HttpProvider (any OpenAI-compat backend)
        2. ANTHROPIC_API_KEY                        → AnthropicProvider
        3. OPENAI_API_KEY                           → HttpProvider (OpenAI)
        4. GOOGLE_API_KEY                           → GoogleProvider
        5. Ollama running at localhost:11434         → OllamaProvider (no key needed)

    Usage:
        import asyncio
        from orchestra.providers import auto_provider

        provider = asyncio.run(auto_provider())  # async-aware helper below preferred
        # or inside async code:
        provider = await auto_provider_async()

    Raises:
        RuntimeError: if no backend is configured.

    For Groq, Together, Mistral, vLLM, LiteLLM, Azure, or any OpenAI-compatible API:
        export ORCHESTRA_BASE_URL=https://api.groq.com/openai/v1
        export ORCHESTRA_API_KEY=gsk_...
        export ORCHESTRA_MODEL=llama-3.3-70b-versatile
    """
    import os

    # Any custom OpenAI-compatible endpoint takes highest priority
    if os.environ.get("ORCHESTRA_BASE_URL") or os.environ.get("ORCHESTRA_API_KEY"):
        return HttpProvider()

    # Named provider keys
    if os.environ.get("ANTHROPIC_API_KEY"):
        from orchestra.providers.anthropic import AnthropicProvider

        return AnthropicProvider()

    if os.environ.get("OPENAI_API_KEY"):
        return HttpProvider()

    if os.environ.get("GOOGLE_API_KEY"):
        from orchestra.providers.google import GoogleProvider

        return GoogleProvider()

    # Ollama — check synchronously via a quick socket probe
    import socket

    try:
        s = socket.create_connection(("localhost", 11434), timeout=1.0)
        s.close()
        from orchestra.providers.ollama import OllamaProvider

        return OllamaProvider()
    except OSError:
        pass

    raise RuntimeError(
        "No LLM backend found. Configure one of:\n"
        "  Any OpenAI-compatible API:  export ORCHESTRA_BASE_URL=<url> ORCHESTRA_API_KEY=<key>\n"
        "  Anthropic:                  export ANTHROPIC_API_KEY=sk-ant-...\n"
        "  OpenAI:                     export OPENAI_API_KEY=sk-...\n"
        "  Google:                     export GOOGLE_API_KEY=AIza...\n"
        "  Local (free):               ollama serve && ollama pull llama3.1\n"
    )


# Lazy imports for optional providers
def __getattr__(name: str) -> object:
    if name == "AnthropicProvider":
        from orchestra.providers.anthropic import AnthropicProvider

        return AnthropicProvider
    if name == "GoogleProvider":
        from orchestra.providers.google import GoogleProvider

        return GoogleProvider
    if name == "OllamaProvider":
        from orchestra.providers.ollama import OllamaProvider

        return OllamaProvider
    raise AttributeError(f"module 'orchestra.providers' has no attribute {name!r}")
