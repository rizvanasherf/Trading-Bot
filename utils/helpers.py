"""
utils/helpers.py
----------------
Timezone helpers, IST conversions, numeric formatting.
"""
from datetime import datetime, time
import pytz

IST = pytz.timezone("Asia/Kolkata")


def now_ist() -> datetime:
    """Current datetime in IST."""
    return datetime.now(IST)


def to_ist(dt: datetime) -> datetime:
    """Convert any aware/naive datetime to IST."""
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(IST)


def ist_time_str(fmt: str = "%H:%M:%S") -> str:
    return now_ist().strftime(fmt)


def is_market_open() -> bool:
    """Returns True between 09:15 and 15:30 IST on weekdays."""
    now = now_ist()
    if now.weekday() >= 5:          # Saturday / Sunday
        return False
    t = now.time()
    return time(9, 15) <= t <= time(15, 30)


def is_after_squareoff(squareoff: str = "15:15") -> bool:
    h, m = map(int, squareoff.split(":"))
    return now_ist().time() >= time(h, m)


def fmt_inr(value: float) -> str:
    """Format a number as Indian Rupees, e.g. ₹1,23,456.78"""
    try:
        negative = value < 0
        value = abs(value)
        s = f"{value:,.2f}"
        # Re-format with Indian grouping (last 3 then pairs)
        parts = s.split(".")
        integer = parts[0].replace(",", "")
        if len(integer) > 3:
            last3 = integer[-3:]
            rest = integer[:-3]
            rest_fmt = ""
            while len(rest) > 2:
                rest_fmt = "," + rest[-2:] + rest_fmt
                rest = rest[:-2]
            rest_fmt = rest + rest_fmt
            integer = rest_fmt + "," + last3
        formatted = f"₹{integer}.{parts[1]}"
        return f"-{formatted}" if negative else formatted
    except Exception:
        return str(value)


def fmt_pct(value: float, decimals: int = 2) -> str:
    return f"{value * 100:.{decimals}f}%"


def pnl_color(value: float) -> str:
    """Returns 'green' or 'red' string for Streamlit metric delta."""
    return "normal" if value >= 0 else "inverse"


class IdempotencyTracker:
    def __init__(self, filepath: str = "logs/placed_signals.json"):
        self.filepath = filepath
        import os
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        self.signals_keys = self._load()

    def _load(self) -> set:
        import os
        import json
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                    return set(data)
            except Exception:
                return set()
        return set()

    def _save(self) -> None:
        import json
        try:
            with open(self.filepath, "w") as f:
                json.dump(list(self.signals_keys), f)
        except Exception:
            pass

    def check_and_add(self, symbol: str, direction: str, date_str: str) -> bool:
        """Returns True if the signal is new and added, False if it was already processed today."""
        key = f"{symbol}_{direction}_{date_str}"
        if key in self.signals_keys:
            return False
        self.signals_keys.add(key)
        self._save()
        return True
