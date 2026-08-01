"""
tests/test_trailing_sl.py
-------------------------
Unit tests verifying the Automated Trailing Stop Loss (TSL) logic for Long and Short trades.
"""
import pytest
from core.order_executor import OrderExecutor, Position
from core.strategy import Direction

@pytest.fixture
def mock_config():
    return {
        "risk": {
            "capital": 100000.0,
            "trailing_sl_enabled": True,
            "trailing_sl_trigger_pct": 0.01,   # Triggers once trade gains 1.0%
            "trailing_sl_distance_pct": 0.005  # Trails 0.5% behind highest/lowest price
        }
    }

def test_trailing_sl_long(mock_config):
    executor = OrderExecutor(config=mock_config)
    
    # Create long position entered at 100
    pos = Position(
        id="pos_long_1",
        symbol="SBIN",
        direction=Direction.LONG,
        qty=10,
        entry_price=100.0,
        stop_loss=95.0,
        target=110.0,
        status="OPEN"
    )
    executor._positions[pos.id] = pos
    
    # 1. Update with price below trigger threshold (LTP = 100.5, trigger = 101.0)
    executor.update_positions_pnl({"SBIN": 100.5})
    assert pos.stop_loss == 95.0  # Should not trail yet
    assert pos.high_watermark == 100.5
    
    # 2. Update with price above trigger threshold (LTP = 102.0, trigger hit!)
    # Trail SL: 102.0 * (1 - 0.005) = 101.49
    executor.update_positions_pnl({"SBIN": 102.0})
    assert pos.high_watermark == 102.0
    assert pos.stop_loss == 101.49  # Trailed SL up
    
    # 3. Drop the price (LTP = 101.8). The stop loss must NOT trail downwards
    executor.update_positions_pnl({"SBIN": 101.8})
    assert pos.high_watermark == 102.0  # High watermark remains at peak
    assert pos.stop_loss == 101.49      # Stop loss remains at trailed peak
    
    # 4. Push price to a new high (LTP = 104.0)
    # Trail SL: 104.0 * (1 - 0.005) = 103.48
    executor.update_positions_pnl({"SBIN": 104.0})
    assert pos.high_watermark == 104.0
    assert pos.stop_loss == 103.48

def test_trailing_sl_short(mock_config):
    executor = OrderExecutor(config=mock_config)
    
    # Create short position entered at 100
    pos = Position(
        id="pos_short_1",
        symbol="SBIN",
        direction=Direction.SHORT,
        qty=10,
        entry_price=100.0,
        stop_loss=105.0,
        target=90.0,
        status="OPEN"
    )
    executor._positions[pos.id] = pos
    
    # 1. Update with price above trigger threshold (LTP = 99.5, trigger = 99.0)
    executor.update_positions_pnl({"SBIN": 99.5})
    assert pos.stop_loss == 105.0  # Should not trail yet
    assert pos.low_watermark == 99.5
    
    # 2. Update with price below trigger threshold (LTP = 98.0, trigger hit!)
    # Trail SL: 98.0 * (1 + 0.005) = 98.49
    executor.update_positions_pnl({"SBIN": 98.0})
    assert pos.low_watermark == 98.0
    assert pos.stop_loss == 98.49  # Trailed SL down
    
    # 3. Raise the price (LTP = 98.2). The stop loss must NOT trail upwards
    executor.update_positions_pnl({"SBIN": 98.2})
    assert pos.low_watermark == 98.0  # Low watermark remains at lowest peak
    assert pos.stop_loss == 98.49      # Stop loss remains at trailed peak
    
    # 4. Push price to a new low (LTP = 95.0)
    # Trail SL: 95.0 * 1.005 = 95.475
    executor.update_positions_pnl({"SBIN": 95.0})
    assert pos.low_watermark == 95.0
    assert pos.stop_loss in (95.47, 95.48)
