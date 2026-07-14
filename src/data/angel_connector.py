"""
src/data/angel_connector.py
---------------------------
Angel One SmartAPI Connector. Handles session management, auto-login,
TOTP generation, and instrument token mapping/caching.
"""
import os
import time
import json
import requests
import pyotp
import schedule
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple
from SmartApi import SmartConnect
from config.settings import settings
from utils.logger import logger
from utils.helpers import now_ist

class AngelConnector:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AngelConnector, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.smart = None
        self.token_map: Dict[str, Tuple[str, str]] = {}  # symbol -> (token, tradingsymbol)
        self._initialized = True
        self.connect()
        self._start_scheduler()

    def connect(self) -> bool:
        """Authenticate and establish session with Angel One SmartAPI."""
        if not settings.angel_configured:
            logger.warning("Angel One credentials incomplete. SmartAPI connection skipped.")
            return False
            
        try:
            logger.info("Initializing Angel One SmartConnect...")
            self.smart = SmartConnect(api_key=settings.ANGEL_API_KEY)
            
            # Generate TOTP
            totp_val = pyotp.TOTP(settings.ANGEL_TOTP_SECRET).now()
            
            logger.info(f"Generating session for Client ID: {settings.ANGEL_CLIENT_ID}...")
            session_data = self.smart.generateSession(
                clientCode=settings.ANGEL_CLIENT_ID,
                password=settings.ANGEL_PIN,
                totp=totp_val
            )
            
            if session_data.get("status") is True:
                logger.success("Angel One SmartAPI Session generated successfully.")
                # Load/Verify instrument token list
                self.load_instruments()
                return True
            else:
                logger.error(f"Failed to generate session: {session_data.get('message')}")
                self.smart = None
                return False
        except Exception as e:
            logger.error(f"Exception during Angel One session generation: {e}")
            self.smart = None
            return False

    def load_instruments(self, force: bool = False) -> None:
        """Fetch all instruments from Angel One margin JSON and cache symbol -> token mapping."""
        cache_path = Path("logs/angel_instruments.json")
        cache_path.parent.mkdir(exist_ok=True, parents=True)
        
        # Check if cache is fresh (less than 24 hours old)
        if not force and cache_path.exists():
            mtime = cache_path.stat().st_mtime
            if time.time() - mtime < 86400:  # 24 hours
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        self.token_map = json.load(f)
                    logger.info(f"Loaded {len(self.token_map)} instrument mappings from local cache.")
                    return
                except Exception as e:
                    logger.warning(f"Error reading instruments cache: {e}. Refetching...")

        try:
            logger.info("Fetching instrument list from Angel One calculator CDN...")
            url = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
            res = requests.get(url, timeout=15)
            if res.status_code == 200:
                data = res.json()
                temp_map = {}
                
                # Hardcoded fallback for Nifty 50 spot index
                temp_map["NIFTY"] = ("99926009", "Nifty 50")
                temp_map["NIFTY 50"] = ("99926009", "Nifty 50")
                
                for item in data:
                    exch_seg = item.get("exch_seg")
                    inst_type = item.get("instrumenttype")
                    symbol_name = item.get("name", "")
                    trading_sym = item.get("symbol", "")
                    token = item.get("token", "")
                    
                    if not token:
                        continue
                    
                    # Filter for NSE segment equities
                    if exch_seg == "NSE" and inst_type == "":
                        if symbol_name:
                            temp_map[symbol_name.upper()] = (token, trading_sym)
                            temp_map[trading_sym.upper()] = (token, trading_sym)
                            
                    # Nifty 50 Spot Index mapping
                    elif exch_seg == "NSE" and (trading_sym == "Nifty 50" or symbol_name == "Nifty 50" or symbol_name == "Nifty Index"):
                        temp_map["NIFTY"] = (token, trading_sym)
                        temp_map["NIFTY 50"] = (token, trading_sym)
                        
                    # Nifty Options mapping (OPTIDX)
                    elif exch_seg == "NFO" and symbol_name == "NIFTY" and inst_type == "OPTIDX":
                        if trading_sym:
                            temp_map[trading_sym.upper()] = (token, trading_sym)
                
                self.token_map = temp_map
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(self.token_map, f)
                logger.success(f"Cached {len(self.token_map)} instrument mappings.")
            else:
                logger.error(f"Failed to fetch instruments: Status code {res.status_code}")
        except Exception as e:
            logger.error(f"Error building instrument token map: {e}")

    def get_token_info(self, symbol: str) -> Tuple[Optional[str], Optional[str]]:
        """Resolve a symbol (e.g. 'RELIANCE') to (token, trading_symbol)."""
        if not self.token_map:
            self.load_instruments()
            
        clean_symbol = symbol.strip().upper()
        if clean_symbol in self.token_map:
            return self.token_map[clean_symbol]
            
        if clean_symbol.endswith("-EQ"):
            base = clean_symbol[:-3]
            if base in self.token_map:
                return self.token_map[base]
            
        eq_symbol = f"{clean_symbol}-EQ"
        if eq_symbol in self.token_map:
            return self.token_map[eq_symbol]
            
        return None, None

    def get_exchange(self, symbol: str) -> str:
        """Get the exchange segment for a symbol (NSE or NFO)."""
        symbol_upper = symbol.strip().upper()
        if ("CE" in symbol_upper or "PE" in symbol_upper) and "NIFTY" in symbol_upper:
            return "NFO"
        return "NSE"

    def resolve_atm_option(self, symbol: str, strike: int, opt_type: str) -> Optional[Tuple[str, str]]:
        """
        Find the nearest active expiry option contract for Nifty 50 from the cache.
        Returns (token, trading_symbol).
        """
        import datetime
        clean_symbol = symbol.strip().upper()
        if clean_symbol != "NIFTY" and clean_symbol != "NIFTY 50":
            return None
            
        opt_suffix = f"{strike}{opt_type.upper()}"
        matches = []
        
        # Search token map for matches
        for key, val in self.token_map.items():
            token, trading_sym = val
            trading_sym_upper = trading_sym.upper()
            if trading_sym_upper.startswith("NIFTY") and trading_sym_upper.endswith(opt_suffix):
                # Try to parse the expiry from NIFTYddMMMyySTRIKECE (e.g. NIFTY06DEC2325350CE -> expiry "06DEC23")
                try:
                    expiry_str = trading_sym_upper[5:12] # characters 5 to 12
                    exp_date = datetime.datetime.strptime(expiry_str, "%d%b%y").date()
                    
                    if exp_date >= datetime.date.today():
                        matches.append((token, trading_sym, exp_date))
                except Exception:
                    continue
                    
        if not matches:
            # Fallback to key exact match search if strict date parsing failed
            for key, val in self.token_map.items():
                token, trading_sym = val
                if trading_sym.upper().startswith("NIFTY") and trading_sym.upper().endswith(opt_suffix):
                    matches.append((token, trading_sym, datetime.date.max))
                    
        if not matches:
            return None
            
        # Sort matches by expiry date ascending and return the closest one
        matches.sort(key=lambda x: x[2])
        return matches[0][0], matches[0][1]

    def _start_scheduler(self):
        """Start background daemon thread to run scheduled reconnect daily at 9:00 AM IST."""
        def run_sched():
            while True:
                schedule.run_pending()
                time.sleep(1)
                
        schedule.every().day.at("09:00").do(self.connect)
        t = threading.Thread(target=run_sched, daemon=True)
        t.start()

# Singleton connector instance
connector = AngelConnector()
