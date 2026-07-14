"""
src/data/quote_fetcher.py
-------------------------
BatchQuoteFetcher: Fetches market quote information (LTP, OHLC) for multiple symbols
in a single batch call using SmartAPI marketData endpoint, caching results to minimize API requests.
"""
from typing import Dict, List, Optional
from utils.logger import logger
from src.utils.rate_limiter import broker_limiters
from src.utils.cache import MarketDataCache
from src.data.angel_connector import connector

class BatchQuoteFetcher:
    def __init__(self, cache: MarketDataCache):
        self.cache = cache
        self.limiter = broker_limiters.get("quotes")
        self.total_saved_calls = 0
        self.total_api_calls = 0

    def get_quotes(self, symbols: List[str]) -> Dict[str, dict]:
        """
        Fetch quotes (LTP + OHLC) for all specified symbols in a batch call.
        Uses cached values if fresh; only queries the API for expired symbols.
        """
        results = {}
        missing_symbols = []
        tokens_to_fetch = []

        # 1. Resolve which symbols can be retrieved from cache
        for symbol in symbols:
            cache_key = f"quote_{symbol.upper()}"
            cached = self.cache.get(cache_key)
            if cached is not None:
                results[symbol] = cached
            else:
                missing_symbols.append(symbol)
                token, trading_sym = connector.get_token_info(symbol)
                if token:
                    tokens_to_fetch.append(token)
                else:
                    logger.warning(f"[Quote Fetcher] Cannot resolve token for {symbol}")

        if not missing_symbols:
            return results

        # 2. Make the batch API call for missing symbols
        if connector.smart is not None and missing_symbols:
            exchange_tokens = {}
            for sym in missing_symbols:
                token, _ = connector.get_token_info(sym)
                if token:
                    exch = connector.get_exchange(sym)
                    if exch not in exchange_tokens:
                        exchange_tokens[exch] = []
                    exchange_tokens[exch].append(token)

            if exchange_tokens:
                self.limiter.acquire("Batch Quote API Call")
                self.total_api_calls += 1
                
                # Naive approach would make len(missing_symbols) calls
                saved = len(missing_symbols) - 1
                self.total_saved_calls += saved
                logger.info(f"[Quote Fetcher] Batch fetching {len(missing_symbols)} quotes across {list(exchange_tokens.keys())}. Saved {saved} calls vs naive approach.")

                try:
                    res = connector.smart.getMarketData("FULL", exchange_tokens)
                
                    if res.get("status") is True and res.get("data") and "fetched" in res["data"]:
                        fetched_list = res["data"]["fetched"]
                        
                        # Create lookup mappings
                        token_to_symbol = {}
                        for sym in missing_symbols:
                            tok, _ = connector.get_token_info(sym)
                            if tok:
                                token_to_symbol[tok] = sym

                        for item in fetched_list:
                            token = item.get("symbolToken")
                            symbol_name = token_to_symbol.get(token)
                            if not symbol_name:
                                continue

                            # Map Angel response to expected format
                            ltp = float(item.get("ltp", 0.0))
                            quote_data = {
                                "last_price": ltp,
                                "ohlc": {
                                    "open": float(item.get("open", ltp)),
                                    "high": float(item.get("high", ltp)),
                                    "low": float(item.get("low", ltp)),
                                    "close": float(item.get("close", ltp))
                                },
                                "volume": int(item.get("volume", 0)),
                                "average_price": float(item.get("avgPrice", ltp))
                            }
                            
                            # Cache the result (5s TTL)
                            cache_key = f"quote_{symbol_name.upper()}"
                            self.cache.set(cache_key, quote_data, MarketDataCache.TTL_QUOTE)
                            results[symbol_name] = quote_data

                    else:
                        logger.warning(f"[Quote Fetcher] Batch API call failed: {res.get('message')}. Falling back to individual calls.")
                        self._fallback_individual(missing_symbols, results)
                except Exception as e:
                    logger.error(f"[Quote Fetcher] Exception during batch quote fetch: {e}. Falling back to individual calls.")
                    self._fallback_individual(missing_symbols, results)
        else:
            # Fallback to mock mode/individual if connector is offline
            self._fallback_individual(missing_symbols, results)

        return results

    def get_ltp(self, symbol: str) -> float:
        """Fetch a single LTP from the batch quote cache. Falls back if missing."""
        quotes = self.get_quotes([symbol])
        if symbol in quotes:
            return quotes[symbol]["last_price"]
        
        # Absolute fallback base price
        from core.data_fetcher import MOCK_BASE_PRICES
        import random
        base = MOCK_BASE_PRICES.get(symbol.upper(), 1000.0)
        return round(base * random.uniform(0.995, 1.005), 2)

    def _fallback_individual(self, symbols: List[str], results: Dict[str, dict]) -> None:
        """Fallback to request quote one-by-one with rate limits."""
        for symbol in symbols:
            token, trading_sym = connector.get_token_info(symbol)
            if not token:
                continue

            self.limiter.acquire("Fallback Quote Call")
            self.total_api_calls += 1
            try:
                res = connector.smart.ltpData(exchange="NSE", tradingsymbol=trading_sym, symboltoken=token)
                if res.get("status") is True and "data" in res:
                    data = res["data"]
                    ltp = float(data["ltp"])
                    quote_data = {
                        "last_price": ltp,
                        "ohlc": {
                            "open": float(data.get("open", ltp)),
                            "high": float(data.get("high", ltp)),
                            "low": float(data.get("low", ltp)),
                            "close": float(data.get("close", ltp))
                        },
                        "volume": 0,
                        "average_price": ltp
                    }
                    
                    cache_key = f"quote_{symbol.upper()}"
                    self.cache.set(cache_key, quote_data, MarketDataCache.TTL_QUOTE)
                    results[symbol] = quote_data
            except Exception as e:
                logger.error(f"[Quote Fetcher] Fallback failed for {symbol}: {e}")
