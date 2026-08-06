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
        
        # We need at least 3 completed candles today (completing 9:15-9:30 range)
        # to establish the 15-minute bias candle
        if len(today_df) < 3:
            return []
            
        # First 15-minute close is the close of the 3rd 5-minute candle of the day
        first_15m_close = float(today_df["close"].iloc[2])
        
        bullish_bias = first_15m_close > cpr_max
        bearish_bias = first_15m_close < cpr_min
        
        if not bullish_bias and not bearish_bias:
            return []  # No directional trade bias established today

        # Check trading time window for entries (9:30 AM to 3:00 PM IST)
        curr_time = df.index[-1].time()
        import datetime
        start_trade_time = datetime.time(9, 30)
        end_trade_time = datetime.time(15, 0)
        
        if not (start_trade_time <= curr_time <= end_trade_time):
            return []
            
        curr_close = float(df["close"].iloc[-1])
        curr_ema = float(df["ema"].iloc[-1])
        prev_high = float(df["high"].iloc[-2])
        prev_low = float(df["low"].iloc[-2])
        
        buy_ce = bullish_bias and curr_close > curr_ema and curr_close > prev_high
        buy_pe = bearish_bias and curr_close < curr_ema and curr_close < prev_low
        
        if buy_ce:
            signal_candle_low = float(df["low"].iloc[-1])
            stop_loss = min(cpr_max, signal_candle_low)
            
            # Max spot risk check: cap at 2.0% of entry price
            if curr_close - stop_loss > curr_close * 0.02:
                stop_loss = curr_close * 0.98
                
            target = curr_close + (curr_close - stop_loss) * self.risk_reward_ratio
            
            logger.info(
                f"[CPR Strategy] Bullish Signal triggered on {symbol}. "
                f"15m Close: {first_15m_close} > CPR Max: {cpr_max}. "
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
                f"15m Close: {first_15m_close} < CPR Min: {cpr_min}. "
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
