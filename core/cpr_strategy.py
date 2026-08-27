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
        
        # Tunable state machine parameters (should be optimized via backtesting)
        self.breakout_buffer: float = float(cpr_cfg.get("breakout_buffer", 0.0))
        self.bias_cutoff_time: str = cpr_cfg.get("bias_cutoff_time", "14:30")
        
        # State machine tracking variables
        self.trend_bias = None  # None | "BULLISH" | "BEARISH"
        self.breakout_candidate = None  # None | "BULLISH" | "BEARISH"
        self.last_bias_date = None
        
        from core.data_fetcher import KiteDataFetcher
        self.data_fetcher = KiteDataFetcher()
        self._cpr_cache = {}  # Cache lookup to prevent redundant daily downloads: (symbol, ref_date) -> (pivot, tc, bc)

    @property
    def warmup_period(self) -> int:
        return max(self.volume_period, self.ema_period, 40)

    def calculate_cpr(self, symbol: str, ref_date: Optional[datetime.date] = None) -> Optional[Tuple[float, float, float]]:
        """Calculate CPR levels (Pivot, TC, BC) from the previous day's OHLC data."""
        try:
            target_date = ref_date if ref_date is not None else now_ist().date()
            cache_key = (symbol.upper(), target_date)
            if cache_key in self._cpr_cache:
                return self._cpr_cache[cache_key]

            df_daily = self.data_fetcher.get_historical_data_yfinance(symbol, interval="day", days=365)
            if df_daily.empty:
                return None
            
            # Find the last completed trading day relative to ref_date
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
            
            res = (pivot, tc, bc)
            self._cpr_cache[cache_key] = res
            return res
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
        
        # Calculate EMA 20
        df = df.copy()
        df["ema"] = df["close"].ewm(span=self.ema_period, adjust=False).mean()
        
        today = df.index[-1].date()
        today_df = df[df.index.date == today]
        
        # We need completed candles today to establish state
        # The currently forming candle is excluded (the last row of today_df)
        completed_today_df = today_df.iloc[:-1]
        
        # Reset state at day transition
        if self.last_bias_date != today:
            self.trend_bias = None
            self.breakout_candidate = None
            self.last_bias_date = today

        # Replay the state machine from the beginning of today's completed candles
        # to ensure deterministic behavior on bot restarts or data reloads
        self.trend_bias = None
        self.breakout_candidate = None

        import datetime
        bias_start_time = datetime.time(9, 15)
        try:
            h_cut, m_cut = map(int, self.bias_cutoff_time.split(":"))
            bias_cutoff_time = datetime.time(h_cut, m_cut)
        except Exception:
            bias_cutoff_time = datetime.time(14, 30)

        for idx, row in completed_today_df.iterrows():
            # First confirmed breakout wins and locks for the rest of the day
            if self.trend_bias is not None:
                continue

            candle_time = idx.time()
            # Only allow establishing a NEW bias candidate within the time window
            if not (bias_start_time <= candle_time <= bias_cutoff_time):
                self.breakout_candidate = None
                continue

            close_val = float(row["close"])
            
            # Tunable buffer check to avoid noise breakouts
            is_above = close_val > cpr_max + self.breakout_buffer
            is_below = close_val < cpr_min - self.breakout_buffer

            if is_above:
                if self.breakout_candidate == "BULLISH":
                    self.trend_bias = "BULLISH"
                    self.breakout_candidate = None
                else:
                    self.breakout_candidate = "BULLISH"
            elif is_below:
                if self.breakout_candidate == "BEARISH":
                    self.trend_bias = "BEARISH"
                    self.breakout_candidate = None
                else:
                    self.breakout_candidate = "BEARISH"
            else:
                # Fails to confirm on the next candle -> reset candidate
                self.breakout_candidate = None

        # If no bias has been established and locked, we do not trade today
        if self.trend_bias is None:
            return []

        # Check trading time window for entries (9:30 AM to 3:00 PM IST)
        curr_time = df.index[-1].time()
        start_trade_time = datetime.time(9, 30)
        end_trade_time = datetime.time(15, 0)
        
        if not (start_trade_time <= curr_time <= end_trade_time):
            return []
            
        curr_close = float(df["close"].iloc[-1])
        curr_ema = float(df["ema"].iloc[-1])
        prev_high = float(df["high"].iloc[-2])
        prev_low = float(df["low"].iloc[-2])
        
        buy_ce = (self.trend_bias == "BULLISH") and curr_close > curr_ema and curr_close > prev_high
        buy_pe = (self.trend_bias == "BEARISH") and curr_close < curr_ema and curr_close < prev_low
        
        if buy_ce:
            signal_candle_low = float(df["low"].iloc[-1])
            stop_loss = min(cpr_max, signal_candle_low)
            
            # Max spot risk check: cap at 2.0% of entry price
            if curr_close - stop_loss > curr_close * 0.02:
                stop_loss = curr_close * 0.98
                
            target = curr_close + (curr_close - stop_loss) * self.risk_reward_ratio
            
            logger.info(
                f"[CPR Strategy] Bullish Signal triggered on {symbol}. "
                f"LTP: {curr_close}, EMA20: {curr_ema}, PrevHigh: {prev_high}. "
                f"StopLoss: {stop_loss}, Target: {target}"
            )
            
            return [Signal(
                symbol=symbol,
                direction=Direction.LONG,
                entry_price=curr_close,
                stop_loss=round(stop_loss, 2),
                target=round(target, 2),
                fib_level=0.0,
                swing_high=prev_high,
                swing_low=prev_low,
                timestamp=df.index[-1],
                confidence=0.8
            )]
            
        elif buy_pe:
            signal_candle_high = float(df["high"].iloc[-1])
            stop_loss = max(cpr_min, signal_candle_high)
            
            # Max spot risk check: cap at 2.0% of entry price
            if stop_loss - curr_close > curr_close * 0.02:
                stop_loss = curr_close * 1.02
                
            target = curr_close - (stop_loss - curr_close) * self.risk_reward_ratio
            
            logger.info(
                f"[CPR Strategy] Bearish Signal triggered on {symbol}. "
                f"LTP: {curr_close}, EMA20: {curr_ema}, PrevLow: {prev_low}. "
                f"StopLoss: {stop_loss}, Target: {target}"
            )
            
            return [Signal(
                symbol=symbol,
                direction=Direction.SHORT,
                entry_price=curr_close,
                stop_loss=round(stop_loss, 2),
                target=round(target, 2),
                fib_level=0.0,
                swing_high=prev_high,
                swing_low=prev_low,
                timestamp=df.index[-1],
                confidence=0.8
            )]
            
        return []
