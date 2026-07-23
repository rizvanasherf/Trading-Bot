"""
tests/test_cpr_strategy.py
--------------------------
Unit tests for the CPRIntradayStrategy module.
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from core.cpr_strategy import CPRIntradayStrategy
from core.strategy import Direction, Signal
from utils.helpers import now_ist

@pytest.fixture
def cpr_config():
    return {
        "strategy": {
            "strategy_type": "cpr_intraday",
            "timeframe": "5minute"
        },
        "cpr_intraday": {
            "ema_period": 20,
            "volume_period": 20,
            "volume_multiplier": 1.1,
            "narrow_cpr_threshold": 0.05,
            "wide_cpr_threshold": 0.15,
            "stop_loss_type": "logical",
            "atr_period": 14,
            "atr_multiplier": 1.5,
            "risk_reward_ratio": 2.0
        }
    }

def test_cpr_level_calculations(cpr_config, monkeypatch):
    # Mock data fetcher historical call
    mock_fetcher = MagicMock()
    
    # Mock previous day OHLC data
    # Pivot = (100 + 80 + 90) / 3 = 90
    # BC = (100 + 80) / 2 = 90
    # TC = (90 - 90) + 90 = 90
    dates = [now_ist() - timedelta(days=2), now_ist() - timedelta(days=1)]
    df_daily = pd.DataFrame({
        "open": [92, 90],
        "high": [100, 100],
        "low": [80, 80],
        "close": [90, 90],
        "volume": [1000, 1000]
    }, index=dates)
    
    mock_fetcher.get_historical_data.return_value = df_daily
    mock_fetcher.get_historical_data_yfinance.return_value = df_daily
    
    # Use monkeypatch to assign our mock data fetcher
    strat = CPRIntradayStrategy(cpr_config)
    strat.data_fetcher = mock_fetcher
    
    cpr = strat.calculate_cpr("NIFTY")
    
    assert cpr is not None
    pivot, tc, bc = cpr
    assert pivot == 90.0
    assert bc == 90.0
    assert tc == 90.0

def test_cpr_strategy_signals_wait(cpr_config, monkeypatch):
    # Prepare intraday 5m data
    now = now_ist()
    times = [now - timedelta(minutes=5 * i) for i in range(100, 0, -1)]
    
    df_intraday = pd.DataFrame({
        "open": [100.0] * 100,
        "high": [101.0] * 100,
        "low": [99.0] * 100,
        "close": [100.0] * 100,
        "volume": [100.0] * 100
    }, index=times)
    
    # Mock calls
    mock_fetcher = MagicMock()
    # Daily OHLC for NIFTY spot
    df_daily = pd.DataFrame({
        "open": [100.0],
        "high": [105.0],
        "low": [95.0],
        "close": [100.0],
        "volume": [5000.0]
    }, index=[now - timedelta(days=1)])
    
    mock_fetcher.get_historical_data.side_effect = lambda sym, interval, days: (
        df_daily if interval == "day" else df_intraday
    )
    mock_fetcher.get_historical_data_yfinance.side_effect = lambda sym, interval, days: (
        df_daily if interval == "day" else df_intraday
    )
    
    strat = CPRIntradayStrategy(cpr_config)
    strat.data_fetcher = mock_fetcher
    
    # Should not produce signals under flat sideways conditions
    signals = strat.generate_signals("NIFTY", df_intraday)
    assert len(signals) == 0
