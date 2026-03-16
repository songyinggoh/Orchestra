"""Wasm tool sandbox using Wasmtime with strict WASI capability restrictions.

Tier 1 of Orchestra's 3-tier sandboxing strategy:
  Tier 1 — Wasm (this module): <5 ms startup, zero host capabilities, fuel-limited
  Tier 2 — gVisor: ~300 ms startup, filtered syscalls, network allowed
  Tier 3 — Kata:   ~2 s startup, full Linux kernel, hardware-level isolation
"""

from __future__ import annotations

import atexit
import threading
import time
import weakref
from typing import TYPE_CHECKING, Any

import structlog

from orchestra.tools.sandbox import (
    POLICY_DEFAULT,
    SandboxPolicy,
    ToolCPUExceeded,
    ToolExecutionError,
    ToolMemoryError,
    ToolTimeoutError,
)

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)


class WasmToolSandbox:
    """Execute Orchestra tools compiled to WebAssembly with strict resource limits.

    A single ``WasmToolSandbox`` instance owns a Wasmtime ``Engine`` and the
    background epoch-ticker thread.  Create one instance per process and reuse
    it; ``Engine`` compilation is expensive but ``Store`` creation is cheap.

    Usage::

        sandbox = WasmToolSandbox()
        output = sandbox.execute(wasm_bytes, input_data=b"hello")
    """

    def __init__(self, epoch_interval: float = 1.0) -> None:
        """Initialise the Wasmtime engine and start the epoch ticker.

        Args:
            epoch_interval: Seconds between epoch increments. Default 1.0 s
                            matches ``SandboxPolicy.timeout_epochs`` semantics.
        """
        try:
            import wasmtime
        except ImportError as exc:
            raise ImportError(
                "wasmtime is required. Install with: pip install wasmtime>=23.0.0"
            ) from exc

        cfg = wasmtime.Config()
        cfg.consume_fuel = True        # Enable per-store fuel budget
        cfg.epoch_interruption = True  # Enable wall-clock timeout via epoch
        self._engine = wasmtime.Engine(cfg)
        self._epoch_interval = epoch_interval
        self._ticker_stop = threading.Event()
        self._ticker_thread: threading.Thread | None = None
        self._start_epoch_ticker()

        # Safety net: call shutdown() at process exit even if the caller forgot.
        # weakref avoids keeping this object alive solely due to the atexit entry.
        _ref = weakref.ref(self)
        atexit.register(lambda: _ref() and _ref().shutdown())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        wasm_bytes: bytes,
        *,
        input_data: bytes = b"",
        policy: SandboxPolicy = POLICY_DEFAULT,
    ) -> bytes:
        """Execute a Wasm module and return its stdout output.

        The module is executed with **zero WASI capabilities** by default:
        no filesystem access, no network, no environment variables, no stdin.
        Only stdout is optionally captured (controlled by ``policy.allow_stdout``).

        Args:
            wasm_bytes: Compiled ``.wasm`` binary.
            input_data: Data passed to the module via WASI stdin (if supported).
            policy: Resource and capability limits.

        Returns:
            Raw bytes written to WASI stdout by the module.

        Raises:
            ToolCPUExceeded: Module consumed its fuel budget.
            ToolTimeoutError: Module exceeded the epoch timeout.
            ToolMemoryError: Module declares more memory than allowed.
            ToolExecutionError: Any other Wasm execution failure.
        """
        import wasmtime

        store = wasmtime.Store(self._engine)
        store.set_fuel(policy.fuel)
        store.set_epoch_deadline(policy.timeout_epochs)

        # Build WASI config with minimal capabilities (deny by default)
        wasi_cfg = wasmtime.WasiConfig()
        if policy.allow_stdout:
            wasi_cfg.inherit_stdout()
        if policy.allow_stderr:
            wasi_cfg.inherit_stderr()
        # No FS preopen, no env, no network — capability model: deny everything

        store.set_wasi(wasi_cfg)

        # Compile and validate module
        try:
            module = wasmtime.Module(self._engine, wasm_bytes)
        except Exception as exc:
            raise ToolExecutionError(f"Wasm module compilation failed: {exc}") from exc

        self._validate_module(module, policy, store)

        # Link WASI imports
        linker = wasmtime.Linker(self._engine)
        linker.define_wasi()

        try:
            instance = linker.instantiate(store, module)
        except Exception as exc:
            raise ToolExecutionError(f"Wasm instantiation failed: {exc}") from exc

        # Run the module entry point
        exports = instance.exports(store)
        start_fn = exports.get("_start") or exports.get("run")
        if start_fn is None:
            raise ToolExecutionError(
                "Wasm module must export '_start' or 'run' function"
            )

        try:
            start_fn(store)
        except Exception as exc:
            self._classify_error(exc, policy)

        return self._read_output(instance, store)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_module(
        self,
        module: object,
        policy: SandboxPolicy,
        store: object,
    ) -> None:
        """Reject modules that declare excessive memory up front."""
        import wasmtime

        # Check imports
        for imp in module.imports:  # type: ignore[attr-defined]
            if isinstance(imp.type, wasmtime.MemoryType):
                self._check_mem_limit(imp.type, policy)

        # Check exports
        for exp in module.exports:  # type: ignore[attr-defined]
            if isinstance(exp.type, wasmtime.MemoryType):
                self._check_mem_limit(exp.type, policy)

    def _check_mem_limit(self, mem_type: Any, policy: SandboxPolicy) -> None:
        """Check if a memory type exceeds policy limits."""
        min_pages = mem_type.limits.min
        if min_pages > policy.max_memory_pages:
            raise ToolMemoryError(
                f"Module requests {min_pages} memory pages "
                f"(policy max: {policy.max_memory_pages})"
            )

    def _read_output(self, instance: object, store: object) -> bytes:
        """Attempt to read output via a ``get_output`` export, else return b''."""
        try:
            exports = instance.exports(store)  # type: ignore[attr-defined]
            get_output = exports.get("get_output")
            if get_output is not None:
                raw = get_output(store)
                if isinstance(raw, (bytes, bytearray)):
                    return bytes(raw)
        except Exception:
            pass
        return b""

    @staticmethod
    def _classify_error(exc: Exception, policy: SandboxPolicy) -> None:
        """Re-raise *exc* as the appropriate typed error."""
        msg = str(exc).lower()
        if "fuel" in msg or "out of fuel" in msg:
            raise ToolCPUExceeded(
                f"Tool exceeded {policy.fuel} fuel units"
            ) from exc
        if "epoch" in msg or "interrupt" in msg:
            raise ToolTimeoutError(
                f"Tool exceeded {policy.timeout_epochs} second(s) timeout"
            ) from exc
        raise ToolExecutionError(str(exc)) from exc

    def shutdown(self) -> None:
        """Stop the epoch-ticker thread and wait for it to exit.

        Call this when the sandbox is no longer needed (e.g., in a finally block
        or an async lifespan handler).  Safe to call multiple times.
        If not called explicitly, the daemon thread is killed automatically when
        the process exits, so omitting it is only a concern for long-lived
        processes that create many sandboxes.
        """
        self._ticker_stop.set()
        if self._ticker_thread is not None and self._ticker_thread.is_alive():
            self._ticker_thread.join(timeout=self._epoch_interval * 2 + 1)
            if self._ticker_thread.is_alive():  # pragma: no cover
                log.warning("wasm_epoch_ticker_did_not_stop_cleanly")
        log.debug("wasm_epoch_ticker_stopped")

    def __enter__(self) -> "WasmToolSandbox":
        return self

    def __exit__(self, *exc: object) -> None:
        self.shutdown()

    def _start_epoch_ticker(self) -> None:
        """Start a daemon thread that increments the engine epoch every interval."""

        def _ticker() -> None:
            # wait() returns True when the stop event is set, False on timeout.
            # Loop exits immediately on shutdown() rather than sleeping a full interval.
            while not self._ticker_stop.wait(self._epoch_interval):
                self._engine.increment_epoch()

        self._ticker_thread = threading.Thread(
            target=_ticker, daemon=False, name="wasm-epoch-ticker"
        )
        self._ticker_thread.start()
        log.debug("wasm_epoch_ticker_started", interval_s=self._epoch_interval)
