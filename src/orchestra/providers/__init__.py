"""Orchestra LLM providers."""

from orchestra.providers.callable import CallableProvider
from orchestra.providers.http import HttpProvider

__all__ = ["CallableProvider", "HttpProvider", "auto_provider"]


def auto_provider() -> object:
    """Return a ready-to-use provider, auto-detecting available backends.

    If you already use a cloud agentic provider (Claude Code, Gemini CLI,
    or OpenAI Codex CLI), Orchestra works out of the box — no API keys,
    no env vars, no separate billing.

    Detection order:
        1. ORCHESTRA_BASE_URL / ORCHESTRA_API_KEY  → HttpProvider  (custom endpoint)
        2. ``claude`` CLI on PATH                   → ClaudeCodeProvider  (uses subscription)
        3. ``gemini`` CLI on PATH                   → GeminiCliProvider  (uses subscription)
        4. ``codex`` CLI on PATH                    → CodexCliProvider  (uses subscription)
        5. ANTHROPIC_API_KEY                        → AnthropicProvider  (API key)
        6. OPENAI_API_KEY                           → HttpProvider  (API key)
        7. GOOGLE_API_KEY                           → GoogleProvider  (API key)
        8. Ollama at localhost:11434                 → OllamaProvider  (local)

    Raises:
        RuntimeError: if no backend is detected.
    """
    import os

    # 1. Explicit custom endpoint takes priority.
    if os.environ.get("ORCHESTRA_BASE_URL") or os.environ.get("ORCHESTRA_API_KEY"):
        return HttpProvider()

    # 2-4. CLI-based providers — use your existing subscription, no API key.
    from orchestra.providers.claude_code import ClaudeCodeProvider

    if ClaudeCodeProvider.is_available():
        return ClaudeCodeProvider()

    from orchestra.providers.gemini_cli import GeminiCliProvider

    if GeminiCliProvider.is_available():
        return GeminiCliProvider()

    from orchestra.providers.codex_cli import CodexCliProvider

    if CodexCliProvider.is_available():
        return CodexCliProvider()

    # 5-7. API-key providers — for direct API access.
    if os.environ.get("ANTHROPIC_API_KEY"):
        from orchestra.providers.anthropic import AnthropicProvider

        return AnthropicProvider()

    if os.environ.get("OPENAI_API_KEY"):
        return HttpProvider()

    if os.environ.get("GOOGLE_API_KEY"):
        from orchestra.providers.google import GoogleProvider

        return GoogleProvider()

    # 8. Ollama — check synchronously via a quick socket probe.
    import socket

    try:
        s = socket.create_connection(("localhost", 11434), timeout=1.0)
        s.close()
        from orchestra.providers.ollama import OllamaProvider

        return OllamaProvider()
    except OSError:
        pass

    raise RuntimeError(
        "No LLM backend detected.\n"
        "\n"
        "Already using a cloud agentic provider? Orchestra works automatically:\n"
        "  - Claude Code → install the claude CLI\n"
        "  - Gemini CLI  → install the gemini CLI\n"
        "  - Codex CLI   → install the codex CLI\n"
        "\n"
        "Local (free):\n"
        "  - Ollama → ollama serve && ollama pull llama3.1\n"
        "\n"
        "Direct API access:\n"
        "  - export ANTHROPIC_API_KEY=sk-ant-...\n"
        "  - export OPENAI_API_KEY=sk-...\n"
        "  - export GOOGLE_API_KEY=AIza...\n"
        "  - export ORCHESTRA_BASE_URL=<url> ORCHESTRA_API_KEY=<key>"
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
    if name == "ClaudeCodeProvider":
        from orchestra.providers.claude_code import ClaudeCodeProvider

        return ClaudeCodeProvider
    if name == "GeminiCliProvider":
        from orchestra.providers.gemini_cli import GeminiCliProvider

        return GeminiCliProvider
    if name == "CodexCliProvider":
        from orchestra.providers.codex_cli import CodexCliProvider

        return CodexCliProvider
    raise AttributeError(f"module 'orchestra.providers' has no attribute {name!r}")
