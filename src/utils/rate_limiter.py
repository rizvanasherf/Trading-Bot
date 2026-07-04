"""
src/utils/rate_limiter.py
-------------------------
Thread-safe Token Bucket Rate Limiter. Provides granular control over
API request rates and bursts to avoid broker rate limits.
"""
import time
import threading
from typing import Dict
from utils.logger import logger

class TokenBucketRateLimiter:
    def __init__(self, rate: float, capacity: float):
        """
        rate: Number of tokens added per second.
        capacity: Maximum burst capacity of the bucket.
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, name: str = "Request") -> None:
        """Block until a token is available in the bucket."""
        with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.last_update = now
                
                # Top up tokens
                self.tokens = min(self.capacity, self.tokens + (elapsed * self.rate))
                
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                
                # Calculate sleep duration
                needed = 1.0 - self.tokens
                sleep_time = needed / self.rate
                wait_ms = int(sleep_time * 1000)
                logger.debug(f"[{name}] Throttled! Waiting {wait_ms}ms for rate limiter token.")
                
                # Release lock while sleeping to avoid blocking other threads
                self._lock.release()
                try:
                    time.sleep(sleep_time)
                finally:
                    self._lock.acquire()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class BrokerLimiters:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(BrokerLimiters, cls).__new__(cls)
                cls._instance._limiters = {
                    "historical": TokenBucketRateLimiter(rate=2.5, capacity=3.0), # 3/sec limit (keep slightly under)
                    "quotes": TokenBucketRateLimiter(rate=9.0, capacity=10.0),    # 10/sec limit
                    "orders": TokenBucketRateLimiter(rate=9.0, capacity=10.0),    # 10/sec limit
                    "login": TokenBucketRateLimiter(rate=0.8, capacity=1.0),     # 1/sec limit
                    "profile": TokenBucketRateLimiter(rate=0.8, capacity=1.0)     # 1/sec limit
                }
            return cls._instance

    def get(self, key: str) -> TokenBucketRateLimiter:
        return self._limiters.get(key, self._limiters["historical"])

# Singleton instances
broker_limiters = BrokerLimiters()
