"""
tests/test_data_fetcher_yfinance.py
-----------------------------------
Unit tests for the yFinance historical data fetcher integration.
"""
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from core.data_fetcher import KiteDataFetcher

@pytest.fixture
def data_fetcher():
    return KiteDataFetcher()

def test_to_yfinance_symbol_translation(data_fetcher):
    # We patch the actual yf.download to verify what symbol is resolved
    with patch("yfinance.download") as mock_download:
        mock_df = pd.DataFrame({
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.0],
            "Volume": [1000]
        }, index=[pd.Timestamp("2026-07-14 09:15:00")])
        mock_download.return_value = mock_df
        
        # Test Nifty Spot translation
        data_fetcher.get_historical_data_yfinance("NIFTY", interval="5minute", days=1)
        mock_download.assert_called_with(tickers="^NSEI", period="1d", interval="5m", progress=False)
        
        # Test Stock translation
        data_fetcher.get_historical_data_yfinance("RELIANCE", interval="15minute", days=5)
        mock_download.assert_called_with(tickers="RELIANCE.NS", period="5d", interval="15m", progress=False)

def test_yfinance_dataframe_cleaning(data_fetcher):
    with patch("yfinance.download") as mock_download:
        # Create a sample raw yfinance dataframe
        raw_df = pd.DataFrame({
            "Open": [10.0, 11.0],
            "High": [12.0, 13.0],
            "Low": [9.0, 8.0],
            "Close": [11.0, 12.0],
            "Volume": [1000, 2000]
        }, index=[pd.Timestamp("2026-07-14 09:15:00"), pd.Timestamp("2026-07-14 09:20:00")])
        mock_download.return_value = raw_df
        
        df_clean = data_fetcher.get_historical_data_yfinance("TCS", interval="5minute", days=10)
        
        assert not df_clean.empty
        # Columns must be lowercased
        assert "open" in df_clean.columns
        assert "close" in df_clean.columns
        assert "Open" not in df_clean.columns
        # Timezone must be localized to Asia/Kolkata (IST)
        assert df_clean.index.tz is not None
        assert str(df_clean.index.tz) == "Asia/Kolkata"
