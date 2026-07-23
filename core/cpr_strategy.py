"""
core/cpr_strategy.py
--------------------
CPR Intraday Strategy: calculates CPR (Pivot, TC, BC) based on previous day's spot,
analyzes 5m Nifty spot data, and emits signals for CE/PE ATM buys.
"""
from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
from core.strategy import Signal, Direction
from utils.logger import logger
from utils.helpers import now_ist

class CPRIntradayStrategy:
    def __init__(self, config: dict):
        strat = config.get("strategy", {}) or {}
        cpr_cfg = config.get("cpr_intraday", {}) or {}
        
        self.ema_period: int = int(cpr_cfg.get("ema_period", 20))
        self.volume_period: int = int(cpr_cfg.get("volume_period", 20))
        self.volume_multiplier: float = float(cpr_cfg.get("volume_multiplier", 1.3))
        self.narrow_cpr_threshold: float = float(cpr_cfg.get("narrow_cpr_threshold", 0.05))  # in %
        self.wide_cpr_threshold: float = float(cpr_cfg.get("wide_cpr_threshold", 0.15))      # in %
        self.stop_loss_type: str = cpr_cfg.get("stop_loss_type", "logical")                 # logical | atr
        self.atr_period: int = int(cpr_cfg.get("atr_period", 14))
        self.atr_multiplier: float = float(cpr_cfg.get("atr_multiplier", 1.5))
        self.risk_reward_ratio: float = float(cpr_cfg.get("risk_reward_ratio", 2.0))
        self.timeframe: str = strat.get("timeframe", "5minute")
        
        from core.data_fetcher import KiteDataFetcher
        self.data_fetcher = KiteDataFetcher()

    @property
    def warmup_period(self) -> int:
        return max(self.volume_period, self.ema_period, 40)

    def calculate_cpr(self, symbol: str, ref_date: Optional[datetime.date] = None) -> Optional[Tuple[float, float, float]]:
        """Calculate CPR levels (Pivot, TC, BC) from the previous day's OHLC data."""
        try:
            df_daily = self.data_fetcher.get_historical_data_yfinance(symbol, interval="day", days=365)
            if df_daily.empty:
                return None
            
            # Find the last completed trading day relative to ref_date
            target_date = ref_date if ref_date is not None else now_ist().date()
            completed_days = df_daily[df_daily.index.date < target_date]
            
            if completed_days.empty:
                prev_day = df_daily.iloc[-1]
            else:
                prev_day = completed_days.iloc[-1]
                
            high = float(prev_day["high"])
            low = float(prev_day["low"])
            close = float(prev_day["close"])
            
            pivot = (high + low + close) / 3
            bc = (high + low) / 2
            tc = (pivot - bc) + pivot
            
            return pivot, tc, bc
        except Exception as e:
            logger.error(f"[CPR Strategy] Error calculating CPR for {symbol}: {e}")
            return None

    def _calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        cum_pv = (tp * df["volume"]).groupby(df.index.date).cumsum()
        cum_v = df["volume"].groupby(df.index.date).cumsum()
        return cum_pv / (cum_v + 1e-9)

    def _atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["high"]
        low = df["low"]
        prev_close = df["close"].shift(1)
        tr = pd.concat([high - low,
                         (high - prev_close).abs(),
                         (low - prev_close).abs()], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> List[Signal]:
        if len(df) < self.warmup_period:
            return []

        ref_date = df.index[-1].date()
        cpr_vals = self.calculate_cpr(symbol, ref_date)
        if not cpr_vals:
            return []
            
        pivot, tc, bc = cpr_vals
        cpr_min = min(tc, bc)
        cpr_max = max(tc, bc)
        
        # CPR width in percent
        cpr_width = (abs(tc - bc) / pivot) * 100
        is_narrow = cpr_width <= self.narrow_cpr_threshold
        is_wide = cpr_width >= self.wide_cpr_threshold
        
        # Calculate indicators
        df = df.copy()
        df["vwap"] = self._calculate_vwap(df)
        df["ema"] = df["close"].ewm(span=self.ema_period, adjust=False).mean()
        df["vol_ma"] = df["volume"].rolling(window=self.volume_period).mean()
        df["atr"] = self._atr(df, period=self.atr_period)
        
        today = df.index[-1].date()
        today_df = df[df.index.date == today]
        
        if len(today_df) < 2:
            return []  # Need at least two candles today to check slope/breakout
            
        # 1. Price opened above/below CPR
        first_open = float(today_df["open"].iloc[0])
        opened_above = first_open > cpr_max
        opened_below = first_open < cpr_min
        
        # 2. Price remains above/below CPR
        remains_above = today_df["low"].min() > cpr_max
        remains_below = today_df["high"].max() < cpr_min
        
        # 3. Latest values
        curr_close = float(df["close"].iloc[-1])
        curr_high = float(df["high"].iloc[-1])
        curr_low = float(df["low"].iloc[-1])
        curr_volume = float(df["volume"].iloc[-1])
        curr_vwap = float(df["vwap"].iloc[-1])
        
        # EMA Slope (computed over last 3 candles)
        ema_slope_up = df["ema"].iloc[-1] > df["ema"].iloc[-2] and df["ema"].iloc[-2] > df["ema"].iloc[-3]
        ema_slope_down = df["ema"].iloc[-1] < df["ema"].iloc[-2] and df["ema"].iloc[-2] < df["ema"].iloc[-3]
        
        # Recent swing high/low lookback (excluding current candle)
        lookback = min(20, len(df) - 1)
        recent_closes = df.iloc[-lookback-1:-1]
        swing_high = float(recent_closes["high"].max())
        swing_low = float(recent_closes["low"].min())
        
        # Breakout / Breakdown
        breakout = curr_close > swing_high
        breakdown = curr_close < swing_low
        
        # Volume check
        vol_check = curr_volume > (df["vol_ma"].iloc[-1] * self.volume_multiplier)
        
        # If CPR is wide, require stronger volume for breakout
        if is_wide:
            vol_check = curr_volume > (df["vol_ma"].iloc[-1] * self.volume_multiplier * 1.5)
            
        # Fallback for Index Spot trading (like NIFTY) which lacks volume and VWAP
        is_index = symbol.upper() in ("NIFTY", "NIFTY 50", "NIFTY_50", "BANKNIFTY", "FINNIFTY") or df["volume"].sum() == 0
        if is_index:
            vol_check = True  # Bypass volume check as volume is always 0
            curr_vwap = df["ema"].iloc[-1]  # Fallback to EMA 20 instead of VWAP
            
        # Check trading window (9:20 AM - 2:45 PM)
        curr_time = df.index[-1].time()
        start_trade_time = datetime.time(9, 20)
        end_trade_time = datetime.time(14, 45)
        
        time_allows_entry = start_trade_time <= curr_time <= end_trade_time
        if not time_allows_entry:
            return []
            
        # Buy CE (LONG) Conditions
        buy_ce = (
            opened_above and
            remains_above and
            curr_close > curr_vwap and
            ema_slope_up and
            breakout and
            vol_check
        )
        
        # Buy PE (SHORT) Conditions
        buy_pe = (
            opened_below and
            remains_below and
            curr_close < curr_vwap and
            ema_slope_down and
            breakdown and
            vol_check
        )
        
        # Confidence multiplier
        confidence = 0.8 if is_narrow else 0.5
        
        if buy_ce:
            if self.stop_loss_type == "atr":
                sl_dist = float(df["atr"].iloc[-1]) * self.atr_multiplier
                stop_loss = curr_close - sl_dist
            else:
                # Logical: below CPR or below breakout candle low
                breakout_candle_low = float(df["low"].iloc[-1])
                stop_loss = min(cpr_min, breakout_candle_low)
                
            if curr_close - stop_loss > curr_close * 0.02:
                stop_loss = curr_close * 0.98  # Cap at 2% risk
                
            target = curr_close + (curr_close - stop_loss) * self.risk_reward_ratio
            
            return [Signal(
                symbol=symbol,
                direction=Direction.LONG,
                entry_price=curr_close,
                stop_loss=round(stop_loss, 2),
                target=round(target, 2),
                fib_level=0.0,
                swing_high=swing_high,
                swing_low=swing_low,
                timestamp=df.index[-1],
                confidence=confidence
            )]
            
        elif buy_pe:
            if self.stop_loss_type == "atr":
                sl_dist = float(df["atr"].iloc[-1]) * self.atr_multiplier
                stop_loss = curr_close + sl_dist
            else:
                # Logical: above CPR or above breakdown candle high
                breakdown_candle_high = float(df["high"].iloc[-1])
                stop_loss = max(cpr_max, breakdown_candle_high)
                
            if stop_loss - curr_close > curr_close * 0.02:
                stop_loss = curr_close * 1.02  # Cap at 2% risk
                
            target = curr_close - (stop_loss - curr_close) * self.risk_reward_ratio
            
            return [Signal(
                symbol=symbol,
                direction=Direction.SHORT,
                entry_price=curr_close,
                stop_loss=round(stop_loss, 2),
                target=round(target, 2),
                fib_level=0.0,
                swing_high=swing_high,
                swing_low=swing_low,
                timestamp=df.index[-1],
                confidence=confidence
            )]
            
        return []
