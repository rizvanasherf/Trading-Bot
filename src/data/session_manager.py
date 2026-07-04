"""
src/data/session_manager.py
---------------------------
AngelSessionManager: Handles full authentication lifecycle for Angel One SmartAPI,
including daily schedules, token management, and auto-reconnection on expiry (AB1010).
"""
import time
import pyotp
import schedule
import threading
from datetime import datetime
from typing import Optional
from SmartApi import SmartConnect
from config.settings import settings
from utils.logger import logger
from utils.helpers import now_ist

class AngelSessionManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AngelSessionManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.smart: Optional[SmartConnect] = None
        self.client_id: Optional[str] = None
        self.session_start_time: Optional[float] = None
        self.auth_token: Optional[str] = None
        self.feed_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self._conn_lock = threading.Lock()
        self._initialized = True
        
        self.connect()
        self._start_scheduler()

    def connect(self) -> bool:
        """Generate a session using credentials with auto-generated TOTP."""
        with self._conn_lock:
            if not settings.angel_configured:
                logger.warning("[Session Manager] Credentials not configured. Session skipped.")
                return False

            try:
                logger.info("[Session Manager] Initiating SmartAPI authentication...")
                self.smart = SmartConnect(api_key=settings.ANGEL_API_KEY)
                totp_val = pyotp.TOTP(settings.ANGEL_TOTP_SECRET).now()
                
                logger.info(f"[Session Manager] Log in Client ID: {settings.ANGEL_CLIENT_ID}")
                session_data = self.smart.generateSession(
                    clientCode=settings.ANGEL_CLIENT_ID,
                    password=settings.ANGEL_PIN,
                    totp=totp_val
                )
                
                if session_data.get("status") is True:
                    self.client_id = settings.ANGEL_CLIENT_ID
                    self.session_start_time = time.time()
                    
                    data = session_data.get("data", {})
                    self.auth_token = data.get("jwtToken")
                    self.feed_token = data.get("feedToken")
                    self.refresh_token = data.get("refreshToken")
                    
                    # Log session details
                    expiry_time = now_ist().replace(hour=23, minute=59, second=59, microsecond=0)
                    logger.success(
                        f"[Session Manager] Successfully logged into Angel One. "
                        f"Client: {self.client_id} | Token Expires at: {expiry_time.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    return True
                else:
                    logger.error(f"[Session Manager] generateSession failed: {session_data.get('message')}")
                    self._reset_session_fields()
                    return False
            except Exception as e:
                logger.error(f"[Session Manager] Exception during login connection: {e}")
                self._reset_session_fields()
                return False

    def is_connected(self) -> bool:
        """Check if session is currently active and valid."""
        if not self.smart or not self.auth_token:
            return False
            
        # Verify the session has not run past midnight (IST)
        if self.session_start_time:
            last_date = datetime.fromtimestamp(self.session_start_time).date()
            current_date = now_ist().date()
            if current_date > last_date:
                logger.warning("[Session Manager] Session expired (ran past midnight).")
                return False
                
        return True

    def verify_or_reconnect(self, error_code: str = "") -> None:
        """If error_code is AB1010 or session is invalid, trigger instant auto-reconnect."""
        if error_code == "AB1010" or not self.is_connected():
            logger.warning("[Session Manager] Session expired or invalid (AB1010). Auto-reconnecting immediately...")
            self.connect()

    def _reset_session_fields(self) -> None:
        self.smart = None
        self.client_id = None
        self.session_start_time = None
        self.auth_token = None
        self.feed_token = None
        self.refresh_token = None

    def _start_scheduler(self) -> None:
        """Schedule reconnect daily at 9:00 AM IST."""
        def run_sched():
            while True:
                schedule.run_pending()
                time.sleep(1)
                
        schedule.every().day.at("09:00").do(self.connect)
        t = threading.Thread(target=run_sched, daemon=True)
        t.start()

# Singleton instance
session_manager = AngelSessionManager()
