"""
core/strategy.py
----------------
FibonacciStrategy: detects swing highs/lows, computes Fib levels,
confirms entries, and emits Signal objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from utils.logger import logger


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


# ══════════════════════════════════════════════════════════════════════════════

class FibonacciStrategy:
    RETRACEMENT_RATIOS = [0.0, 0.236, 0.382, 0.500, 0.618, 0.786, 1.0]
    EXTENSION_RATIOS = [1.272, 1.618]

    def __init__(self, config: dict):
        strat = config.get("strategy", {})
        risk = config.get("risk", {})

        self.swing_threshold: int = strat.get("swing_threshold", 5)
        self.price_tolerance: float = strat.get("price_tolerance", 0.003)
        self.confirmation_candles: int = strat.get("confirmation_candles", 2)
        self.volume_multiplier: float = strat.get("volume_multiplier", 1.5)
        self.min_trend_strength: float = strat.get("min_trend_strength", 2.0)
        
        # New configurations
        self.use_vwap: bool = strat.get("use_vwap", True)
        self.vwap_filter: bool = strat.get("vwap_filter", True)
        self.fib_zone: float = strat.get("fib_zone", 0.002)
        self.confirmation_type: str = strat.get("confirmation_type", "reversal_candle")
        self.volume_period: int = strat.get("volume_period", 20)

        # Filter levels to pullback levels: 38.2%, 50%, 61.8%
        raw_levels = strat.get("fib_levels", self.RETRACEMENT_RATIOS)
        self.fib_levels_cfg = [lvl for lvl in raw_levels if lvl in (0.382, 0.500, 0.618)]
        if not self.fib_levels_cfg:
            self.fib_levels_cfg = [0.382, 0.500, 0.618]
            
        self.fib_extensions_cfg: List[float] = strat.get("fib_extensions", self.EXTENSION_RATIOS)
        self.min_rr: float = risk.get("min_risk_reward", 2.0)

    @property
    def warmup_period(self) -> int:
        return max(self.swing_threshold * 2 + 20, 40)

    # ── Swing detection ────────────────────────────────────────────────────────

    def find_swing_high(self, highs: pd.Series) -> Optional[Tuple[int, float]]:
        """
        Scan from right to left and return (index_pos, price) of the most
        recent swing high — a candle whose high is greater than
        `swing_threshold` candles on both sides.
        """
        n = len(highs)
        t = self.swing_threshold
        for i in range(n - t - 1, t, -1):
            candidate = highs.iloc[i]
            left = highs.iloc[i - t: i]
            right = highs.iloc[i + 1: i + t + 1]
            if (candidate > left).all() and (candidate > right).all():
                return i, candidate
        return None

    def find_swing_low(self, lows: pd.Series) -> Optional[Tuple[int, float]]:
        """Most recent swing low."""
        n = len(lows)
        t = self.swing_threshold
        for i in range(n - t - 1, t, -1):
            candidate = lows.iloc[i]
            left = lows.iloc[i - t: i]
            right = lows.iloc[i + 1: i + t + 1]
            if (candidate < left).all() and (candidate < right).all():
                return i, candidate
        return None

    # ── Level computation ──────────────────────────────────────────────────────

    def calculate_fib_levels(
        self, swing_high: float, swing_low: float, direction: Direction
    ) -> FibLevels:
        diff = swing_high - swing_low
        levels: Dict[float, float] = {}
        extensions: Dict[float, float] = {}

        for ratio in self.fib_levels_cfg:
            if direction == Direction.LONG:
                levels[ratio] = swing_high - diff * ratio
            else:
                levels[ratio] = swing_low + diff * ratio

        for ratio in self.fib_extensions_cfg:
            if direction == Direction.LONG:
                extensions[ratio] = swing_high + diff * (ratio - 1.0)
            else:
                extensions[ratio] = swing_low - diff * (ratio - 1.0)

        return FibLevels(swing_high=swing_high, swing_low=swing_low,
                         direction=direction, levels=levels, extensions=extensions)

    # ── Price proximity check ──────────────────────────────────────────────────

    def is_near_level(self, price: float, level_price: float) -> bool:
        return abs(price - level_price) / level_price <= self.price_tolerance

    # ── Confirmation ───────────────────────────────────────────────────────────

    def detect_bullish_reversal(self, df: pd.DataFrame, idx: int) -> bool:
        if idx < 1:
            return False
        
        curr = df.iloc[idx]
        prev = df.iloc[idx - 1]
        
        c_open, c_high, c_low, c_close = curr["open"], curr["high"], curr["low"], curr["close"]
        p_open, p_close = prev["open"], prev["close"]
        
        c_body = abs(c_close - c_open)
        c_range = c_high - c_low if (c_high - c_low) > 0 else 1e-9
        
        # Bullish Engulfing
        is_bullish_engulfing = (
            c_close > c_open and p_close < p_open and
            c_open <= p_close and c_close >= p_open
        )
        
        # Hammer
        c_min = min(c_open, c_close)
        c_max = max(c_open, c_close)
        c_lower_shadow = c_min - c_low
        c_upper_shadow = c_high - c_max
        is_hammer = (
            c_lower_shadow >= 2.0 * c_body and
            c_upper_shadow <= 0.2 * c_body and
            c_body > 0
        )
        
        # Bullish Marubozu
        is_marubozu = (
            c_close > c_open and
            c_body / c_range >= 0.9
        )
        
        return bool(is_bullish_engulfing or is_hammer or is_marubozu)

    def detect_bearish_reversal(self, df: pd.DataFrame, idx: int) -> bool:
        if idx < 1:
            return False
            
        curr = df.iloc[idx]
        prev = df.iloc[idx - 1]
        
        c_open, c_high, c_low, c_close = curr["open"], curr["high"], curr["low"], curr["close"]
        p_open, p_close = prev["open"], prev["close"]
        
        c_body = abs(c_close - c_open)
        c_range = c_high - c_low if (c_high - c_low) > 0 else 1e-9
        
        # Bearish Engulfing
        is_bearish_engulfing = (
            c_close < c_open and p_close > p_open and
            c_open >= p_close and c_close <= p_open
        )
        
        # Shooting Star
        c_min = min(c_open, c_close)
        c_max = max(c_open, c_close)
        c_upper_shadow = c_high - c_max
        c_lower_shadow = c_min - c_low
        is_shooting_star = (
            c_upper_shadow >= 2.0 * c_body and
            c_lower_shadow <= 0.2 * c_body and
            c_body > 0
        )
        
        # Bearish Marubozu
        is_marubozu = (
            c_close < c_open and
            c_body / c_range >= 0.9
        )
        
        return bool(is_bearish_engulfing or is_shooting_star or is_marubozu)

    def _calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        """Calculate session VWAP resetting every trading day."""
        tp = (df["high"] + df["low"] + df["close"]) / 3
        tp_vol = tp * df["volume"]
        dates = df.index.date
        cum_tp_vol = tp_vol.groupby(dates).cumsum()
        cum_vol = df["volume"].groupby(dates).cumsum()
        vwap = cum_tp_vol / (cum_vol + 1e-9)
        return vwap

    # ── ATR helper ─────────────────────────────────────────────────────────────

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["high"]
        low = df["low"]
        prev_close = df["close"].shift(1)
        tr = pd.concat([high - low,
                         (high - prev_close).abs(),
                         (low - prev_close).abs()], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    # ── Main signal generator ──────────────────────────────────────────────────

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> List[Signal]:
        """
        Bar-by-bar scan of *df*. Returns a list of Signal objects.
        """
        if len(df) < max(self.swing_threshold * 2 + 20, self.volume_period):
            return []

        signals: List[Signal] = []
        atr = self._atr(df)

        # ── VWAP calculation ──
        current_vwap = None
        if self.use_vwap:
            vwap_series = self._calculate_vwap(df)
            current_vwap = vwap_series.iloc[-1]

        # ── Detect swing high/low ──
        sh_result = self.find_swing_high(df["high"])
        sl_result = self.find_swing_low(df["low"])

        if sh_result and sl_result:
            sh_idx, sh_price = sh_result
            sl_idx, sl_price = sl_result

            trend_strength = (sh_price - sl_price) / (atr.iloc[sh_idx] + 1e-9)
            if trend_strength < self.min_trend_strength:
                return []

            current_price = df["close"].iloc[-1]
            current_idx = len(df) - 1
            current_volume = df["volume"].iloc[-1]
            avg_vol = df["volume"].rolling(self.volume_period).mean().iloc[-1]

            # ── LONG: swing low before swing high ──────────────────────────
            if sl_idx < sh_idx:
                # Trend filter: Only allow LONG if Close > VWAP
                if self.vwap_filter and current_vwap is not None and current_price <= current_vwap:
                    return []

                fib = self.calculate_fib_levels(sh_price, sl_price, Direction.LONG)

                for ratio, level_price in fib.levels.items():
                    if ratio not in self.fib_levels_cfg:
                        continue
                    # Proximity check (Fib Zone +/-0.2% by default)
                    if abs(current_price - level_price) / level_price > self.fib_zone:
                        continue
                    
                    # Reversal confirmation
                    if self.confirmation_type == "reversal_candle":
                        if not self.detect_bullish_reversal(df, current_idx):
                            continue
                    else:
                        # Fallback to standard bullish confirmation (1 simple bullish candle)
                        if current_price <= df["open"].iloc[-1]:
                            continue

                    # Volume filter
                    if current_volume <= avg_vol * self.volume_multiplier:
                        continue

                    # Stop Loss: Below Swing Low OR 1 ATR below entry
                    stop = min(sl_price, current_price - atr.iloc[-1])
                    
                    # Target: next extension level (1.272 preferred, fallback to 1.618)
                    target = fib.extensions.get(1.272, fib.extensions.get(1.618, sh_price))
                    
                    rr = (target - current_price) / max(current_price - stop, 1e-9)
                    if rr < self.min_rr:
                        continue

                    confidence = self._confidence_score(ratio, rr, trend_strength)
                    sig = Signal(
                        symbol=symbol,
                        direction=Direction.LONG,
                        entry_price=round(current_price, 2),
                        stop_loss=round(stop, 2),
                        target=round(target, 2),
                        fib_level=ratio,
                        swing_high=sh_price,
                        swing_low=sl_price,
                        timestamp=df.index[-1],
                        confidence=confidence,
                    )
                    signals.append(sig)
                    logger.info(f"[{symbol}] LONG signal @ {current_price:.2f} | Fib {ratio:.3f} | RR {rr:.2f}")
                    break   # one signal per scan

            # ── SHORT: swing high before swing low ─────────────────────────
            elif sh_idx < sl_idx:
                # Trend filter: Only allow SHORT if Close < VWAP
                if self.vwap_filter and current_vwap is not None and current_price >= current_vwap:
                    return []

                fib = self.calculate_fib_levels(sh_price, sl_price, Direction.SHORT)

                for ratio, level_price in fib.levels.items():
                    if ratio not in self.fib_levels_cfg:
                        continue
                    # Proximity check (Fib Zone +/-0.2% by default)
                    if abs(current_price - level_price) / level_price > self.fib_zone:
                        continue
                    
                    # Reversal confirmation
                    if self.confirmation_type == "reversal_candle":
                        if not self.detect_bearish_reversal(df, current_idx):
                            continue
                    else:
                        # Fallback to standard bearish confirmation (1 simple bearish candle)
                        if current_price >= df["open"].iloc[-1]:
                            continue

                    # Volume filter
                    if current_volume <= avg_vol * self.volume_multiplier:
                        continue

                    # Stop Loss: Above Swing High OR 1 ATR above entry
                    stop = max(sh_price, current_price + atr.iloc[-1])
                    
                    # Target: next extension level (1.272 preferred, fallback to 1.618)
                    target = fib.extensions.get(1.272, fib.extensions.get(1.618, sl_price))
                    
                    rr = (current_price - target) / max(stop - current_price, 1e-9)
                    if rr < self.min_rr:
                        continue

                    confidence = self._confidence_score(ratio, rr, trend_strength)
                    sig = Signal(
                        symbol=symbol,
                        direction=Direction.SHORT,
                        entry_price=round(current_price, 2),
                        stop_loss=round(stop, 2),
                        target=round(target, 2),
                        fib_level=ratio,
                        swing_high=sh_price,
                        swing_low=sl_price,
                        timestamp=df.index[-1],
                        confidence=confidence,
                    )
                    signals.append(sig)
                    logger.info(f"[{symbol}] SHORT signal @ {current_price:.2f} | Fib {ratio:.3f} | RR {rr:.2f}")
                    break

        return signals

    # ── Confidence scoring ────────────────────────────────────────────────────

    @staticmethod
    def _confidence_score(fib_ratio: float, rr: float, trend_strength: float) -> float:
        """
        Heuristic 0–1 score.
        Golden ratio (0.618) and 0.382 are the strongest Fib levels.
        """
        level_weight = {0.236: 0.5, 0.382: 0.8, 0.500: 0.6, 0.618: 1.0, 0.786: 0.7}
        lw = level_weight.get(fib_ratio, 0.4)
        rr_score = min(rr / 5.0, 1.0)
        ts_score = min(trend_strength / 10.0, 1.0)
        return round((lw * 0.5 + rr_score * 0.3 + ts_score * 0.2), 3)
