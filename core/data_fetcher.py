"""
core/data_fetcher.py
--------------------
KiteDataFetcher wraps Angel One SmartAPI to fetch market data (historical, LTP, quote)
for Indian NSE equities. It keeps an Angel Connect client instance available for
the OrderExecutor to place live orders if credentials are provided.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config.settings import settings
from utils.logger import logger
from utils.helpers import now_ist, IST
from src.data.angel_connector import connector
from src.data.optimized_client import optimized_client


# ══════════════════════════════════════════════════════════════════════════════
# Mock data helpers
# ══════════════════════════════════════════════════════════════════════════════

def _generate_mock_ohlcv(
    symbol: str,
    n: int = 100,
    base_price: float = 2000.0,
    interval_minutes: int = 15,
) -> pd.DataFrame:
    """Synthetic OHLCV for testing / mock mode."""
    rng = np.random.default_rng(hash(symbol) % (2**32))
    returns = rng.normal(0.0002, 0.008, n)
    closes = base_price * np.cumprod(1 + returns)

    highs = closes * rng.uniform(1.001, 1.015, n)
    lows = closes * rng.uniform(0.985, 0.999, n)
    opens = np.roll(closes, 1)
    opens[0] = base_price
    volumes = rng.integers(100_000, 1_000_000, n).astype(float)

    now = now_ist().replace(second=0, microsecond=0)
    dates = [now - timedelta(minutes=interval_minutes * i) for i in range(n, 0, -1)]

    return pd.DataFrame(
        {"date": dates, "open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}
    ).set_index("date")


MOCK_BASE_PRICES = {
    "RELIANCE": 2800.0, "TCS": 3900.0, "INFY": 1500.0, "HDFCBANK": 1600.0,
    "ICICIBANK": 950.0, "SBIN": 650.0, "BAJFINANCE": 6800.0, "WIPRO": 450.0,
    "AXISBANK": 1100.0, "MARUTI": 10500.0,
}


# ══════════════════════════════════════════════════════════════════════════════
# Main class
# ══════════════════════════════════════════════════════════════════════════════

class KiteDataFetcher:
    def __init__(self):
        # is_mock runs if settings are not configured or if connection failed
        self._mock_mode = not settings.angel_configured or optimized_client.session.smart is None

    @property
    def is_mock(self) -> bool:
        self._mock_mode = not settings.angel_configured or optimized_client.session.smart is None
        return self._mock_mode

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_historical_data(
        self,
        symbol: str,
        interval: str = "15minute",
        days: int = 30,
    ) -> pd.DataFrame:
        """Return OHLCV DataFrame indexed by datetime (IST) using OptimizedAngelClient."""
        if self.is_mock:
            n_candles = min(days * 26, 500)
            return _generate_mock_ohlcv(
                symbol,
                n=n_candles,
                base_price=MOCK_BASE_PRICES.get(symbol.upper(), 1000.0),
            )

        return optimized_client.get_historical(symbol, interval, days)

    def get_ltp(self, symbol: str) -> float:
        """Last traded price from OptimizedAngelClient."""
        if self.is_mock:
            base = MOCK_BASE_PRICES.get(symbol.upper(), 1000.0)
            return round(base * random.uniform(0.995, 1.005), 2)

        return optimized_client.get_ltp(symbol)

    def get_quote(self, symbol: str) -> dict:
        """Full market quote from OptimizedAngelClient."""
        if self.is_mock:
            ltp = self.get_ltp(symbol)
            return {
                "last_price": ltp,
                "ohlc": {"open": ltp * 0.998, "high": ltp * 1.01, "low": ltp * 0.99, "close": ltp},
                "volume": random.randint(500_000, 5_000_000),
                "average_price": ltp,
            }

        quotes = optimized_client.get_quote([symbol])
        if symbol in quotes:
            return quotes[symbol]
        
        # Fallback to get_ltp
        ltp = self.get_ltp(symbol)
        return {
            "last_price": ltp,
            "ohlc": {"open": ltp * 0.998, "high": ltp * 1.01, "low": ltp * 0.99, "close": ltp},
            "volume": 0,
            "average_price": ltp
        }

    def get_account_balance(self) -> dict:
        """Available funds / margin from OptimizedAngelClient."""
        if self.is_mock:
            return {"available": 100_000.0, "used": 0.0, "total": 100_000.0}
            
        return optimized_client.get_margins()
