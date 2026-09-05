"""
core/strategy.py
----------------
Shared strategy data structures and models (Direction, Signal, FibLevels).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import pandas as pd


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class FibLevels:
    swing_high: float
    swing_low: float
    direction: Direction
    levels: Dict[float, float] = field(default_factory=dict)
    extensions: Dict[float, float] = field(default_factory=dict)

    def nearest_level(self, price: float) -> Optional[Tuple[float, float]]:
        """Return (ratio, price) of the nearest Fib level to *price*."""
        if not self.levels:
            return None
        nearest = min(self.levels.items(), key=lambda kv: abs(kv[1] - price))
        return nearest


@dataclass
class Signal:
    symbol: str
    direction: Direction
    entry_price: float
    stop_loss: float
    target: float
    fib_level: float          # e.g. 0.618
    swing_high: float
    swing_low: float
    timestamp: pd.Timestamp
    confidence: float = 0.0   # 0–1 score

    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward(self) -> float:
        return abs(self.target - self.entry_price)

    @property
    def risk_reward(self) -> float:
        return self.reward / self.risk if self.risk else 0.0
