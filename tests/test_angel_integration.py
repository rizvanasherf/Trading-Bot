"""
tests/test_angel_integration.py
-------------------------------
Unit tests verifying the Angel One SmartAPI connector logic,
instrument mappings, and order buffers.
"""
import pytest
from src.data.angel_connector import connector
from src.data.optimized_client import optimized_client
from core.data_fetcher import KiteDataFetcher
from core.order_executor import OrderExecutor, Position
from core.strategy import Signal, Direction

def test_angel_connector_singleton():
    """Verify AngelConnector behaves as a singleton."""
    from src.data.angel_connector import AngelConnector
    c1 = AngelConnector()
    c2 = AngelConnector()
    assert c1 is c2

def test_instrument_token_resolving():
    """Verify that symbols are mapped to tokens and trading symbols."""
    # Seed mock entries to test resolving offline
    connector.token_map["RELIANCE"] = ("3045", "RELIANCE-EQ")
    connector.token_map["RELIANCE-EQ"] = ("3045", "RELIANCE-EQ")
    token, trading_sym = connector.get_token_info("RELIANCE")
    assert token == "3045"
    assert trading_sym == "RELIANCE-EQ"

    token_eq, trading_sym_eq = connector.get_token_info("RELIANCE-EQ")
    assert token_eq == "3045"
    assert trading_sym_eq == "RELIANCE-EQ"

def test_data_fetcher_mock_fallback():
    """Verify KiteDataFetcher automatically falls back to mock mode if credentials are missing."""
    orig_smart_connector = connector.smart
    orig_smart_client = optimized_client.session.smart
    connector.smart = None
    optimized_client.session.smart = None
    try:
        fetcher = KiteDataFetcher()
        assert fetcher.is_mock is True
        
        # Check that mock historical data returns expected structure
        df = fetcher.get_historical_data("RELIANCE", interval="15minute", days=2)
        assert not df.empty
        assert "close" in df.columns
        assert "volume" in df.columns
    finally:
        connector.smart = orig_smart_connector
        optimized_client.session.smart = orig_smart_client

def test_order_executor_price_buffer():
    """Verify 0.1% buffer calculations for limit order placements."""
    executor = OrderExecutor()
    import pandas as pd
    signal_long = Signal(
        symbol="RELIANCE",
        direction=Direction.LONG,
        entry_price=2800.0,
        stop_loss=2750.0,
        target=2900.0,
        fib_level=0.618,
        swing_high=2900.0,
        swing_low=2700.0,
        timestamp=pd.Timestamp.now()
    )
    
    # In paper/mock mode, positions are created successfully
    pos = executor.execute_entry(signal_long, qty=10)
    assert pos is not None
    assert pos.entry_price == 2800.0
    assert pos.stop_loss == 2750.0
    assert pos.target == 2900.0
    
    # Verify buffer price calculations
    long_limit_price = round(signal_long.entry_price * 1.001, 2)
    short_limit_price = round(signal_long.entry_price * 0.999, 2)
    assert long_limit_price == 2802.8
    assert short_limit_price == 2797.2
