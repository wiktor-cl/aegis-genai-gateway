import time

import pytest

from aegis.providers.circuit_breaker import CircuitBreakerRegistry, CircuitOpenError, CircuitState


def test_starts_closed() -> None:
    registry = CircuitBreakerRegistry()
    assert registry.state_of("bedrock") == CircuitState.CLOSED
    registry.before_call("bedrock")  # must not raise


def test_opens_after_threshold_failures() -> None:
    registry = CircuitBreakerRegistry(failure_threshold=3)
    for _ in range(3):
        registry.on_failure("bedrock")
    assert registry.state_of("bedrock") == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        registry.before_call("bedrock")


def test_success_resets_failure_count() -> None:
    registry = CircuitBreakerRegistry(failure_threshold=3)
    registry.on_failure("bedrock")
    registry.on_failure("bedrock")
    registry.on_success("bedrock")
    registry.on_failure("bedrock")
    assert registry.state_of("bedrock") == CircuitState.CLOSED


def test_half_open_after_reset_timeout_then_closes_on_success() -> None:
    registry = CircuitBreakerRegistry(failure_threshold=1, reset_timeout_s=0.02)
    registry.on_failure("bedrock")
    assert registry.state_of("bedrock") == CircuitState.OPEN

    time.sleep(0.15)
    registry.before_call("bedrock")  # should flip to HALF_OPEN, not raise
    assert registry.state_of("bedrock") == CircuitState.HALF_OPEN

    registry.on_success("bedrock")
    assert registry.state_of("bedrock") == CircuitState.CLOSED


def test_half_open_reopens_on_failure() -> None:
    registry = CircuitBreakerRegistry(failure_threshold=1, reset_timeout_s=0.02)
    registry.on_failure("bedrock")
    time.sleep(0.15)
    registry.before_call("bedrock")
    registry.on_failure("bedrock")
    assert registry.state_of("bedrock") == CircuitState.OPEN


def test_breakers_are_independent_per_provider() -> None:
    registry = CircuitBreakerRegistry(failure_threshold=1)
    registry.on_failure("bedrock")
    assert registry.state_of("bedrock") == CircuitState.OPEN
    assert registry.state_of("foundry") == CircuitState.CLOSED
