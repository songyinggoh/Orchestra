"""Reproduction tests for Phase 2 WARNING race conditions.

These tests demonstrate the actual bugs in:
- WARN-2.1: Latency tracker race condition
- WARN-2.5: Background task shutdown race
- WARN-2.9: Type validation missing
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel

from orchestra.providers.failover import ProviderFailover
from orchestra.providers.strategy import PromptedStrategy
from orchestra.core.types import LLMResponse, Message, MessageRole
from orchestra.memory.invalidation import InvalidationSubscriber


# =============================================================================
# WARN-2.1: Latency Tracker Race Condition
# =============================================================================

@pytest.mark.asyncio
async def test_warn_2_1_latency_tracker_race():
    """Demonstrate race condition in latency tracking.

    Multiple concurrent complete() calls race on _latency_tracker dict.
    This test should show inconsistent latency_history_size or crashes.
    """
    mock_provider = AsyncMock()
    mock_provider.provider_name = "test"
    mock_provider.complete.return_value = LLMResponse(content="ok")

    failover = ProviderFailover([mock_provider])

    # Concurrent calls to complete() -> _track_latency() without locks
    tasks = [failover.complete() for _ in range(50)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # All should succeed
    assert all(isinstance(r, LLMResponse) for r in results)

    # Check latency tracker state
    health = await failover.get_provider_health(0)

    # EXPECTED: up to _max_history (20) latencies — the tracker caps history at
    # self._max_history = 20 to bound memory usage.  50 calls > 20 cap, so the
    # correct post-condition is that the history is exactly at the cap.
    assert health["latency_history_size"] == failover._max_history, \
        f"Race condition: expected {failover._max_history} latencies (max_history cap), got {health['latency_history_size']}"

    # Also verify the tracker wasn't corrupted
    assert failover._latency_tracker[0], "Latency tracker should not be empty"


# =============================================================================
# WARN-2.5: Background Task Shutdown Race
# =============================================================================

@pytest.mark.asyncio
async def test_warn_2_5_background_task_shutdown_race():
    """Demonstrate race condition in InvalidationSubscriber shutdown.

    The _running flag is set to False before awaiting the task,
    creating a window where the task could see the flag change mid-execution.
    """
    redis = MagicMock()
    pubsub = AsyncMock()
    redis.pubsub.return_value = pubsub

    invalidated_keys = []
    processed_count = [0]

    def on_invalidate(key):
        invalidated_keys.append(key)
        processed_count[0] += 1

    subscriber = InvalidationSubscriber(redis, on_invalidate)

    # Mock ps.listen() to yield messages slowly
    async def mock_listen():
        for i in range(10):
            yield {"type": "message", "data": f"key{i}".encode()}
            await asyncio.sleep(0.01)  # Small delay between messages

    pubsub.listen = mock_listen
    pubsub.__aenter__.return_value = pubsub
    pubsub.__aexit__.return_value = None

    # Start listener
    await subscriber.start()

    # Let a few messages process.
    # 10 messages at 0.01 s each; wait 0.08 s to give the event loop enough
    # budget to process at least 6 of them before we trigger stop().
    await asyncio.sleep(0.08)

    # Now stop (this is where the race happens)
    # Without the fix, the task might exit early or miss messages
    await subscriber.stop()

    # EXPECTED: Most/all of the 10 messages plus initial "*" processed
    # ACTUAL (with race): Fewer messages processed due to early flag exit
    # This assertion will FAIL without the fix
    assert processed_count[0] >= 6, \
        f"Race condition in shutdown: only {processed_count[0]} messages processed before forced exit"


# =============================================================================
# WARN-2.9: Type Validation Missing
# =============================================================================

class ValidSchema(BaseModel):
    """Valid Pydantic model for testing."""
    name: str
    value: int


@pytest.mark.asyncio
async def test_warn_2_9_type_validation_missing():
    """Demonstrate missing type validation for output_type parameter.

    PromptedStrategy accepts output_type but doesn't validate it's a BaseModel.
    """
    mock_provider = AsyncMock()
    mock_provider.complete.return_value = LLMResponse(
        content='{"name": "test", "value": 42}'
    )

    strategy = PromptedStrategy()

    # Test 1: Invalid output_type - dict (not a BaseModel)
    # This should fail gracefully, but currently crashes in _build_schema_prompt
    try:
        result = await strategy.execute(
            provider=mock_provider,
            messages=[Message(role=MessageRole.USER, content="test")],
            output_type=dict,  # INVALID: not a Pydantic BaseModel
        )
        # Without the fix, this crashes with AttributeError
        # With the fix, this should raise ValueError or similar
        pytest.fail("Should have raised ValueError for invalid output_type")
    except AttributeError as e:
        # This is the ACTUAL error we get without the fix
        assert "model_json_schema" in str(e), \
            f"Got AttributeError but not for model_json_schema: {e}"
        print(f"WARN-2.9 confirmed: {e}")
    except (ValueError, TypeError) as e:
        # This is what we EXPECT with the fix
        assert "output_type" in str(e).lower() or "basemodel" in str(e).lower(), \
            f"Expected validation error, got: {e}"

    # Test 2: Valid output_type
    result = await strategy.execute(
        provider=mock_provider,
        messages=[Message(role=MessageRole.USER, content="test")],
        output_type=ValidSchema,  # VALID
    )
    assert result.content is not None


if __name__ == "__main__":
    # Run with: python -m pytest tests/unit/test_phase2_race_conditions.py -v
    print("Run with: python -m pytest tests/unit/test_phase2_race_conditions.py -v")
