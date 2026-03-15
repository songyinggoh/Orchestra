import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from orchestra.providers.failover import ProviderFailover, ErrorCategory, classify_error
from orchestra.core.errors import (
    AuthenticationError, 
    ContextWindowError, 
    RateLimitError, 
    AllProvidersUnavailableError
)
from orchestra.core.types import LLMResponse
from orchestra.security.circuit_breaker import CircuitState

@pytest.fixture
def mock_provider_1():
    p = AsyncMock()
    p.provider_name = "p1"
    p.complete.return_value = LLMResponse(content="p1 success")
    return p

@pytest.fixture
def mock_provider_2():
    p = AsyncMock()
    p.provider_name = "p2"
    p.complete.return_value = LLMResponse(content="p2 success")
    return p

def test_classify_error():
    assert classify_error(AuthenticationError("bad key")) == ErrorCategory.TERMINAL
    assert classify_error(ContextWindowError("too long")) == ErrorCategory.MODEL_MISMATCH
    assert classify_error(RateLimitError("too fast")) == ErrorCategory.RETRYABLE
    assert classify_error(Exception("503 Service Unavailable")) == ErrorCategory.RETRYABLE
    assert classify_error(Exception("unauthorized")) == ErrorCategory.TERMINAL

@pytest.mark.asyncio
async def test_first_provider_succeeds(mock_provider_1, mock_provider_2):
    failover = ProviderFailover([mock_provider_1, mock_provider_2])
    result = await failover.complete()
    assert result.content == "p1 success"
    mock_provider_1.complete.assert_called_once()
    mock_provider_2.complete.assert_not_called()

@pytest.mark.asyncio
async def test_failover_to_second(mock_provider_1, mock_provider_2):
    mock_provider_1.complete.side_effect = Exception("500 Internal Server Error")
    failover = ProviderFailover([mock_provider_1, mock_provider_2])
    result = await failover.complete()
    assert result.content == "p2 success"
    mock_provider_1.complete.assert_called_once()
    mock_provider_2.complete.assert_called_once()

@pytest.mark.asyncio
async def test_circuit_breaker_opens(mock_provider_1, mock_provider_2):
    mock_provider_1.complete.side_effect = Exception("500 Error")
    # Threshold=1 for quick test
    failover = ProviderFailover([mock_provider_1, mock_provider_2], failure_threshold=1)
    
    # First call: p1 fails, p2 succeeds
    await failover.complete()
    assert failover.breakers[0].state == CircuitState.OPEN
    
    # Second call: p1 should be skipped due to OPEN circuit
    mock_provider_1.complete.reset_mock()
    await failover.complete()
    mock_provider_1.complete.assert_not_called()

@pytest.mark.asyncio
async def test_terminal_error_raises_immediately(mock_provider_1, mock_provider_2):
    mock_provider_1.complete.side_effect = AuthenticationError("Invalid Key")
    failover = ProviderFailover([mock_provider_1, mock_provider_2])
    
    with pytest.raises(AuthenticationError):
        await failover.complete()
    mock_provider_2.complete.assert_not_called()

@pytest.mark.asyncio
async def test_all_providers_fail_raises(mock_provider_1, mock_provider_2):
    mock_provider_1.complete.side_effect = Exception("500 Error")
    mock_provider_2.complete.side_effect = Exception("503 Error")
    failover = ProviderFailover([mock_provider_1, mock_provider_2])
    
    with pytest.raises(AllProvidersUnavailableError):
        await failover.complete()

@pytest.mark.asyncio
async def test_latency_tracking(mock_provider_1):
    failover = ProviderFailover([mock_provider_1])
    await failover.complete()

    health = await failover.get_provider_health(0)
    assert health["latency_history_size"] == 1
    assert "p50_latency_ms" in health
    assert health["name"] == "p1"
