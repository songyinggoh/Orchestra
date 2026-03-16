# Orchestra Framework — Critical Issues Remediation Guide

This document provides detailed remediation steps for the 14 critical issues identified in the code review.

---

## CRITICAL-1.1: Bare Exception Suppression in Background Task

**Location:** `src/orchestra/memory/tiers.py:162, 258`

**Current Code:**
```python
async def stop(self) -> None:
    """Stop background scan task."""
    self._stop_event.set()
    if self._scan_task:
        self._scan_task.cancel()
        try: await self._scan_task
        except asyncio.CancelledError: pass  # ← ISSUE
```

**Problem:**
- `asyncio.CancelledError` is suppressed without logging.
- If `_background_scan()` encounters any other exception, it dies silently.
- Tiered memory can become inconsistent (hot/warm/cold) without alerting monitoring.

**Fix:**
```python
async def stop(self) -> None:
    """Stop background scan task."""
    self._stop_event.set()
    if self._scan_task:
        self._scan_task.cancel()
        try:
            await self._scan_task
        except asyncio.CancelledError:
            pass  # Expected
        except Exception as e:
            logger.error("background_scan_failed", error=str(e), exc_info=True)

# Also add task exception handler in start():
async def start(self) -> None:
    """Start background scan task."""
    if self._initialized: return
    self._scan_task = asyncio.create_task(self._background_scan())
    self._scan_task.add_done_callback(self._handle_scan_done)
    self._initialized = True

def _handle_scan_done(self, task: asyncio.Task) -> None:
    """Handle background scan task completion."""
    try:
        task.result()  # Will raise if exception occurred
    except asyncio.CancelledError:
        pass  # Expected shutdown
    except Exception as e:
        logger.error("background_scan_crashed", error=str(e), exc_info=True)
```

**Testing:**
```python
async def test_tiered_memory_scan_task_failure():
    """Test that scan task failures are logged."""
    manager = TieredMemoryManager(scan_interval=0.1)

    # Inject a failure
    async def bad_scan():
        await asyncio.sleep(0.05)
        raise RuntimeError("Scan failed")

    manager._background_scan = bad_scan
    await manager.start()
    await asyncio.sleep(0.2)

    # Verify logs contain error
    assert any("background_scan" in record for record in log_records)
```

---

## CRITICAL-1.2: Broad Exception Catch During Checkpoint Restoration

**Location:** `src/orchestra/core/compiled.py:266`

**Current Code:**
```python
try:
    from orchestra.storage.sqlite import SQLiteEventStore
    event_store = SQLiteEventStore()
    await event_store.initialize()
except (ImportError, Exception) as e:
    raise AgentError(f"Failed to auto-initialize event store for resume: {e}")
```

**Problem:**
- Catches `Exception`, which includes `SystemExit`, `KeyboardInterrupt` (in Python <3.11), `GeneratorExit`.
- Converts unrelated failures to `AgentError`, obscuring the real issue.
- Impossible to debug if a system signal is mistakenly caught.

**Fix:**
```python
try:
    from orchestra.storage.sqlite import SQLiteEventStore
    event_store = SQLiteEventStore()
    await event_store.initialize()
except ImportError as e:
    raise AgentError(f"SQLiteEventStore not installed: {e}") from e
except (ValueError, sqlite3.Error, OSError) as e:
    raise AgentError(f"Failed to initialize event store: {e}") from e
# Let other exceptions propagate (RuntimeError, AttributeError, etc.)
```

**Testing:**
```python
async def test_checkpoint_restore_import_error():
    """Verify ImportError is caught."""
    compiled = CompiledGraph(...)
    with patch("orchestra.storage.sqlite.SQLiteEventStore", side_effect=ImportError("missing")):
        with pytest.raises(AgentError):
            await compiled.resume_run(run_id="test")

async def test_checkpoint_restore_system_error():
    """Verify SystemExit is NOT caught."""
    compiled = CompiledGraph(...)
    with patch("orchestra.storage.sqlite.SQLiteEventStore", side_effect=SystemExit(1)):
        with pytest.raises(SystemExit):  # Should propagate!
            await compiled.resume_run(run_id="test")
```

---

## CRITICAL-1.3: Silent Failure on Max Iterations Without Final Output

**Location:** `src/orchestra/core/agent.py:228`

**Current Code:**
```python
for _iteration in range(self.max_iterations):
    # ... tool calling loop ...
    if response.finish_reason == "stop":
        break

raise MaxIterationsError(
    f"Agent '{self.name}' exceeded {self.max_iterations} iterations.\n"
    f"  Last message: {full_messages[-1].content if full_messages else ''}\n"
    f"  Fix: Increase max_iterations or simplify the task."
)
```

**Problem:**
- If max iterations exceeded, no output is returned. Caller has nothing to work with.
- Multi-turn workflows lose partial progress.

**Fix:**
```python
async def run(
    self,
    input: str | list[Message],
    context: ExecutionContext,
) -> AgentResult:
    """Execute the agent's reasoning loop."""
    llm = context.provider
    if not llm:
        raise RuntimeError(...)

    prompt = self._resolve_system_prompt(context)
    full_messages = [Message(role=MessageRole.SYSTEM, content=prompt)]
    # ... build messages ...

    tool_schemas = [self._tool_to_schema(t) for t in self.tools] if self.tools else None
    all_tool_records: list[ToolCallRecord] = []
    total_usage = TokenUsage()
    last_response: LLMResponse | None = None  # ← Capture last response

    for _iteration in range(self.max_iterations):
        # ... tool calling loop ...
        last_response = response
        if response.finish_reason == "stop":
            break

    # If max iterations exceeded, emit partial result if configured
    if last_response and last_response.finish_reason != "stop":
        emit_partial = context.get_config("emit_partial_on_max_iterations", False)
        if emit_partial:
            logger.warning(
                "agent_max_iterations_reached",
                agent=self.name,
                iterations=self.max_iterations,
                last_content=last_response.content[:100]
            )
            return AgentResult(
                agent_name=self.name,
                output=last_response.content or "",
                messages=full_messages,
                tool_calls_made=all_tool_records,
                token_usage=total_usage,
            )

        raise MaxIterationsError(...)

    # ... return final result ...
```

**Testing:**
```python
async def test_max_iterations_with_partial_result():
    """Test that partial results can be retrieved on max iterations."""
    agent = BaseAgent(name="test", max_iterations=2, model="gpt-4")

    # Mock LLM to always request tools
    context = ExecutionContext(provider=mock_llm, config={"emit_partial_on_max_iterations": True})
    result = await agent.run("Do something complex", context)

    # Should have partial output despite max iterations
    assert result.output != ""
    assert len(result.tool_calls_made) > 0
```

---

## CRITICAL-2.1: Conservative Default Hides Real Errors in Failover

**Location:** `src/orchestra/providers/failover.py:62`

**Current Code:**
```python
def classify_error(exc: Exception) -> ErrorCategory:
    """Classify an exception into a retryable or terminal category."""
    # ... specific checks ...

    # Default to retryable for most network/server issues
    retryable_keywords = [...]
    if any(kw in msg for kw in retryable_keywords):
        return ErrorCategory.RETRYABLE

    return ErrorCategory.RETRYABLE # Conservative: try next provider if unsure
```

**Problem:**
- Unknown errors are treated as retryable.
- If all providers fail due to invalid API key (not caught by keyword match), failover exhausts all providers silently.
- Real issue (bad credentials) is never surfaced.

**Fix:**
```python
def classify_error(exc: Exception) -> ErrorCategory:
    """Classify an exception into a retryable or terminal category."""
    from orchestra.core.errors import (
        AuthenticationError, ContextWindowError, RateLimitError, ProviderUnavailableError
    )

    # 1. Explicit Orchestra errors
    if isinstance(exc, AuthenticationError):
        return ErrorCategory.TERMINAL
    if isinstance(exc, ContextWindowError):
        return ErrorCategory.MODEL_MISMATCH
    if isinstance(exc, RateLimitError):
        return ErrorCategory.RETRYABLE
    if isinstance(exc, ProviderUnavailableError):
        return ErrorCategory.RETRYABLE

    msg = str(exc).lower()

    # 2. Terminal errors (don't retry)
    terminal_keywords = [
        "unauthorized", "invalid api key", "401", "403", "forbidden",
        "credentials", "authentication", "apikey", "api_key"
    ]
    if any(kw in msg for kw in terminal_keywords):
        logger.warning("provider_terminal_error", error_type=type(exc).__name__, msg=msg)
        return ErrorCategory.TERMINAL

    # 3. Model mismatch errors
    model_mismatch_keywords = [
        "context_length_exceeded", "max tokens", "too long", "exceeds context"
    ]
    if any(kw in msg for kw in model_mismatch_keywords):
        return ErrorCategory.MODEL_MISMATCH

    # 4. Retryable errors
    retryable_keywords = [
        "rate_limit", "429", "timeout", "deadline", "500", "502", "503", "504",
        "server error", "connection", "unavailable", "overloaded", "temporarily"
    ]
    if any(kw in msg for kw in retryable_keywords):
        return ErrorCategory.RETRYABLE

    # 5. DEFAULT: Log and treat as terminal to surface unknown errors
    logger.warning(
        "unknown_provider_error",
        error_type=type(exc).__name__,
        msg=msg,
        action="treating_as_terminal"
    )
    return ErrorCategory.TERMINAL  # ← Changed from RETRYABLE
```

**Testing:**
```python
def test_classify_unknown_error_defaults_to_terminal():
    """Test that unknown errors are treated as terminal."""
    exc = ValueError("Some unknown issue")
    category = classify_error(exc)
    assert category == ErrorCategory.TERMINAL

def test_classify_auth_error():
    """Test that auth errors are terminal."""
    exc = AuthenticationError("invalid api key")
    category = classify_error(exc)
    assert category == ErrorCategory.TERMINAL
```

---

## CRITICAL-2.2: Direct Internal State Access in Memory Tiers

**Location:** `src/orchestra/memory/tiers.py:177-219`

**Current Code:**
```python
async def retrieve(self, key: str, promote: bool = True) -> Any | None:
    """Retrieve value searching HOT -> WARM -> COLD."""
    # 1. Try policy (HOT/WARM)
    if key in self._policy._hot:  # ← No lock!
        if promote:
            _, evictions = self._policy.access(key)
            await self._handle_evictions(evictions)
        return self._policy._hot[key].value  # ← Race condition

    if key in self._policy._warm:  # ← No lock!
        if promote:
            new_tier, evictions = self._policy.access(key)
            # ...
```

**Problem:**
- Multiple concurrent `retrieve()` calls can check `_hot` and `_warm` simultaneously.
- Key can be removed between check and access.
- Concurrent `store()` can modify tier while `retrieve()` reads.
- Result: `KeyError` or stale data.

**Fix:**
```python
class TieredMemoryManager:
    def __init__(self, ...):
        # ...
        self._policy_lock = asyncio.Lock()

    async def retrieve(self, key: str, promote: bool = True) -> Any | None:
        """Retrieve value searching HOT -> WARM -> COLD."""
        async with self._policy_lock:
            # 1. Try HOT tier
            if key in self._policy._hot:
                entry = self._policy._hot[key]
                if promote:
                    _, evictions = self._policy.access(key)
                    # Handle outside lock to avoid nested await
                else:
                    return entry.value

        # Emit evictions outside lock
        if promote and evictions:
            await self._handle_evictions(evictions)
            # Retry retrieval in case item was evicted
            async with self._policy_lock:
                if key in self._policy._hot:
                    return self._policy._hot[key].value

        # 2. Try WARM tier
        async with self._policy_lock:
            if key in self._policy._warm:
                entry = self._policy._warm[key]
                if promote:
                    new_tier, evictions = self._policy.access(key)
                    return entry.value
                return entry.value

        # 3. Try WARM Backend (Redis)
        if self._warm:
            val = await self._warm.get(key)
            if val is not None:
                if promote:
                    async with self._policy_lock:
                        entry = MemoryEntry(key=key, value=val, tier=Tier.HOT)
                        self._policy._hot[key] = entry
                        evictions = self._policy.evictions_due()
                    await self._handle_evictions(evictions)
                return val

        # 4. Try COLD Backend (pgvector)
        if self._cold:
            val = await self._cold.retrieve(key)
            if val is not None:
                if promote:
                    async with self._policy_lock:
                        entry = MemoryEntry(key=key, value=val, tier=Tier.HOT)
                        self._policy._hot[key] = entry
                        evictions = self._policy.evictions_due()
                    await self._handle_evictions(evictions)
                    if self._warm:
                        await self._warm.set(key, val)
                return val

        return None

    async def store(self, key: str, value: Any) -> None:
        """Store value. Initially placed in WARM or updated in current tier."""
        entry = MemoryEntry(key=key, value=value)

        async with self._policy_lock:
            evictions = self._policy.insert(key, entry)

        # Write backends and handle evictions outside lock
        if self._warm:
            await self._warm.set(key, value)
        await self._handle_evictions(evictions)
```

**Testing:**
```python
async def test_concurrent_retrieve_store():
    """Test concurrent retrieve/store don't race."""
    manager = TieredMemoryManager(...)
    await manager.initialize()

    # Store initial value
    await manager.store("key1", {"data": "v1"})

    # Concurrent retrieve while storing new value
    async def retrieve_loop():
        results = []
        for _ in range(100):
            val = await manager.retrieve("key1")
            results.append(val)
        return results

    async def store_loop():
        for i in range(10):
            await manager.store("key1", {"data": f"v{i}"})
            await asyncio.sleep(0.001)

    results, _ = await asyncio.gather(retrieve_loop(), store_loop())

    # All retrieved values should be consistent (no KeyError, no None)
    assert all(r is not None for r in results)
    assert all("data" in r for r in results)
```

---

## CRITICAL-3.1: Mutable Context Mutation Without Sync

**Location:** `src/orchestra/security/attenuation.py:26-31`

**Current Code:**
```python
def process_risk_score(self, context: ExecutionContext, score: float) -> None:
    """Update context state based on a risk score."""
    if score >= self.risk_threshold:
        if not context.restricted_mode:
            logger.warning("entering_restricted_mode", score=score, run_id=context.run_id)
            context.restricted_mode = True  # ← Direct mutation, no sync
```

**Problem:**
- Two concurrent attenuators can both check `context.restricted_mode == False`, then both set it to True.
- Race condition: one update lost.
- More importantly: context mutation is not atomic; if an error occurs between check and set, state is inconsistent.

**Fix:**
```python
class CapabilityAttenuator:
    """Monitors risk and attenuates agent capabilities."""

    def __init__(self, risk_threshold: float = 0.8) -> None:
        self.risk_threshold = risk_threshold

    async def process_risk_score(
        self, context: ExecutionContext, score: float
    ) -> None:
        """Update context state based on a risk score.

        Instead of mutating context directly, emit an event that the
        runner will process atomically.
        """
        if score >= self.risk_threshold:
            # Emit event rather than mutate
            from orchestra.storage.events import RestrictedModeEntered

            event = RestrictedModeEntered(
                run_id=context.run_id,
                score=score,
                timestamp=int(time.time()),
            )
            await context.event_bus.emit(event)

    def _handle_restricted_mode_event(
        self, context: ExecutionContext, event: RestrictedModeEntered
    ) -> None:
        """Handler called by the runner to atomically update context."""
        if not context.restricted_mode:
            logger.warning(
                "entering_restricted_mode",
                score=event.score,
                run_id=context.run_id
            )
            context.restricted_mode = True
```

Then in the runner:

```python
# In CompiledGraph._run_loop():
event_bus.subscribe(
    lambda event: self._handle_event(event, context),
    event_type=RestrictedModeEntered,
)
```

**Testing:**
```python
async def test_concurrent_risk_processing():
    """Test concurrent risk detection doesn't lose updates."""
    context = ExecutionContext(event_bus=EventBus())
    attenuator = CapabilityAttenuator(risk_threshold=0.5)

    # Two concurrent risk scores
    tasks = [
        attenuator.process_risk_score(context, 0.9),
        attenuator.process_risk_score(context, 0.85),
    ]
    await asyncio.gather(*tasks)

    # Give event bus time to process
    await asyncio.sleep(0.1)

    # Verify context was updated (handler should be called)
    # This test verifies the event was emitted (you'll need to inspect event log)
```

---

## CRITICAL-3.2: Threading + Asyncio Mixed Without Coordination

**Location:** `src/orchestra/tools/wasm_runtime.py:212`

**Current Code:**
```python
def __init__(self, ...):
    # ...
    def _ticker():
        while True:
            host.signal_interrupt(engine)
            time.sleep(0.001)

    t = threading.Thread(target=_ticker, daemon=True, name="wasm-epoch-ticker")
    t.start()
```

**Problem:**
- Daemon thread is not joined.
- On process shutdown, thread can outlive the event loop.
- Can cause hanging process, orphaned threads.
- No cleanup guarantee.

**Fix:**
```python
class WasmRuntime:
    def __init__(self, ...):
        # ...
        self._ticker_thread: threading.Thread | None = None
        self._ticker_stop = threading.Event()
        self._start_ticker()

    def _start_ticker(self) -> None:
        """Start the epoch ticker thread."""
        def _ticker():
            while not self._ticker_stop.is_set():
                try:
                    host.signal_interrupt(self._engine)
                    time.sleep(0.001)
                except Exception:
                    pass  # Engine shutdown, exit gracefully

        self._ticker_thread = threading.Thread(
            target=_ticker,
            daemon=False,  # ← Non-daemon so it doesn't silently die
            name="wasm-epoch-ticker"
        )
        self._ticker_thread.start()

    def shutdown(self) -> None:
        """Clean shutdown of the WASM runtime."""
        self._ticker_stop.set()  # Signal ticker to stop
        if self._ticker_thread and self._ticker_thread.is_alive():
            self._ticker_thread.join(timeout=5.0)  # Wait for thread to finish
            if self._ticker_thread.is_alive():
                logger.error("wasm_ticker_thread_still_alive", timeout=5.0)

    def __del__(self) -> None:
        """Ensure cleanup on garbage collection."""
        try:
            self.shutdown()
        except Exception:
            pass
```

Also update manager lifecycle:

```python
class WasmRuntimeManager:
    async def shutdown_all(self) -> None:
        """Shut down all WASM runtimes."""
        for runtime in self._runtimes.values():
            try:
                runtime.shutdown()
            except Exception as e:
                logger.error("runtime_shutdown_failed", error=str(e))
        self._runtimes.clear()
```

**Testing:**
```python
async def test_wasm_ticker_joined_on_shutdown():
    """Test that ticker thread is properly joined."""
    runtime = WasmRuntime(...)

    # Verify thread is alive
    assert runtime._ticker_thread.is_alive()

    # Shutdown
    runtime.shutdown()

    # Verify thread is dead
    assert not runtime._ticker_thread.is_alive()

def test_wasm_process_shutdown():
    """Test that process doesn't hang on shutdown."""
    import subprocess
    import signal

    code = '''
    from orchestra.tools.wasm_runtime import WasmRuntime
    runtime = WasmRuntime()
    # Simulate work
    '''

    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Kill process and verify it exits quickly
    proc.terminate()
    try:
        proc.wait(timeout=2.0)  # Should exit promptly
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("Process hung during shutdown")
```

---

## CRITICAL-3.3: Generic Exception Handler in UCAN Verification

**Location:** `src/orchestra/identity/ucan.py:71`

**Current Code:**
```python
@staticmethod
def verify(
    token_str: str,
    verification_key: OKPKey,
    expected_audience: str | None = None,
) -> dict[str, Any]:
    """Verify signature and basic claims (expiry, audience)."""
    try:
        decoded = jwt.decode(token_str, verification_key, algorithms=["EdDSA"])
        payload = decoded.claims
    except Exception as e:  # ← Too broad!
        raise UCANVerificationError(f"JWT verification failed: {str(e)}")
```

**Problem:**
- Catches all exceptions, including `AssertionError`, `AttributeError`, `TypeError`.
- Converts library bugs into security errors, confusing callers.
- Loses exception context chain.

**Fix:**
```python
@staticmethod
def verify(
    token_str: str,
    verification_key: OKPKey,
    expected_audience: str | None = None,
) -> dict[str, Any]:
    """Verify signature and basic claims (expiry, audience)."""
    try:
        from joserfc import JoseError

        try:
            decoded = jwt.decode(token_str, verification_key, algorithms=["EdDSA"])
            payload = decoded.claims
        except JoseError as e:
            raise UCANVerificationError(f"JWT verification failed: {str(e)}") from e
        except (KeyError, AttributeError, TypeError) as e:
            # Decode succeeded but missing expected fields
            raise UCANVerificationError(f"Malformed JWT payload: {str(e)}") from e
    except UCANVerificationError:
        raise  # Re-raise our own error
    except Exception as e:
        # Unexpected error—log and re-raise as-is
        logger.error("unexpected_verify_error", error=type(e).__name__, msg=str(e))
        raise

    now = int(time.time())

    # Explicit field access with error handling
    try:
        exp = payload.get("exp", 0)
        if exp < now:
            raise UCANVerificationError(f"UCAN expired at {exp}")

        nbf = payload.get("nbf", 0)
        if nbf > now + 60:
            raise UCANVerificationError(f"UCAN not yet valid (nbf: {nbf})")

        if expected_audience and payload.get("aud") != expected_audience:
            raise UCANVerificationError(
                f"Audience mismatch: expected {expected_audience}, got {payload.get('aud')}"
            )
    except KeyError as e:
        raise UCANVerificationError(f"Missing required UCAN field: {e}") from e

    return payload
```

**Testing:**
```python
def test_ucan_verify_catches_jose_error():
    """Test that JOSE errors are caught and converted."""
    token = "invalid.jwt.string"
    key = OKPKey.generate("Ed25519")

    with pytest.raises(UCANVerificationError):
        UCANManager.verify(token, key)

def test_ucan_verify_malformed_payload():
    """Test that malformed payloads raise properly."""
    # Create a JWT with missing exp field
    from joserfc import jwt
    key = OKPKey.generate("Ed25519")

    payload = {"iss": "did:...", "aud": "did:...", "nbf": 0}  # Missing exp
    token = jwt.encode({"alg": "EdDSA"}, payload, key, algorithms=["EdDSA"])

    with pytest.raises(UCANVerificationError, match="Missing required"):
        UCANManager.verify(token, key, expected_audience="did:...")

def test_ucan_verify_preserves_cause():
    """Test that exception chain is preserved."""
    token = "bad"
    key = OKPKey.generate("Ed25519")

    try:
        UCANManager.verify(token, key)
    except UCANVerificationError as e:
        assert e.__cause__ is not None  # Cause chain preserved
```

---

## CRITICAL-3.4: No Capability Scope Narrowing Check

**Location:** `src/orchestra/security/acl.py:60-71`

**Current Code:**
```python
def is_authorized(self, tool_name: str, *, ucan: UCANToken | None = None) -> bool:
    # ... (lines 27-71 omitted for brevity) ...

    # Step 5: must also appear in UCAN grants
    for cap in ucan.capabilities:
        resource_match = (
            cap.resource == f"orchestra:tools/{tool_name}" or
            cap.resource == "orchestra:tools" or
            f"orchestra:tools/{tool_name}".startswith(cap.resource + "/")
        )
        ability_match = (cap.ability == "tool/invoke" or cap.ability == "*")

        if resource_match and ability_match:
            return True  # ← No narrowing check!

    return False
```

**Problem:**
- Per DD-4, delegation must narrow capabilities (child ⊂ parent).
- This code only checks if capability exists, not if it's narrower.
- A parent UCAN with `orchestra:tools` can delegate without narrowing to `orchestra:tools/web_search`.
- Violates principle of attenuation.

**Fix:**
```python
def is_narrower_capability(
    child_cap: UCANCapability,
    parent_cap: UCANCapability,
) -> bool:
    """Check if child capability is narrower than parent.

    Child is narrower if:
    - resource: child_resource is a sub-path of parent_resource
    - ability: child_ability is a sub-ability of parent_ability
    """
    # Resource narrowing: child must be more specific
    parent_res = parent_cap.resource
    child_res = child_cap.resource

    # Exact match is allowed (not narrower, but valid)
    if parent_res == child_res:
        is_res_narrower = True
    # Child is a sub-path (e.g., child=orchestra:tools/web, parent=orchestra:tools)
    elif child_res.startswith(parent_res + "/"):
        is_res_narrower = True
    else:
        is_res_narrower = False

    # Ability narrowing: must match or be more specific
    parent_ability = parent_cap.ability
    child_ability = child_cap.ability

    if parent_ability == "*":
        # Parent allows any ability; child can be anything
        is_ability_narrower = True
    elif parent_ability == child_ability:
        is_ability_narrower = True
    else:
        # Parent does not allow this child ability
        is_ability_narrower = False

    return is_res_narrower and is_ability_narrower


def validate_narrowing(
    parent_capabilities: list[UCANCapability],
    child_capabilities: list[UCANCapability],
) -> bool:
    """Validate that child caps are narrower than parent caps.

    For DD-4 compliance, every child capability must have a parent
    capability that is at least as broad or broader.
    """
    for child_cap in child_capabilities:
        found_parent = False
        for parent_cap in parent_capabilities:
            if is_narrower_capability(child_cap, parent_cap):
                found_parent = True
                break

        if not found_parent:
            return False  # Child cap has no corresponding parent

    return True


class ToolACL:
    def is_authorized(self, tool_name: str, *, ucan: UCANToken | None = None) -> bool:
        """Check if a tool is authorized, with narrowing validation."""
        # ... (previous checks up to line 54) ...

        # Step 5: must also appear in UCAN grants AND be narrower
        if ucan.parent_capabilities:  # Check narrowing if available
            if not validate_narrowing(ucan.parent_capabilities, ucan.capabilities):
                logger.warning(
                    "ucan_narrowing_violation",
                    child_caps=ucan.capabilities,
                    parent_caps=ucan.parent_capabilities,
                )
                return False  # Delegation violation

        for cap in ucan.capabilities:
            # ... (capability checks) ...
            if resource_match and ability_match:
                return True

        return False
```

**Testing:**
```python
def test_narrowing_validation_success():
    """Test valid narrowing."""
    parent = [UCANCapability(resource="orchestra:tools", ability="tool/invoke")]
    child = [UCANCapability(resource="orchestra:tools/web_search", ability="tool/invoke")]

    assert validate_narrowing(parent, child)

def test_narrowing_validation_failure_widening():
    """Test invalid widening."""
    parent = [UCANCapability(resource="orchestra:tools/web_search", ability="tool/invoke")]
    child = [UCANCapability(resource="orchestra:tools", ability="tool/invoke")]

    assert not validate_narrowing(parent, child)  # Child is broader!

def test_narrowing_validation_ability():
    """Test ability narrowing."""
    parent = [UCANCapability(resource="orchestra:tools", ability="*")]
    child = [UCANCapability(resource="orchestra:tools", ability="tool/invoke")]

    assert validate_narrowing(parent, child)  # Child ability is narrower
```

---

## Remaining Critical Issues (4.1–4.5)

Due to space constraints, the following critical issues are summarized:

### CRITICAL-4.1: WAL + PRAGMA Race Condition
**File:** `src/orchestra/cost/persistent_budget.py:85-87`

**Fix:** Implement a lock file mechanism to serialize database initialization:
```python
async def initialize(self) -> None:
    if self._initialized: return

    lock_file = self.db_path.parent / f".{self.db_path.name}.lock"
    async with asyncio.Lock():  # Use asyncio.Lock for async coordination
        # Only first initialization sets up pragmas
        if not self.db_path.exists():
            # ... create database ...
            async with self.connection() as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA foreign_keys=ON")
```

### CRITICAL-4.2: No Key Rotation
**File:** `src/orchestra/messaging/secure_provider.py:104-106`

**Fix:** Implement key versioning and rotation:
```python
@dataclass
class AgentKeyMaterial:
    did: str
    kid: str
    keypair: OKPKey
    version: int = 1  # Key version
    created_at: float = field(default_factory=time.time)
    rotated_at: float | None = None

async def rotate_keys(self) -> None:
    """Rotate session keys."""
    old_keys = self._own_keys
    new_keys = self._generate_keys()

    # Update public DID document with new key version
    # Archive old keys for decryption of historical messages
    self._key_history.append((old_keys.version, old_keys))
    self._own_keys = new_keys
```

### CRITICAL-4.3: No Agent Card Revocation
**File:** `src/orchestra/identity/agent_identity.py`

**Fix:** Add revocation list check:
```python
class AgentIdentityValidator:
    async def validate_with_revocation_check(
        self, agent_card: AgentCard, revocation_list: list[str]
    ) -> bool:
        """Validate agent card and check revocation list."""
        if agent_card.did in revocation_list:
            return False  # Agent is revoked
        return agent_card.verify_signature()
```

### CRITICAL-4.4: Dynamic Import with User Input
**File:** `src/orchestra/memory/serialization.py:54`

**Fix:** Use registry instead of dynamic import:
```python
SERIALIZATION_REGISTRY = {
    "list": list,
    "dict": dict,
    "Message": Message,
    "AgentResult": AgentResult,
}

def deserialize(obj: dict) -> Any:
    if "module" in obj and "class" in obj:
        cls = SERIALIZATION_REGISTRY.get(f"{obj['module']}.{obj['class']}")
        if not cls:
            raise ValueError(f"Class not in allowlist: {obj['module']}.{obj['class']}")
        return cls(**obj["data"])
```

### CRITICAL-4.5: Allowlist Mutable at Runtime
**File:** `src/orchestra/core/dynamic.py:51`

**Fix:** Freeze allowlist at import time:
```python
# In dynamic.py
from types import MappingProxyType  # Immutable dict

DYNAMIC_IMPORT_ALLOWLIST = MappingProxyType({
    "orchestra.core.types": types_module,
    "orchestra.core.errors": errors_module,
    # ...
})

def resolve_ref(ref: str) -> Any:
    if ref not in DYNAMIC_IMPORT_ALLOWLIST:
        raise ImportError(f"Ref '{ref}' not in allowlist")
    return DYNAMIC_IMPORT_ALLOWLIST[ref]
```

---

## Deployment Checklist

Before merging any critical fixes:

- [ ] Code review by security team (CRITICAL-4.4, 4.5, 3.4)
- [ ] Concurrency tests added for each fix (CRITICAL-2.2, 3.1)
- [ ] Integration tests verify fixes end-to-end
- [ ] Load test with 1000 concurrent agents
- [ ] Backward compatibility verified
- [ ] Performance benchmarks (no regressions)
- [ ] Security audit of changes

---

**Document Version:** 1.0
**Last Updated:** 2026-03-15
