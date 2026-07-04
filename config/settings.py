"""
config/settings.py
------------------
Loads environment variables using pydantic-settings.
Falls back to safe defaults so the app runs in mock/paper mode
even without a .env file.
"""
from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Angel One ─────────────────────────────────────────────────────────────
    ANGEL_API_KEY: Optional[str] = None
    ANGEL_CLIENT_ID: Optional[str] = None
    ANGEL_PIN: Optional[str] = None
    ANGEL_TOTP_SECRET: Optional[str] = None

    # ── Trading mode ──────────────────────────────────────────────────────────
    TRADING_MODE: Literal["paper", "live"] = "paper"

    @property
    def angel_configured(self) -> bool:
        """True when all four Angel One credentials are present."""
        return bool(self.ANGEL_API_KEY and self.ANGEL_CLIENT_ID and self.ANGEL_PIN and self.ANGEL_TOTP_SECRET)

    @property
    def is_live(self) -> bool:
        return self.TRADING_MODE == "live"



# Singleton — import this everywhere
settings = Settings()
