"""
tests/test_vwap_pullback.py
---------------------------
Unit tests for the VWAPPullbackStrategy.
"""
import pytest
import pandas as pd
from datetime import datetime
from core.vwap_pullback_strategy import VWAPPullbackStrategy
from core.strategy import Direction, Signal

@pytest.fixture
def vp_config():
    return {
        "strategy": {
            "timeframe": "5minute"
        },
        "vwap_pullback": {
            "ema_period": 3,
            "vwap_buffer_pct": 0.002, # 0.2%
            "volume_period": 3,
            "volume_multiplier": 1.2,
            "stop_loss_pct": 0.005,
            "lookback_swings": 5
        }
    }

def test_generate_signals_long_pullback(vp_config):
    strat = VWAPPullbackStrategy(vp_config)
    
    # We want to mock a series of candles:
    # 1. Warmup candles (5 bars)
    # 2. Bullish trend above VWAP & EMA9.
    # 3. Pullback to VWAP (low matches or dips near VWAP).
    # 4. Confirmation candle: Close > Open, Volume > avg * 1.2.
    
    dates = [
        datetime(2026, 7, 2, 9, 15),
        datetime(2026, 7, 2, 9, 20),
        datetime(2026, 7, 2, 9, 25),
        datetime(2026, 7, 2, 9, 30),
        datetime(2026, 7, 2, 9, 35),
        datetime(2026, 7, 2, 9, 40), # Pullback bar (low touches VWAP)
        datetime(2026, 7, 2, 9, 45)  # Confirmation bar
    ]
    
    # Let's say vwap is roughly 100
    opens =   [100, 101, 102, 103, 104, 102.5, 100.5]
    highs =   [101, 103, 104, 105, 105, 103.0, 102.8]
    lows =    [99,  100, 101, 102, 103, 99.9,  100.2] # Low at index 5 (99.9) touches VWAP (~100.1)
    closes =  [100, 102, 103, 104, 103, 100.5, 102.5] # Close at index 6 (102.5) is bullish close > open (100.5)
    volumes = [100, 100, 100, 100, 100, 100,   250]   # Confirmation volume (250) is > avg (100) * 1.2
    
    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    }, index=dates)
    
    # Calculate indicators manually for verification
    vwap_vals = strat._calculate_vwap(df)
    ema_vals = df["close"].ewm(span=9, adjust=False).mean()
    
    signals = strat.generate_signals("RELIANCE", df)
    
    assert len(signals) == 1
    sig = signals[0]
    assert sig.symbol == "RELIANCE"
    assert sig.direction == Direction.LONG
    assert sig.entry_price == 102.5
    assert sig.stop_loss < 102.5

def test_generate_signals_short_pullback(vp_config):
    strat = VWAPPullbackStrategy(vp_config)
    
    dates = [
        datetime(2026, 7, 2, 9, 15),
        datetime(2026, 7, 2, 9, 20),
        datetime(2026, 7, 2, 9, 25),
        datetime(2026, 7, 2, 9, 30),
        datetime(2026, 7, 2, 9, 35),
        datetime(2026, 7, 2, 9, 40), # Pullback bar (high touches VWAP)
        datetime(2026, 7, 2, 9, 45)  # Confirmation bar
    ]
    
    opens =   [100, 99,  98,  97,  96,  97.5, 99.5]
    highs =   [101, 100, 99,  98,  97,  100.1, 99.8] # High at index 5 (100.1) touches VWAP (~99.8)
    lows =    [99,  97,  96,  95,  95,  97.0, 97.0]
    closes =  [100, 98,  97,  96,  97,  99.5, 97.5] # Close at index 6 (97.5) is bearish close < open (99.5)
    volumes = [100, 100, 100, 100, 100, 100,   250]
    
    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    }, index=dates)
    
    signals = strat.generate_signals("RELIANCE", df)
    
    assert len(signals) == 1
    sig = signals[0]
    assert sig.symbol == "RELIANCE"
    assert sig.direction == Direction.SHORT
    assert sig.entry_price == 97.5
    assert sig.stop_loss > 97.5
