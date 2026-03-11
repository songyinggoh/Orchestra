"""Sandbox policy definitions for tool execution tiers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SandboxPolicy:
    """Resource and capability limits for Wasm tool execution.

    Attributes:
        fuel: CPU budget in Wasmtime fuel units. Each Wasm instruction consumes
              approximately 1 unit. Default 10M ≈ tens of milliseconds of work.
        timeout_epochs: Wall-clock timeout as epoch count. The epoch ticker
                        increments once per second, so this is approximately
                        seconds. Default 5 s.
        max_memory_pages: Maximum Wasm memory pages (1 page = 64 KiB).
                          Default 256 pages = 16 MiB.
        max_stack_bytes: Maximum Wasm operand stack size in bytes. Default 1 MiB.
        allow_stdout: Whether to capture WASI stdout as tool output.
        allow_stderr: Whether to inherit WASI stderr (debug logging only).
    """

    fuel: int = 10_000_000
    timeout_epochs: int = 5
    max_memory_pages: int = 256
    max_stack_bytes: int = 1_048_576  # 1 MiB
    allow_stdout: bool = True
    allow_stderr: bool = False


# Preset policies for common use cases

#: Tight limits for fast, purely computational tools (parsers, formatters).
POLICY_STRICT = SandboxPolicy(
    fuel=1_000_000,
    timeout_epochs=2,
    max_memory_pages=64,   # 4 MiB
)

#: Default limits for general-purpose tools.
POLICY_DEFAULT = SandboxPolicy()

#: Relaxed limits for heavier tools (e.g. code analysis, data processing).
POLICY_RELAXED = SandboxPolicy(
    fuel=50_000_000,
    timeout_epochs=30,
    max_memory_pages=1024,  # 64 MiB
    allow_stderr=True,
)


class ToolCPUExceeded(RuntimeError):
    """Wasm tool exceeded its fuel (CPU) budget."""


class ToolTimeoutError(RuntimeError):
    """Wasm tool exceeded its wall-clock timeout."""


class ToolMemoryError(RuntimeError):
    """Wasm module declares more memory than the policy allows."""


class ToolExecutionError(RuntimeError):
    """Generic Wasm tool execution failure."""
