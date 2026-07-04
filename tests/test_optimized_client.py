"""
tests/test_optimized_client.py
------------------------------
Unit tests verifying the rate limiter, cache managers, historical auto-chunker,
batch quote fetches, circuit breakers, and optimized client.
"""
import time
import pytest
import pandas as pd
from src.utils.rate_limiter import TokenBucketRateLimiter
from src.utils.cache import MarketDataCache
from src.utils.circuit_breaker import CircuitBreaker, CircuitOpenError, retry_with_backoff
from src.data.angel_fetcher import AngelHistoricalFetcher
from src.data.quote_fetcher import BatchQuoteFetcher
from src.data.optimized_client import OptimizedAngelClient, optimized_client

def test_token_bucket_rate_limiter():
    """Verify rate limiter blocks when tokens are exhausted."""
    # Create limiter with rate 5 req/s and capacity 1
    limiter = TokenBucketRateLimiter(rate=5.0, capacity=1.0)
    
    t0 = time.monotonic()
    limiter.acquire("Test 1") # Immediate
    limiter.acquire("Test 2") # Blocks for ~0.2s
    t1 = time.monotonic()
    
    # Assert elapsed time is around 0.2s or higher
    assert t1 - t0 >= 0.15

def test_cache_serialization_parquet(tmp_path):
    """Verify L2 cache stores DataFrames to parquet and JSON sidecars."""
    cache = MarketDataCache(cache_dir=str(tmp_path))
    
    df = pd.DataFrame({"close": [100.0, 105.0]}, index=pd.date_range("2026-07-01", periods=2))
    cache.set_df("test_df", df, ttl=10)
    
    # Retrieve it
    retrieved = cache.get_df("test_df")
    assert retrieved is not None
    assert len(retrieved) == 2
    assert "close" in retrieved.columns
    
    # Verify file existence on disk
    hash_key = cache._hash_key("test_df")
    assert (tmp_path / f"{hash_key}.parquet").exists()
    assert (tmp_path / f"{hash_key}.meta.json").exists()

def test_historical_fetcher_chunk_generation():
    """Verify chunk generation splits wide date ranges properly."""
    fetcher = AngelHistoricalFetcher(MarketDataCache())
    
    start_dt = datetime = pd.Timestamp("2026-01-01").to_pydatetime()
    end_dt = pd.Timestamp("2026-01-31").to_pydatetime()
    
    # Max chunk of 10 days
    chunks = fetcher._generate_chunks(start_dt, end_dt, max_days=10)
    
    assert len(chunks) == 3 # 31 days split into 10-day chunks -> 3 chunks
    assert chunks[0][0] == start_dt
    assert chunks[-1][1] == end_dt

def test_circuit_breaker_states():
    """Verify CLOSED -> OPEN -> HALF_OPEN transitions."""
    cb = CircuitBreaker("TestCB", failure_threshold=2, recovery_timeout=0.2)
    
    # CLOSED state
    assert cb.state == cb.STATE_CLOSED
    
    # Generate failures
    @cb.call
    def fail_call():
        raise ValueError("Fail")

    with pytest.raises(ValueError):
        fail_call()
    assert cb.state == cb.STATE_CLOSED # 1 failure
    
    with pytest.raises(ValueError):
        fail_call()
    assert cb.state == cb.STATE_OPEN # 2 failures -> Trips!
    
    # Calls should fail immediately with CircuitOpenError
    with pytest.raises(CircuitOpenError):
        fail_call()
        
    # Sleep to allow recovery
    time.sleep(0.25)
    
    # Call should transition to HALF_OPEN and allow one probe
    # If probe fails, transitions back to OPEN
    with pytest.raises(ValueError):
        fail_call()
    assert cb.state == cb.STATE_OPEN

def test_optimized_client_stats():
    """Verify request diagnostics are tracked correctly."""
    client = OptimizedAngelClient()
    
    # Seed stats
    client.stats["cache_hits"] = 10
    client.stats["cache_misses"] = 2
    
    stats = client.api_stats()
    assert stats["cache_hits"] == 10
    assert stats["cache_misses"] == 2
    assert stats["hit_ratio_pct"] == 83.33
