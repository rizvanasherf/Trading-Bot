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

def test_cpr_strategy_triggers_bullish_and_bearish(cpr_config):
    # Setup mock data fetcher
    mock_fetcher = MagicMock()
    
    # Previous day OHLC: High = 100, Low = 98, Close = 99
    # Pivot = 99, BC = 99, TC = 99 -> CPR range: [99, 99]
    df_daily = pd.DataFrame({
        "open": [99.0],
        "high": [100.0],
        "low": [98.0],
        "close": [99.0],
        "volume": [1000]
    }, index=[datetime(2026, 8, 3)])
    
    mock_fetcher.get_historical_data_yfinance.return_value = df_daily
    
    strat = CPRIntradayStrategy(cpr_config)
    strat.data_fetcher = mock_fetcher
    
    # Generate 35 warmup candles on the previous day (August 3rd)
    warmup_times = [datetime(2026, 8, 3, 15, 30) - timedelta(minutes=5 * (35 - i)) for i in range(35)]
    df_warmup = pd.DataFrame({
        "open": [98.0] * 35,
        "high": [98.5] * 35,
        "low": [97.5] * 35,
        "close": [98.0] * 35,
        "volume": [100.0] * 35
    }, index=warmup_times)
    
    # 5 intraday candles today starting at 9:15 AM
    times = [
        datetime(2026, 8, 4, 9, 15), # 5m candle 1
        datetime(2026, 8, 4, 9, 20), # 5m candle 2
        datetime(2026, 8, 4, 9, 25), # 5m candle 3: closes at 100.1 above cpr_max = 99 (establishes Bullish Bias)
        datetime(2026, 8, 4, 9, 30), # 4th candle: flat/setup
        datetime(2026, 8, 4, 9, 35)  # 5th candle: closes at 101.2 above EMA20 and breaks prev high (100.0)
    ]
    df_today = pd.DataFrame({
        "open":  [98.0, 99.0, 99.5, 99.6, 99.8],
        "high":  [99.2, 99.6, 100.2, 100.0, 101.5],
        "low":   [97.8, 98.8, 99.4, 99.5, 99.7],
        "close": [99.0, 99.5, 100.1, 99.7, 101.2],
        "volume": [100.0] * 5
    }, index=times)
    
    df_bullish = pd.concat([df_warmup, df_today])
    signals = strat.generate_signals("NIFTY", df_bullish)
    assert len(signals) == 1
    assert signals[0].direction == Direction.LONG
    assert signals[0].entry_price == 101.2

# ── State Machine Verification Unit Tests ───────────────────────────────────

class MockCPRStrategy(CPRIntradayStrategy):
    @property
    def warmup_period(self) -> int:
        return 0

def _create_mock_strategy(cpr_config, cpr_range=(99.0, 101.0), breakout_buffer=0.0, bias_cutoff_time="14:30"):
    # Helper to mock CPR calculations and custom config
    cfg = cpr_config.copy()
    cfg["cpr_intraday"]["breakout_buffer"] = breakout_buffer
    cfg["cpr_intraday"]["bias_cutoff_time"] = bias_cutoff_time
    
    mock_fetcher = MagicMock()
    # Mock daily returns to produce cpr_vals: pivot = 100.0, tc = 101.0, bc = 99.0 (CPR: [99.0, 101.0])
    df_daily = pd.DataFrame({
        "open": [100.0],
        "high": [102.0],
        "low": [98.0],
        "close": [100.0],
        "volume": [1000]
    }, index=[datetime(2026, 8, 3)])
    mock_fetcher.get_historical_data_yfinance.return_value = df_daily
    
    strat = MockCPRStrategy(cfg)
    strat.data_fetcher = mock_fetcher
    return strat

def test_cpr_state_machine_no_breakout(cpr_config):
    # Scenario 1: No breakout at all -> trend_bias stays None
    strat = _create_mock_strategy(cpr_config)
    times = [datetime(2026, 8, 4, 9, 15) + timedelta(minutes=5 * i) for i in range(10)]
    df = pd.DataFrame({
        "open": [100.0] * 10, "high": [100.5] * 10, "low": [99.5] * 10, "close": [100.0] * 10, "volume": [100] * 10
    }, index=times)
    
    strat.generate_signals("NIFTY", df)
    assert strat.trend_bias is None
    assert strat.breakout_candidate is None

def test_cpr_state_machine_false_breakout(cpr_config):
    # Scenario 2: Single candle above CPR, then back inside -> None (false breakout rejected)
    strat = _create_mock_strategy(cpr_config)
    times = [datetime(2026, 8, 4, 9, 15) + timedelta(minutes=5 * i) for i in range(5)]
    closes = [100.0, 101.5, 100.0, 100.0, 100.0]  # index 1 (101.5) is above cpr_max = 101.0
    df = pd.DataFrame({
        "open": closes, "high": [c + 0.1 for c in closes], "low": [c - 0.1 for c in closes], "close": closes, "volume": [100] * 5
    }, index=times)
    
    strat.generate_signals("NIFTY", df)
    # The last candle in df is currently forming, so completed candles are first 4:
    # 9:15: close 100.0 -> inside
    # 9:20: close 101.5 -> candidate = BULLISH
    # 9:25: close 100.0 -> fails to confirm, candidate becomes None
    # 9:30: close 100.0 -> inside
    assert strat.trend_bias is None
    assert strat.breakout_candidate is None

def test_cpr_state_machine_confirmed_bullish(cpr_config):
    # Scenario 3: Confirmed bullish: inside -> above -> above -> "BULLISH"
    strat = _create_mock_strategy(cpr_config)
    times = [datetime(2026, 8, 4, 9, 15) + timedelta(minutes=5 * i) for i in range(5)]
    closes = [100.0, 101.5, 101.8, 100.0, 100.0]
    df = pd.DataFrame({
        "open": closes, "high": [c + 0.1 for c in closes], "low": [c - 0.1 for c in closes], "close": closes, "volume": [100] * 5
    }, index=times)
    
    strat.generate_signals("NIFTY", df)
    # Completed:
    # 9:15: close 100.0 (inside)
    # 9:20: close 101.5 (above) -> candidate = BULLISH
    # 9:25: close 101.8 (above) -> confirmed! trend_bias = BULLISH
    # 9:30: close 100.0 (bias already locked, stays BULLISH)
    assert strat.trend_bias == "BULLISH"

def test_cpr_state_machine_confirmed_bearish(cpr_config):
    # Scenario 4: Confirmed bearish: inside -> below -> below -> "BEARISH"
    strat = _create_mock_strategy(cpr_config)
    times = [datetime(2026, 8, 4, 9, 15) + timedelta(minutes=5 * i) for i in range(5)]
    closes = [100.0, 98.5, 98.2, 100.0, 100.0]
    df = pd.DataFrame({
        "open": closes, "high": [c + 0.1 for c in closes], "low": [c - 0.1 for c in closes], "close": closes, "volume": [100] * 5
    }, index=times)
    
    strat.generate_signals("NIFTY", df)
    # Completed:
    # 9:15: close 100.0 (inside)
    # 9:20: close 98.5 (below) -> candidate = BEARISH
    # 9:25: close 98.2 (below) -> confirmed! trend_bias = BEARISH
    assert strat.trend_bias == "BEARISH"

def test_cpr_state_machine_lock_first_bullish(cpr_config):
    # Scenario 5: Bullish confirmed first, bearish breakout happens later same day -> stays "BULLISH" (first confirmed wins)
    strat = _create_mock_strategy(cpr_config)
    times = [datetime(2026, 8, 4, 9, 15) + timedelta(minutes=5 * i) for i in range(7)]
    closes = [100.0, 101.5, 101.8, 100.0, 98.0, 97.5, 100.0]
    df = pd.DataFrame({
        "open": closes, "high": [c + 0.1 for c in closes], "low": [c - 0.1 for c in closes], "close": closes, "volume": [100] * 7
    }, index=times)
    
    strat.generate_signals("NIFTY", df)
    # 9:20 & 9:25: Above -> locked BULLISH
    # 9:35 & 9:40: Below -> should be ignored since bias is locked
    assert strat.trend_bias == "BULLISH"

def test_cpr_state_machine_lock_first_bearish(cpr_config):
    # Scenario 6: Bearish confirmed first, bullish breakout happens later same day -> stays "BEARISH"
    strat = _create_mock_strategy(cpr_config)
    times = [datetime(2026, 8, 4, 9, 15) + timedelta(minutes=5 * i) for i in range(7)]
    closes = [100.0, 98.5, 98.2, 100.0, 102.0, 102.5, 100.0]
    df = pd.DataFrame({
        "open": closes, "high": [c + 0.1 for c in closes], "low": [c - 0.1 for c in closes], "close": closes, "volume": [100] * 7
    }, index=times)
    
    strat.generate_signals("NIFTY", df)
    # 9:20 & 9:25: Below -> locked BEARISH
    assert strat.trend_bias == "BEARISH"

def test_cpr_state_machine_failed_then_succeeds(cpr_config):
    # Scenario 7: Failed bullish candidate followed by a real confirmed bullish breakout -> "BULLISH"
    strat = _create_mock_strategy(cpr_config)
    times = [datetime(2026, 8, 4, 9, 15) + timedelta(minutes=5 * i) for i in range(7)]
    closes = [100.0, 101.5, 100.0, 101.6, 101.9, 100.0, 100.0]
    df = pd.DataFrame({
        "open": closes, "high": [c + 0.1 for c in closes], "low": [c - 0.1 for c in closes], "close": closes, "volume": [100] * 7
    }, index=times)
    
    strat.generate_signals("NIFTY", df)
    # 9:20: close 101.5 (BULLISH candidate)
    # 9:25: close 100.0 (fails, candidate = None)
    # 9:30: close 101.6 (BULLISH candidate)
    # 9:35: close 101.9 (BULLISH confirmed!)
    assert strat.trend_bias == "BULLISH"

def test_cpr_state_machine_currently_forming_candle(cpr_config):
    # Scenario 8: Currently-forming (incomplete) candle must never trigger or confirm a bias
    strat = _create_mock_strategy(cpr_config)
    times = [datetime(2026, 8, 4, 9, 15) + timedelta(minutes=5 * i) for i in range(3)]
    closes = [100.0, 101.5, 101.8]  # index 2 (101.8) is the last candle (currently forming)
    df = pd.DataFrame({
        "open": closes, "high": [c + 0.1 for c in closes], "low": [c - 0.1 for c in closes], "close": closes, "volume": [100] * 3
    }, index=times)
    
    strat.generate_signals("NIFTY", df)
    # Completed is only 9:15 and 9:20.
    # 9:15: close 100.0
    # 9:20: close 101.5 -> candidate = BULLISH
    # 9:25: close 101.8 (currently forming, ignored!)
    # Trend bias must still be None
    assert strat.trend_bias is None
    assert strat.breakout_candidate == "BULLISH"

def test_cpr_state_machine_new_day_reset(cpr_config):
    # Scenario 9: New trading day always starts with trend_bias = None, regardless of yesterday's locked value
    strat = _create_mock_strategy(cpr_config)
    
    # Yesterday: Bullish locked
    times_yesterday = [datetime(2026, 8, 4, 9, 15) + timedelta(minutes=5 * i) for i in range(5)]
    closes_yesterday = [100.0, 101.5, 101.8, 100.0, 100.0]
    df_yesterday = pd.DataFrame({
        "open": closes_yesterday, "high": [c + 0.1 for c in closes_yesterday], "low": [c - 0.1 for c in closes_yesterday], "close": closes_yesterday, "volume": [100] * 5
    }, index=times_yesterday)
    
    strat.generate_signals("NIFTY", df_yesterday)
    assert strat.trend_bias == "BULLISH"
    
    # Today: Starts, flat prices inside CPR
    times_today = [datetime(2026, 8, 5, 9, 15) + timedelta(minutes=5 * i) for i in range(5)]
    closes_today = [100.0, 100.0, 100.0, 100.0, 100.0]
    df_today = pd.DataFrame({
        "open": closes_today, "high": [c + 0.1 for c in closes_today], "low": [c - 0.1 for c in closes_today], "close": closes_today, "volume": [100] * 5
    }, index=times_today)
    
    strat.generate_signals("NIFTY", df_today)
    # Must have reset for the new day
    assert strat.trend_bias is None
    assert strat.breakout_candidate is None

def test_cpr_state_machine_time_cutoff(cpr_config):
    # Scenario 10: Time cutoff: breakout confirmed before cutoff (e.g. 14:30) is valid; no new bias establishable after cutoff
    strat = _create_mock_strategy(cpr_config, bias_cutoff_time="14:30")
    
    # Closes outside CPR after cutoff (14:35 and 14:40)
    times_late = [
        datetime(2026, 8, 4, 14, 30), # 14:30 completed candle (last moment inside cutoff)
        datetime(2026, 8, 4, 14, 35), # 14:35 completed candle (exceeds cutoff)
        datetime(2026, 8, 4, 14, 40), # 14:40 completed candle
        datetime(2026, 8, 4, 14, 45)  # 14:45 forming
    ]
    closes_late = [100.0, 101.5, 101.8, 100.0]
    df_late = pd.DataFrame({
        "open": closes_late, "high": [c + 0.1 for c in closes_late], "low": [c - 0.1 for c in closes_late], "close": closes_late, "volume": [100] * 4
    }, index=times_late)
    
    strat.generate_signals("NIFTY", df_late)
    # The 14:35 candle close at 101.5 is outside the allowed bias window.
    # Therefore candidate should not even be established.
    assert strat.trend_bias is None
    assert strat.breakout_candidate is None

