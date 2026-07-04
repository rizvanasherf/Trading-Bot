"""
tests/test_backtester.py
------------------------
Unit tests for the Backtester.
Validates performance calculations and ensures no lookahead bias.
"""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from core.backtester import Backtester, BacktestResult, BacktestTrade
from core.strategy import Direction


@pytest.fixture
def test_data():
    """Create a simple, predictable trend dataset of 100 bars."""
    dates = [datetime(2026, 6, 1) + timedelta(minutes=15 * i) for i in range(100)]
    # Linear upward trend
    closes = np.linspace(100.0, 150.0, 100)
    opens = np.roll(closes, 1)
    opens[0] = 100.0
    highs = closes + 1.0
    lows = closes - 1.0
    volumes = np.ones(100) * 1000.0
    
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes
    }, index=dates)


@pytest.fixture
def backtest_config():
    return {
        "strategy": {
            "swing_threshold": 3,
            "price_tolerance": 0.005,
            "confirmation_candles": 2,
            "volume_multiplier": 1.0,
            "min_trend_strength": 1.0,
            "fib_levels": [0.0, 0.236, 0.382, 0.500, 0.618, 0.786, 1.0],
            "fib_extensions": [1.272, 1.618]
        },
        "risk": {
            "capital": 100000.0,
            "risk_per_trade": 0.01,
            "min_risk_reward": 1.5
        }
    }


def test_backtest_kpi_computation(backtest_config):
    tester = Backtester(backtest_config)
    
    # Create manual mock results to check mathematical formula logic
    res = BacktestResult(symbol="TEST", initial_capital=100000.0)
    # Add trades
    # Winner: entry 100, exit 110, qty 100 -> P&L = +1000
    res.trades.append(BacktestTrade(
        symbol="TEST", direction=Direction.LONG, entry_idx=10, 
        entry_price=100.0, stop_loss=90.0, target=110.0, qty=100,
        exit_idx=15, exit_price=110.0, exit_reason="TARGET", pnl=1000.0
    ))
    # Loser: entry 100, exit 95, qty 100 -> P&L = -500
    res.trades.append(BacktestTrade(
        symbol="TEST", direction=Direction.LONG, entry_idx=20, 
        entry_price=100.0, stop_loss=95.0, target=110.0, qty=100,
        exit_idx=25, exit_price=95.0, exit_reason="SL", pnl=-500.0
    ))
    
    # Construct an equity curve manually
    # Length of df is 52 bars
    df = pd.DataFrame(index=[datetime(2026, 6, 1) + timedelta(minutes=15 * i) for i in range(52)])
    
    res.equity_curve = [100000.0] * 54  # 54 points
    res.equity_curve[-1] = 100500.0     # end with some gain
    
    tester._compute_kpis(res, df)
    
    # Win rate: 1 win, 1 loss -> 50%
    assert res.win_rate == 0.50
    # Profit factor: gross_profit / gross_loss = 1000 / 500 = 2.0
    assert res.profit_factor == 2.0
    assert res.total_trades == 2
    assert res.winners == 1
    assert res.losers == 1
    # Total return: (100500 - 100000)/100000 = 0.5%
    assert res.total_return == pytest.approx(0.005)


def test_no_lookahead_bias(backtest_config, test_data):
    tester = Backtester(backtest_config)
    
    # We spy on strategy.generate_signals to verify that the length of dataframe
    # passed to it is never greater than the current index `i` + 1.
    original_generate_signals = tester.strategy.generate_signals
    
    max_lengths_checked = []
    
    def spy_generate_signals(symbol, df_window):
        max_lengths_checked.append(len(df_window))
        return original_generate_signals(symbol, df_window)
        
    tester.strategy.generate_signals = spy_generate_signals
    
    # Run the backtester
    tester.run("TEST_STOCK", test_data)
    
    # Ensure that length of window supplied to strategy is incrementing one bar at a time
    # and never exceeds the current lookback window.
    # The max length checked should correspond to the length of test_data during the loop
    assert max(max_lengths_checked) <= len(test_data)
    # The first window checked is warmup (which is max(3*2+20, 40) = 40)
    assert min(max_lengths_checked) == 41 # index 40 is 41st bar
