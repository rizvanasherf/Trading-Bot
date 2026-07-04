"""
utils/logger.py
---------------
Pre-configured loguru logger.
Dual output: colourised stdout + rotating file at logs/trading.log.
"""
import sys
from pathlib import Path
from loguru import logger

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

# Remove the default handler
logger.remove()

# ── Console ────────────────────────────────────────────────────────────────
logger.add(
    sys.stdout,
    level="INFO",
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> – {message}",
)

# ── Rotating file ───────────────────────────────────────────────────────────
logger.add(
    _LOG_DIR / "trading.log",
    level="DEBUG",
    rotation="10 MB",
    retention="14 days",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} – {message}",
    enqueue=True,         # thread-safe
)

__all__ = ["logger"]
