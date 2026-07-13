"""
tests/test_orb_strategy.py
--------------------------
Unit tests for the ORBStrategy class.
"""
import pytest
import pandas as pd
from datetime import datetime, time
from core.orb_strategy import ORBStrategy
from core.strategy import Direction, Signal

@pytest.fixture
def orb_config():
    return {
        "strategy": {
            "timeframe": "5minute"
        },
        "orb": {
            "start_time": "09:15",
            "end_time": "09:30",
            "volume_period": 5,
            "volume_multiplier": 1.2,
            "use_vwap_filter": False,
            "target_multiplier": 1.5,
            "max_range_pct": 0.10,
            "min_range_pct": 0.001
        }
    }

def test_calculate_opening_range(orb_config):
    strat = ORBStrategy(orb_config)
    
    # Create mock candles for one day
    dates = [
        datetime(2026, 7, 2, 9, 15),
        datetime(2026, 7, 2, 9, 20),
        datetime(2026, 7, 2, 9, 25),
        datetime(2026, 7, 2, 9, 30)
    ]
    highs = [100.0, 102.5, 99.0, 105.0]
    lows = [98.0, 97.0, 97.5, 96.0]
    closes = [99.0, 98.0, 98.5, 104.0]
    
    df = pd.DataFrame({
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [100] * 4
    }, index=dates)
    
    orh, orl = strat.calculate_opening_range(df)
    
    # 09:15, 09:20, and 09:25 candles are part of the opening range (before 09:30)
    # Highs: 100.0, 102.5, 99.0 -> Max = 102.5
    # Lows: 98.0, 97.0, 97.5 -> Min = 97.0
    assert orh == 102.5
    assert orl == 97.0

def test_generate_signals_long_breakout(orb_config):
    strat = ORBStrategy(orb_config)
    
    # 09:15 to 09:25: Range is 97.0 to 102.5
    # 09:30: Closes at 104.0 (breakout!)
    dates = [
        datetime(2026, 7, 2, 9, 0), # Warmup bar
        datetime(2026, 7, 2, 9, 5), # Warmup bar
        datetime(2026, 7, 2, 9, 10), # Warmup bar
        datetime(2026, 7, 2, 9, 15), # ORB Bar 1
        datetime(2026, 7, 2, 9, 20), # ORB Bar 2
        datetime(2026, 7, 2, 9, 25), # ORB Bar 3
        datetime(2026, 7, 2, 9, 30)  # Breakout Bar!
    ]
    
    # Volume average of first 6 bars: 100. Breakout bar volume: 200 (exceeds avg * 1.2)
    volumes = [100, 100, 100, 100, 100, 100, 200]
    highs =   [95, 96, 97, 100.0, 102.5, 99.0, 105.0]
    lows =    [93, 94, 95, 98.0, 97.0, 97.5, 98.5]
    closes =  [94, 95, 96, 99.0, 98.0, 98.5, 104.0] # closes above 102.5
    opens =   [93, 94, 95, 98.0, 99.0, 98.0, 99.0]
    
    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    }, index=dates)
    
    strat._calculate_rsi_15m = lambda df: 60.0
    signals = strat.generate_signals("RELIANCE", df)
    
    assert len(signals) == 1
    sig = signals[0]
    assert sig.symbol == "RELIANCE"
    assert sig.direction == Direction.LONG
    assert sig.entry_price == 104.0
    assert sig.stop_loss == 97.0 # ORL is 97.0
    assert sig.target == 104.0 + (102.5 - 97.0) * 1.5 # entry + range * 1.5

def test_generate_signals_short_breakout(orb_config):
    strat = ORBStrategy(orb_config)
    
    dates = [
        datetime(2026, 7, 2, 9, 0),
        datetime(2026, 7, 2, 9, 5),
        datetime(2026, 7, 2, 9, 10),
        datetime(2026, 7, 2, 9, 15), # ORB Bar 1
        datetime(2026, 7, 2, 9, 20), # ORB Bar 2
        datetime(2026, 7, 2, 9, 25), # ORB Bar 3
        datetime(2026, 7, 2, 9, 30)  # Breakout Bar!
    ]
    
    volumes = [100, 100, 100, 100, 100, 100, 200]
    highs =   [105, 106, 105, 102.5, 101.0, 102.0, 100.0]
    lows =    [103, 104, 103, 97.0, 98.0, 97.5, 95.0]
    closes =  [104, 105, 104, 98.0, 99.0, 98.5, 96.0] # closes below ORL (97.0)
    opens =   [103, 104, 103, 101.0, 98.0, 99.0, 98.0]
    
    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    }, index=dates)
    
    strat._calculate_rsi_15m = lambda df: 35.0
    signals = strat.generate_signals("RELIANCE", df)
    
    assert len(signals) == 1
    sig = signals[0]
    assert sig.direction == Direction.SHORT
    assert sig.entry_price == 96.0
    assert sig.stop_loss == 102.5 # ORH is 102.5
    assert sig.target == 96.0 - (102.5 - 97.0) * 1.5
