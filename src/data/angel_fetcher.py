"""
src/data/angel_fetcher.py
-------------------------
AngelHistoricalFetcher: Smart historical data retriever wrapping Angel One SmartAPI.
Features auto-chunking, L1/L2 caching, rate limiting, and bulk concurrent fetches.
"""
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple
import pandas as pd
from utils.logger import logger
from utils.helpers import now_ist
from src.utils.rate_limiter import broker_limiters
from src.utils.cache import MarketDataCache
from src.data.angel_connector import connector

class AngelHistoricalFetcher:
    INTERVAL_LIMITS = {
        "ONE_MINUTE": 30,
        "THREE_MINUTE": 60,
        "FIVE_MINUTE": 100,
        "TEN_MINUTE": 100,  # Map 10 min to same as 5 min for safety
        "FIFTEEN_MINUTE": 200,
        "THIRTY_MINUTE": 200,
        "ONE_HOUR": 400,
        "ONE_DAY": 2000
    }

    def __init__(self, cache: MarketDataCache):
        self.cache = cache
        self.limiter = broker_limiters.get("historical")

    def get_token(self, symbol: str) -> Optional[str]:
        """Expose get_token method using connector singleton."""
        token, _ = connector.get_token_info(symbol)
        return token

    def fetch_historical(
        self,
        symbol: str,
        interval: str,
        days: int,
        is_live: bool = False
    ) -> pd.DataFrame:
        """
        Fetch historical candles checking L1 -> L2 -> API with rate limits and auto-chunking.
        Returns a clean pd.DataFrame indexed by DatetimeIndex in IST timezone.
        """
        cache_key = f"hist_{symbol}_{interval}_{days}"
        
        # Check cache
        cached_df = self.cache.get_df(cache_key)
        if cached_df is not None:
            return cached_df

        # Resolve symbol token
        token, trading_symbol = connector.get_token_info(symbol)
        if not token:
            logger.warning(f"[Historical Fetcher] Symbol {symbol} token could not be resolved.")
            return pd.DataFrame()

        # Calculate time boundaries
        end_dt = now_ist()
        if is_live:
            # Handle the 5-second latest candle delay by subtracting 10 seconds
            end_dt = end_dt - timedelta(seconds=10)
        start_dt = end_dt - timedelta(days=days)

        # Mappings
        timeframe_map = {
            "minute": "ONE_MINUTE",
            "3minute": "THREE_MINUTE",
            "5minute": "FIVE_MINUTE",
            "10minute": "TEN_MINUTE",
            "15minute": "FIFTEEN_MINUTE",
            "30minute": "THIRTY_MINUTE",
            "60minute": "ONE_HOUR",
            "day": "ONE_DAY",
        }
        angel_interval = timeframe_map.get(interval, interval)
        if angel_interval not in self.INTERVAL_LIMITS:
            angel_interval = "FIFTEEN_MINUTE"

        # Chunk calculations
        chunk_days = self.INTERVAL_LIMITS[angel_interval]
        chunks = self._generate_chunks(start_dt, end_dt, chunk_days)

        all_dfs = []
        for i, (from_dt, to_dt) in enumerate(chunks):
            # Apply Token Bucket Rate Limiter
            self.limiter.acquire("Historical Candle API Call")

            # Sleep between calls to respect rate limit of 3 req/sec
            if i > 0:
                time.sleep(0.35)

            params = {
                "exchange": connector.get_exchange(symbol),
                "symboltoken": token,
                "interval": angel_interval,
                "fromdate": from_dt.strftime("%Y-%m-%d %H:%M"),
                "todate": to_dt.strftime("%Y-%m-%d %H:%M")
            }

            try:
                if connector.smart is None:
                    raise ConnectionError("SmartConnect instance not logged in.")

                logger.info(f"[{symbol}] Fetching candle chunk {i+1}/{len(chunks)} from {params['fromdate']} to {params['todate']}")
                res = connector.smart.getCandleData(params)

                if res.get("status") is True and res.get("data"):
                    candles = res["data"]
                    df_chunk = pd.DataFrame(candles, columns=["date", "open", "high", "low", "close", "volume"])
                    all_dfs.append(df_chunk)
                else:
                    logger.warning(f"[{symbol}] API chunk fetch failed: {res.get('message')}")
            except Exception as e:
                logger.error(f"[{symbol}] Exception during API chunk fetch: {e}")

        if not all_dfs:
            self.cache.set_df(cache_key, pd.DataFrame(), 15)
            return pd.DataFrame()

        # Concatenate and clean chunks
        df = pd.concat(all_dfs, ignore_index=True)
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates(subset=["date"])
        df = df.set_index("date").sort_index()

        # Make sure timezone is Asia/Kolkata
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
        else:
            df.index = df.index.tz_convert("Asia/Kolkata")

        # Cast to float
        df = df[["open", "high", "low", "close", "volume"]].astype(float)

        # Store in cache (default TTL 900 seconds)
        self.cache.set_df(cache_key, df, MarketDataCache.TTL_HISTORICAL)
        return df

    def fetch_bulk(
        self,
        symbols: List[str],
        interval: str,
        days: int,
        is_live: bool = False
    ) -> Dict[str, pd.DataFrame]:
        """Fetch historical data for multiple symbols concurrently using max_workers=3."""
        results = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_symbol = {
                executor.submit(self.fetch_historical, symbol, interval, days, is_live): symbol
                for symbol in symbols
            }
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    df = future.result()
                    results[symbol] = df
                except Exception as exc:
                    logger.error(f"[{symbol}] Bulk historical fetch raised exception: {exc}")
                    results[symbol] = pd.DataFrame()
        return results

    def _generate_chunks(self, start_dt: datetime, end_dt: datetime, max_days: int) -> List[Tuple[datetime, datetime]]:
        """Split a start/end date range into tuples of smaller date ranges based on max_days."""
        chunks = []
        current_end = end_dt
        while current_end > start_dt:
            current_start = max(start_dt, current_end - timedelta(days=max_days))
            chunks.insert(0, (current_start, current_end))
            current_end = current_start - timedelta(minutes=1)  # overlap prevention
        return chunks
