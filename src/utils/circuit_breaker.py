"""
src/utils/circuit_breaker.py
----------------------------
Circuit Breaker & Retry with Exponential Backoff.
Protects backend calls from cascading failures and automatically
recovers from transient network or broker failures.
"""
import time
import random
import functools
import threading
from typing import Callable, Any
from utils.logger import logger

class CircuitOpenError(Exception):
    """Raised when the circuit breaker is in the OPEN state and blocks requests."""
    pass


class CircuitBreaker:
    STATE_CLOSED = "CLOSED"
    STATE_OPEN = "OPEN"
    STATE_HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        name: str = "API",
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state = self.STATE_CLOSED
        self.failures = 0
        self.last_state_change = time.monotonic()
        self.probe_calls = 0
        self.trips_count = 0
        self._lock = threading.Lock()

    def call(self, func: Callable) -> Callable:
        """Decorator wrapping any API call with circuit breaker rules."""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Check state before making the call
            self._before_call()
            
            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result
            except Exception as e:
                # Do not count CircuitOpenError itself as a failure
                if not isinstance(e, CircuitOpenError):
                    self._on_failure(e)
                raise e
        return wrapper

    def _before_call(self) -> None:
        """Enforce circuit state checks and transition states if timeout has elapsed."""
        with self._lock:
            now = time.monotonic()
            
            # Transition OPEN -> HALF_OPEN after timeout
            if self.state == self.STATE_OPEN:
                if now - self.last_state_change >= self.recovery_timeout:
                    self.state = self.STATE_HALF_OPEN
                    self.probe_calls = 0
                    self.last_state_change = now
                    logger.warning(f"[Circuit Breaker '{self.name}'] Transitioning OPEN -> HALF_OPEN. Allowing probe call.")
                else:
                    logger.error(f"[Circuit Breaker '{self.name}'] Call blocked (State: OPEN). Time left: {int(self.recovery_timeout - (now - self.last_state_change))}s")
                    raise CircuitOpenError(f"Circuit '{self.name}' is OPEN. API calls blocked.")
            
            # Limit probe calls in HALF_OPEN
            if self.state == self.STATE_HALF_OPEN:
                if self.probe_calls >= self.half_open_max_calls:
                    raise CircuitOpenError(f"Circuit '{self.name}' is HALF_OPEN. Awaiting probe results.")
                self.probe_calls += 1

    def _on_success(self) -> None:
        """Handle successful call: reset failures and close the circuit if it was half-open."""
        with self._lock:
            if self.state == self.STATE_HALF_OPEN:
                self.state = self.STATE_CLOSED
                self.failures = 0
                self.last_state_change = time.monotonic()
                logger.success(f"[Circuit Breaker '{self.name}'] Probe successful! Closing circuit.")
            elif self.state == self.STATE_CLOSED:
                self.failures = 0

    def _on_failure(self, exc: Exception) -> None:
        """Handle call failure: increment failures, trip circuit to OPEN if threshold is crossed."""
        with self._lock:
            now = time.monotonic()
            self.failures += 1
            logger.warning(f"[Circuit Breaker '{self.name}'] Failure detected ({self.failures}/{self.failure_threshold}): {exc}")

            if self.state in [self.STATE_CLOSED, self.STATE_HALF_OPEN]:
                if self.failures >= self.failure_threshold or self.state == self.STATE_HALF_OPEN:
                    self.state = self.STATE_OPEN
                    self.last_state_change = now
                    self.trips_count += 1
                    logger.error(f"[Circuit Breaker '{self.name}'] Tripped to OPEN! Blocking API calls for {self.recovery_timeout} seconds.")


def retry_with_backoff(
    max_attempts: int = 3,
    initial_backoff: float = 1.0,
    backoff_factor: float = 2.0,
    jitter: float = 0.1
) -> Callable:
    """Decorator to retry a function with exponential backoff and jitter."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            backoff = initial_backoff
            
            while True:
                attempts += 1
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # Do not retry if the circuit is open
                    if isinstance(e, CircuitOpenError):
                        raise e
                    
                    if attempts >= max_attempts:
                        logger.error(f"[Retry] Attempt {attempts}/{max_attempts} failed. Max retries exceeded.")
                        raise e
                    
                    # Compute backoff with jitter
                    current_jitter = random.uniform(-jitter, jitter)
                    sleep_time = max(0.1, backoff + current_jitter)
                    logger.warning(f"[Retry] Attempt {attempts}/{max_attempts} failed: {e}. Retrying in {sleep_time:.2f}s...")
                    
                    time.sleep(sleep_time)
                    backoff *= backoff_factor
        return wrapper
    return decorator
