"""
tests/test_strategy.py
-----------------------
Unit tests for shared strategy models (Direction, Signal, FibLevels).
"""
import pytest
import pandas as pd
from core.strategy import Direction, FibLevels, Signal


def test_direction_enum():
    assert Direction.LONG.value == "LONG"
    assert Direction.SHORT.value == "SHORT"


def test_fib_levels_dataclass():
    fib = FibLevels(
        swing_high=200.0,
        swing_low=100.0,
        direction=Direction.LONG,
        levels={0.618: 138.2, 0.382: 161.8},
        extensions={1.272: 227.2}
    )
    assert fib.swing_high == 200.0
    assert fib.swing_low == 100.0
    assert fib.direction == Direction.LONG
    
    nearest = fib.nearest_level(140.0)
    assert nearest is not None
    assert nearest[0] == 0.618


def test_signal_dataclass():
    sig = Signal(
        symbol="RELIANCE",
        direction=Direction.LONG,
        entry_price=100.0,
        stop_loss=90.0,
        target=120.0,
        fib_level=0.618,
        swing_high=110.0,
        swing_low=95.0,
        timestamp=pd.Timestamp("2026-09-05 09:30:00")
    )
    assert sig.risk == 10.0
    assert sig.reward == 20.0
    assert sig.risk_reward == 2.0
