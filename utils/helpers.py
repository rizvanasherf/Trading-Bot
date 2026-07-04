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
