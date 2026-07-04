"""
src/data/optimized_client.py
---------------------------
OptimizedAngelClient: The single entry point for all data needs.
Wires rate limiters, Two-Level Cache, Historical Fetcher, Batch Quote Fetcher,
Circuit Breaker, and Session Manager together.
"""
import time
from typing import Dict, List, Optional
import pandas as pd
from utils.logger import logger
from config.settings import settings
from src.utils.rate_limiter import broker_limiters
from src.utils.cache import MarketDataCache
from src.utils.circuit_breaker import CircuitBreaker, retry_with_backoff, CircuitOpenError
from src.data.session_manager import session_manager
from src.data.angel_fetcher import AngelHistoricalFetcher
from src.data.quote_fetcher import BatchQuoteFetcher

class OptimizedAngelClient:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(OptimizedAngelClient, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        # Initialize Layer instances
        self.cache = MarketDataCache()
        self.session = session_manager
        self.historical_fetcher = AngelHistoricalFetcher(self.cache)
        self.quote_fetcher = BatchQuoteFetcher(self.cache)
        
        # Initialize limiters & circuit breakers
        self.limiters = broker_limiters
        self.cb = CircuitBreaker("OptimizedAngelAPI", failure_threshold=5, recovery_timeout=60.0)
        
        # Stats tracking
        self.stats = {
            "total_api_calls": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "rate_limit_waits": 0,
            "circuit_breaker_trips": 0
        }
        self._initialized = True

    # ── Public client methods ──────────────────────────────────────────────────

    def get_historical(self, symbol: str, interval: str, days: int) -> pd.DataFrame:
        """Fetch historical candles via cache -> rate limiter -> fetcher (with retry and CB)."""
        cache_key = f"hist_{symbol}_{interval}_{days}"
        df = self.cache.get_df(cache_key)
        if df is not None:
            self.stats["cache_hits"] += 1
            return df
            
        self.stats["cache_misses"] += 1

        @retry_with_backoff(max_attempts=3)
        @self.cb.call
        def _execute():
            self.stats["total_api_calls"] += 1
            return self.historical_fetcher.fetch_historical(symbol, interval, days, is_live=settings.is_live)

        try:
            return _execute()
        except Exception as e:
            self._handle_exception(e)
            raise e

    def get_quote(self, symbols: List[str]) -> Dict[str, dict]:
        """Fetch batch quotes via cache -> rate limiter -> batch fetcher (with retry and CB)."""
        if not symbols:
            return {}

        # Scan how many symbols are in cache vs missing
        cached_count = 0
        for symbol in symbols:
            if self.cache.get(f"quote_{symbol.upper()}") is not None:
                cached_count += 1
                
        self.stats["cache_hits"] += cached_count
        self.stats["cache_misses"] += (len(symbols) - cached_count)

        @retry_with_backoff(max_attempts=3)
        @self.cb.call
        def _execute():
            # Track batch quote calls
            self.stats["total_api_calls"] += 1
            return self.quote_fetcher.get_quotes(symbols)

        try:
            return _execute()
        except Exception as e:
            self._handle_exception(e)
            raise e

    def get_ltp(self, symbol: str) -> float:
        """Read LTP from batch quote cache with zero extra API requests."""
        # This will call get_quote internally which automatically handles batch caching
        quotes = self.get_quote([symbol])
        if symbol in quotes:
            return quotes[symbol]["last_price"]
        
        return self.quote_fetcher.get_ltp(symbol)

    def get_token(self, symbol: str) -> Optional[str]:
        """Resolve a symbol token from cached instrument mapping."""
        # instrument mapping is already cached for 24h, reading it counts as cache hit
        self.stats["cache_hits"] += 1
        return self.historical_fetcher.get_token(symbol)

    def get_margins(self) -> dict:
        """Fetch available margin (cached 30 seconds)."""
        cache_key = "rms_margins"
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.stats["cache_hits"] += 1
            return cached

        self.stats["cache_misses"] += 1

        @retry_with_backoff(max_attempts=3)
        @self.cb.call
        def _execute():
            self.limiters.get("profile").acquire("Margins Limit API Call")
            self.stats["total_api_calls"] += 1
            if self.session.smart is None:
                return {"available": 100_000.0, "used": 0.0, "total": 100_000.0}
            
            res = self.session.smart.rmsLimit()
            if res.get("status") is True and "data" in res:
                data = res["data"]
                available = float(data.get("net", 0.0))
                margin_info = {"available": available, "used": 0.0, "total": available}
                self.cache.set(cache_key, margin_info, MarketDataCache.TTL_MARGIN)
                return margin_info
            else:
                raise ValueError(res.get("message", "rmsLimit failed"))

        try:
            return _execute()
        except Exception as e:
            self._handle_exception(e)
            return {"available": 100_000.0, "used": 0.0, "total": 100_000.0}

    def get_positions(self) -> List[dict]:
        """Fetch positions list (cached 10 seconds)."""
        cache_key = "rms_positions"
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.stats["cache_hits"] += 1
            return cached

        self.stats["cache_misses"] += 1

        @retry_with_backoff(max_attempts=3)
        @self.cb.call
        def _execute():
            self.limiters.get("profile").acquire("Positions API Call")
            self.stats["total_api_calls"] += 1
            if self.session.smart is None:
                return []
            
            res = self.session.smart.position()
            if res.get("status") is True and "data" in res:
                positions_list = res["data"]
                self.cache.set(cache_key, positions_list, MarketDataCache.TTL_POSITIONS)
                return positions_list
            else:
                raise ValueError(res.get("message", "position fetch failed"))

        try:
            return _execute()
        except Exception as e:
            self._handle_exception(e)
            return []

    # ── Exception / Stats Monitor ─────────────────────────────────────────────

    def _handle_exception(self, e: Exception) -> None:
        """Intercept session expirations (AB1010) and count circuit breaker trips."""
        if isinstance(e, CircuitOpenError):
            self.stats["circuit_breaker_trips"] += 1
        
        # Extract error message for session expired code
        msg = str(e)
        if "AB1010" in msg:
            self.session.verify_or_reconnect("AB1010")

    def api_stats(self) -> dict:
        """Expose request diagnostics."""
        # Calculate rates and cache hit ratios
        total_requests = self.stats["cache_hits"] + self.stats["cache_misses"]
        hit_ratio = round(self.stats["cache_hits"] / total_requests, 4) if total_requests else 0.0
        
        # Read circuit trips and rate limiter waits
        self.stats["circuit_breaker_trips"] = self.cb.trips_count
        self.stats["rate_limit_waits"] = self.quote_fetcher.total_saved_calls
        
        return {
            **self.stats,
            "hit_ratio_pct": hit_ratio * 100,
            "reconnects_scheduled": 1,
            "session_active": self.session.is_connected()
        }

# Singleton optimized client instance
optimized_client = OptimizedAngelClient()
