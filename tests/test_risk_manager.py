"""
tests/test_risk_manager.py
--------------------------
Unit tests for the RiskManager.
Verifies position sizing, circuit breakers, and daily statistic updates.
"""
import pytest
from datetime import date, timedelta
from core.risk_manager import RiskManager, DailyStats
from utils.helpers import now_ist


@pytest.fixture
def risk_config():
    return {
        "risk": {
            "capital": 100000.0,            # 1 Lakh Capital
            "risk_per_trade": 0.01,         # 1% = ₹1000 risk per trade
            "max_daily_loss": 0.03,         # 3% = ₹3000 max daily loss
            "max_consecutive_losses": 3,
            "max_daily_trades": 5,
            "min_risk_reward": 2.0,
            "max_stock_concentration": 0.20  # 20% = ₹20000 max single stock exposure
        }
    }


def test_calculate_position_size(risk_config):
    rm = RiskManager(risk_config)
    
    # Capital: 100,000. Risk per trade: 1% = 1,000.
    # Entry: 100, SL: 95. Risk per share = 5.
    # Expected position size = 1,000 / 5 = 200 shares.
    # Total exposure = 200 * 100 = 20,000.
    # Max allowed exposure = 20% of 100,000 = 20,000.
    # Fits exactly.
    qty = rm.calculate_position_size("TCS", entry_price=100.0, stop_loss=95.0)
    assert qty == 200

    # Entry: 100, SL: 90. Risk per share = 10.
    # Qty by risk = 1000 / 10 = 100 shares.
    # Exposure = 100 * 100 = 10,000 (below 20,000).
    # Expected size = 100.
    qty = rm.calculate_position_size("TCS", entry_price=100.0, stop_loss=90.0)
    assert qty == 100

    # Test stock concentration cap
    # Entry: 100, SL: 99. Risk per share = 1.
    # Qty by risk = 1000 / 1 = 1000 shares.
    # Exposure = 1000 * 100 = 100,000.
    # Concentration limit is 20,000 exposure = 20,000 / 100 = 200 shares.
    # Expected size should be capped at 200 shares.
    qty = rm.calculate_position_size("TCS", entry_price=100.0, stop_loss=99.0)
    assert qty == 200


def test_can_trade_circuit_breakers(risk_config):
    rm = RiskManager(risk_config)
    
    # Initially OK
    allowed, reason = rm.can_trade()
    assert allowed is True
    assert reason == "OK"
    
    # 1. Daily trade limit
    rm.stats.trades = 5
    allowed, reason = rm.can_trade()
    assert allowed is False
    assert "Max daily trades" in reason
    
    # Reset trades
    rm.stats.trades = 2
    
    # 2. Consecutive losses limit (max_consecutive_losses = 3)
    rm.stats.consecutive_losses = 3
    allowed, reason = rm.can_trade()
    assert allowed is False
    assert "Consecutive loss circuit breaker" in reason
    
    rm.stats.consecutive_losses = 1
    
    # 3. Daily PnL loss limit (3% of 100,000 = ₹3000)
    rm.stats.gross_pnl = -3500.0
    allowed, reason = rm.can_trade()
    assert allowed is False
    assert "Daily loss limit hit" in reason


def test_record_trade_result(risk_config):
    rm = RiskManager(risk_config)
    
    # Add exposure
    rm.add_position_exposure("INFY", 10000.0)
    assert rm._position_exposure["INFY"] == 10000.0
    
    # Record a winner trade
    rm.record_trade_result("INFY", pnl=1500.0, qty=100, exit_price=115.0)
    
    # Stats checks
    assert rm.stats.trades == 1
    assert rm.stats.winners == 1
    assert rm.stats.losers == 0
    assert rm.stats.gross_pnl == 1500.0
    assert rm.stats.consecutive_losses == 0
    assert "INFY" not in rm._position_exposure  # Cleared exposure
    
    # Record a loser trade
    rm.add_position_exposure("TCS", 15000.0)
    rm.record_trade_result("TCS", pnl=-800.0, qty=150, exit_price=90.0)
    assert rm.stats.trades == 2
    assert rm.stats.winners == 1
    assert rm.stats.losers == 1
    assert rm.stats.gross_pnl == 700.0
    assert rm.stats.consecutive_losses == 1


def test_reset_daily_counters(risk_config):
    rm = RiskManager(risk_config)
    
    # Modify stats to simulate a previous day
    rm.stats.date = now_ist().date() - timedelta(days=1)
    rm.stats.trades = 3
    rm.stats.gross_pnl = 1200.0
    rm._position_exposure["TCS"] = 15000.0
    
    # Running resets because the date changed
    rm.reset_daily_counters()
    
    assert rm.stats.date == now_ist().date()
    assert rm.stats.trades == 0
    assert rm.stats.gross_pnl == 0.0
    assert len(rm._position_exposure) == 0
