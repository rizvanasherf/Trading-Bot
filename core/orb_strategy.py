"""
core/orb_strategy.py
--------------------
ORBStrategy: detects Opening Range High (ORH) and Opening Range Low (ORL),
evaluates momentum breakouts on candle closes, and emits Signal objects.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import pandas as pd
from core.strategy import Signal, Direction
from utils.logger import logger

class ORBStrategy:
    def __init__(self, config: dict):
        strat = config.get("strategy", {}) or {}
        orb_cfg = config.get("orb", {}) or {}
        
        self.start_time: str = orb_cfg.get("start_time", "09:15")
        self.end_time: str = orb_cfg.get("end_time", "09:30")
        self.volume_period: int = orb_cfg.get("volume_period", 20)
        self.volume_multiplier: float = orb_cfg.get("volume_multiplier", 2.0)
        self.use_vwap_filter: bool = orb_cfg.get("use_vwap_filter", True)
        self.target_multiplier: float = orb_cfg.get("target_multiplier", 1.5)
        self.min_range_pct: float = orb_cfg.get("min_range_pct", 0.001)
        self.max_range_pct: float = orb_cfg.get("max_range_pct", 0.02)
        
        self.timeframe: str = strat.get("timeframe", "5minute")

    @property
    def warmup_period(self) -> int:
        return self.volume_period + 2

    def _calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        tp_vol = tp * df["volume"]
        dates = df.index.date
        cum_tp_vol = tp_vol.groupby(dates).cumsum()
        cum_vol = df["volume"].groupby(dates).cumsum()
        return cum_tp_vol / (cum_vol + 1e-9)

    def _atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["high"]
        low = df["low"]
        prev_close = df["close"].shift(1)
        tr = pd.concat([high - low,
                         (high - prev_close).abs(),
                         (low - prev_close).abs()], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def _calculate_rsi_15m(self, df: pd.DataFrame, period: int = 14) -> float:
        """Resample base data to 15-minute timeframe and calculate RSI."""
        try:
            # Resample input dataframe (which might be 1m, 3m, 5m etc) to 15m
            df_15m = df.resample("15min").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            }).dropna()
            
            if len(df_15m) < period + 2:
                # If resampled bars are too few, compute standard RSI on the raw series as fallback
                df_15m = df
                
            delta = df_15m["close"].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            
            avg_gain = gain.rolling(period).mean()
            avg_loss = loss.rolling(period).mean()
            
            # Wilders smoothing
            for i in range(period, len(df_15m)):
                avg_gain.iloc[i] = (avg_gain.iloc[i-1] * (period - 1) + gain.iloc[i]) / period
                avg_loss.iloc[i] = (avg_loss.iloc[i-1] * (period - 1) + loss.iloc[i]) / period
                
            rs = avg_gain / (avg_loss + 1e-9)
            rsi = 100 - (100 / (1 + rs))
            return float(rsi.iloc[-1])
        except Exception as e:
            logger.warning(f"RSI calculation exception, falling back to neutral: {e}")
            return 50.0

    def calculate_opening_range(self, df_day: pd.DataFrame) -> Tuple[Optional[float], Optional[float]]:
        """Calculate the ORH and ORL using range window timestamps."""
        if df_day.empty:
            return None, None
        
        times = df_day.index.time
        # Convert start/end configurations into time objects
        try:
            start_t = pd.to_datetime(self.start_time, format="%H:%M").time()
            end_t = pd.to_datetime(self.end_time, format="%H:%M").time()
        except Exception:
            start_t = pd.to_datetime("09:15", format="%H:%M").time()
            end_t = pd.to_datetime("09:30", format="%H:%M").time()
            
        in_range = df_day[(times >= start_t) & (times < end_t)]
        if in_range.empty:
            return None, None
            
        orh = float(in_range["high"].max())
        orl = float(in_range["low"].min())
        return orh, orl

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> List[Signal]:
        """
        Bar-by-bar evaluation to find breakouts on candle closes.
        """
        if df.empty or len(df) < self.warmup_period:
            return []

        # Get current active bar info
        curr_bar = df.iloc[-1]
        curr_time = df.index[-1]
        curr_date = curr_time.date()

        # Initialize diagnostics container
        self.last_diagnostics = {
            "symbol": symbol,
            "strategy": "orb",
            "timestamp": curr_time.strftime("%Y-%m-%d %H:%M:%S") if hasattr(curr_time, "strftime") else str(curr_time),
            "orh": None,
            "orl": None,
            "range_pct": None,
            "close": float(curr_bar["close"]),
            "vol_ratio": None,
            "rsi_15m": None,
            "vwap": None,
            "conditions": {},
            "status": "Scanning"
        }

        # Filter dataframe for the current active day
        df_day = df[df.index.date == curr_date]
        if df_day.empty or len(df_day) < 3:
            self.last_diagnostics["status"] = f"Insufficient intraday candles ({len(df_day)} < 3)"
            logger.info(f"[ORB Eval] [{symbol}] {self.last_diagnostics['status']}")
            return []

        # 1. Calculate Opening Range High and Low
        orh, orl = self.calculate_opening_range(df_day)
        if orh is None or orl is None:
            self.last_diagnostics["status"] = "Waiting for Opening Range (09:15-09:30 AM)"
            logger.info(f"[ORB Eval] [{symbol}] {self.last_diagnostics['status']}")
            return []

        self.last_diagnostics["orh"] = round(orh, 2)
        self.last_diagnostics["orl"] = round(orl, 2)

        # Make sure we have crossed the end boundary time (e.g. current bar starts at or after 09:30)
        try:
            end_t = pd.to_datetime(self.end_time, format="%H:%M").time()
        except Exception:
            end_t = pd.to_datetime("09:30", format="%H:%M").time()
            
        if curr_time.time() < end_t:
            self.last_diagnostics["status"] = f"Waiting for market to cross 09:30 AM (current: {curr_time.time().strftime('%H:%M')})"
            logger.info(f"[ORB Eval] [{symbol}] {self.last_diagnostics['status']}")
            return []

        # 2. Enforce Range Quality Filters (skip if range is too narrow or too wide)
        range_size = orh - orl
        range_pct = range_size / (orl + 1e-9)
        self.last_diagnostics["range_pct"] = round(range_pct * 100, 3)

        if range_pct < self.min_range_pct or range_pct > self.max_range_pct:
            self.last_diagnostics["status"] = f"Range quality failed (OR range: {(range_pct*100):.2f}% outside [{self.min_range_pct*100:.1f}%, {self.max_range_pct*100:.1f}%])"
            logger.info(f"[ORB Eval] [{symbol}] {self.last_diagnostics['status']}")
            return []

        current_close = float(curr_bar["close"])
        current_volume = float(curr_bar["volume"])
        avg_vol = float(df["volume"].rolling(self.volume_period).mean().iloc[-1]) if len(df) >= self.volume_period else 1.0
        vol_ratio = current_volume / (avg_vol + 1e-9)
        self.last_diagnostics["vol_ratio"] = round(vol_ratio, 2)
        
        # 3. Volume filter check
        vol_pass = current_volume >= avg_vol * self.volume_multiplier

        # Calculate VWAP
        current_vwap = None
        if self.use_vwap_filter:
            vwap_series = self._calculate_vwap(df)
            current_vwap = float(vwap_series.iloc[-1])
            self.last_diagnostics["vwap"] = round(current_vwap, 2)

        atr_series = self._atr(df)
        current_atr = float(atr_series.iloc[-1]) if not atr_series.empty else 1.0

        # Previous bar close to check if breakout just occurred
        prev_close = float(df_day["close"].iloc[-2]) if len(df_day) > 1 else current_close

        # Calculate 15m RSI filter
        rsi_15m = self._calculate_rsi_15m(df)
        self.last_diagnostics["rsi_15m"] = round(rsi_15m, 1)

        # Evaluate breakout direction checks
        long_cross = prev_close <= orh and current_close > orh
        short_cross = prev_close >= orl and current_close < orl
        
        rsi_long_pass = rsi_15m >= 55.0
        rsi_short_pass = rsi_15m <= 45.0
        vwap_long_pass = (current_vwap is None) or (current_close > current_vwap)
        vwap_short_pass = (current_vwap is None) or (current_close < current_vwap)

        self.last_diagnostics["conditions"] = {
            "time_window": True,
            "range_quality": True,
            "volume_filter": vol_pass,
            "rsi_filter": rsi_long_pass if current_close > orh else (rsi_short_pass if current_close < orl else False),
            "vwap_filter": vwap_long_pass if current_close > orh else (vwap_short_pass if current_close < orl else False),
            "crossover": long_cross or short_cross
        }

        # 4. Check for Long Breakout (close crosses above ORH)
        if long_cross:
            if not vol_pass:
                self.last_diagnostics["status"] = f"Breakout Above ORH | Failing Volume ({vol_ratio:.2f}x < {self.volume_multiplier:.1f}x req)"
                logger.info(f"[ORB Eval] [{symbol}] {self.last_diagnostics['status']}")
                return []
            if not rsi_long_pass:
                self.last_diagnostics["status"] = f"Breakout Above ORH | Failing RSI 15m ({rsi_15m:.1f} < 55.0 req)"
                logger.info(f"[ORB Eval] [{symbol}] {self.last_diagnostics['status']}")
                return []
            if not vwap_long_pass:
                self.last_diagnostics["status"] = f"Breakout Above ORH | Failing VWAP (Close {current_close:.1f} <= VWAP {current_vwap:.1f})"
                logger.info(f"[ORB Eval] [{symbol}] {self.last_diagnostics['status']}")
                return []
                
            stop_loss = max(orl, current_close - 1.5 * current_atr)
            target = current_close + range_size * self.target_multiplier
            
            self.last_diagnostics["status"] = f"TRIGGERED: LONG BREAKOUT @ {current_close:.2f}"
            logger.info(f"[ORB Strategy] LONG breakout triggered on {symbol} @ {current_close:.2f}")
            
            return [Signal(
                symbol=symbol,
                direction=Direction.LONG,
                entry_price=current_close,
                stop_loss=stop_loss,
                target=target,
                fib_level=0.0,
                swing_high=orh,
                swing_low=orl,
                timestamp=curr_time,
                confidence=0.8
            )]

        # 5. Check for Short Breakout (close crosses below ORL)
        if short_cross:
            if not vol_pass:
                self.last_diagnostics["status"] = f"Breakdown Below ORL | Failing Volume ({vol_ratio:.2f}x < {self.volume_multiplier:.1f}x req)"
                logger.info(f"[ORB Eval] [{symbol}] {self.last_diagnostics['status']}")
                return []
            if not rsi_short_pass:
                self.last_diagnostics["status"] = f"Breakdown Below ORL | Failing RSI 15m ({rsi_15m:.1f} > 45.0 req)"
                logger.info(f"[ORB Eval] [{symbol}] {self.last_diagnostics['status']}")
                return []
            if not vwap_short_pass:
                self.last_diagnostics["status"] = f"Breakdown Below ORL | Failing VWAP (Close {current_close:.1f} >= VWAP {current_vwap:.1f})"
                logger.info(f"[ORB Eval] [{symbol}] {self.last_diagnostics['status']}")
                return []
                
            stop_loss = min(orh, current_close + 1.5 * current_atr)
            target = current_close - range_size * self.target_multiplier
            
            self.last_diagnostics["status"] = f"TRIGGERED: SHORT BREAKOUT @ {current_close:.2f}"
            logger.info(f"[ORB Strategy] SHORT breakout triggered on {symbol} @ {current_close:.2f}")
            
            return [Signal(
                symbol=symbol,
                direction=Direction.SHORT,
                entry_price=current_close,
                stop_loss=stop_loss,
                target=target,
                fib_level=0.0,
                swing_high=orh,
                swing_low=orl,
                timestamp=curr_time,
                confidence=0.8
            )]

        # If no breakout crossover on this exact bar
        pos_str = "Above ORH" if current_close > orh else ("Below ORL" if current_close < orl else "Inside OR Range")
        self.last_diagnostics["status"] = f"Price {current_close:.2f} {pos_str} (ORH: {orh:.2f}, ORL: {orl:.2f}) | Vol: {vol_ratio:.2f}x | RSI15m: {rsi_15m:.1f}"
        logger.info(f"[ORB Eval] [{symbol}] {self.last_diagnostics['status']}")
        return []
