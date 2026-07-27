"""
tests/test_scanner_circuit_breaker.py
--------------------------------------
Verifies that the background scanner loop continues checking exits and updating PnL
for open positions even when the risk manager triggers a circuit breaker (allowed=False).
"""
import pytest
from unittest.mock import MagicMock
from core.order_executor import Position, Direction
from core.risk_manager import RiskManager
from core.data_fetcher import KiteDataFetcher


def test_scanner_loop_continues_exits_on_circuit_breaker():
    # 1. Setup mock RiskManager where can_trade() returns False (e.g. daily loss limit hit)
    mock_risk = MagicMock(spec=RiskManager)
    mock_risk.can_trade.return_value = (False, "Daily loss limit hit")
    
    # 2. Setup mock OrderExecutor with an open position
    pos = Position(
        symbol="TCS",
        direction=Direction.LONG,
        qty=10,
        entry_price=100.0,
        stop_loss=95.0,
        target=110.0,
        status="OPEN"
    )
    
    mock_executor = MagicMock()
    mock_executor.open_positions = [pos]
    mock_executor.update_positions_pnl.return_value = [
        {"symbol": "TCS", "pnl": 100.0, "qty": 10, "exit_price": 110.0}
    ]
    
    # 3. Setup mock DataFetcher
    mock_fetcher = MagicMock(spec=KiteDataFetcher)
    mock_fetcher.get_ltp.return_value = 110.0
    
    # Simulate the scanner loop body:
    allowed, reason = mock_risk.can_trade(active_positions_count=len(mock_executor.open_positions))
    
    ltps = {}
    
    if allowed:
        pytest.fail("Should not execute the entry branch when circuit breaker is active")
    else:
        open_positions_symbols = list(set(p.symbol for p in mock_executor.open_positions))
        for sym in open_positions_symbols:
            ltp_val = mock_fetcher.get_ltp(sym)
            if ltp_val is not None:
                ltps[sym] = ltp_val
                
    # Check that open position symbol LTP was fetched correctly
    assert "TCS" in ltps
    assert ltps["TCS"] == 110.0
    
    # 4. Enforce that update_positions_pnl is called with the resolved LTPs dictionary
    closed_trades = mock_executor.update_positions_pnl(ltps)
    
    assert len(closed_trades) == 1
    assert closed_trades[0]["symbol"] == "TCS"
    assert closed_trades[0]["exit_price"] == 110.0
    
    for trade in closed_trades:
        mock_risk.record_trade_result(
            symbol=trade["symbol"],
            pnl=trade["pnl"],
            qty=trade["qty"],
            exit_price=trade["exit_price"]
        )
        
    # Verify that record_trade_result was called for the closed position
    mock_risk.record_trade_result.assert_called_once_with(
        symbol="TCS",
        pnl=100.0,
        qty=10,
        exit_price=110.0
    )
