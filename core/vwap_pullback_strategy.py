"""
core/vwap_pullback_strategy.py
------------------------------
VWAP Pullback – Nifty 50 Intraday Strategy Module.
"""
import numpy as np
import pandas as pd
from typing import List, Tuple, Optional
from datetime import time

from core.strategy import Direction, Signal

class VWAPPullbackStrategy:
    def __init__(self, config: dict):
        strat = config.get("strategy", {}) or {}
        vp_cfg = config.get("vwap_pullback", {}) or {}
        
        self.ema_period: int = vp_cfg.get("ema_period", 9)
        self.vwap_buffer_pct: float = vp_cfg.get("vwap_buffer_pct", 0.0015)
        self.volume_period: int = vp_cfg.get("volume_period", 20)
        self.volume_multiplier: float = vp_cfg.get("volume_multiplier", 1.2)
        self.stop_loss_pct: float = vp_cfg.get("stop_loss_pct", 0.005)
        self.lookback_swings: int = vp_cfg.get("lookback_swings", 20)
        
        self.timeframe: str = strat.get("timeframe", "5minute")

    @property
    def warmup_period(self) -> int:
        return self.volume_period + 2

    def _calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        cum_pv = (tp * df["volume"]).groupby(df.index.date).cumsum()
        cum_v = df["volume"].groupby(df.index.date).cumsum()
        return cum_pv / (cum_v + 1e-9)

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> List[Signal]:
        if len(df) < self.warmup_period:
            return []

        # Calculate Indicators
        vwap = self._calculate_vwap(df)
        ema = df["close"].ewm(span=self.ema_period, adjust=False).mean()
        vol_ma = df["volume"].rolling(window=self.volume_period).mean()

        # Get latest active candle values
        curr_close = float(df["close"].iloc[-1])
        curr_open = float(df["open"].iloc[-1])
        curr_high = float(df["high"].iloc[-1])
        curr_low = float(df["low"].iloc[-1])
        curr_vol = float(df["volume"].iloc[-1])
        
        curr_vwap = float(vwap.iloc[-1])
        curr_ema = float(ema.iloc[-1])
        prev_ema = float(ema.iloc[-2])
        curr_vol_ma = float(vol_ma.iloc[-1])

        # Slope of EMA9
        ema_slope_up = curr_ema > prev_ema
        ema_slope_down = curr_ema < prev_ema

        # Pullback triggers
        # Check last 3 candles to see if we recently touched/pulled back to VWAP
        pullback_long_detected = False
        pullback_short_detected = False

        for lookback in range(1, 4):
            if len(df) < lookback + 1:
                continue
            hist_low = float(df["low"].iloc[-lookback])
            hist_high = float(df["high"].iloc[-lookback])
            hist_close = float(df["close"].iloc[-lookback])
            hist_vwap = float(vwap.iloc[-lookback])
            
            # Long pullback: low is near or below VWAP, but close doesn't break deep below VWAP
            if hist_low <= hist_vwap * (1 + self.vwap_buffer_pct) and hist_close >= hist_vwap * 0.997:
                pullback_long_detected = True
                
            # Short pullback: high is near or above VWAP, but close doesn't break deep above VWAP
            if hist_high >= hist_vwap * (1 - self.vwap_buffer_pct) and hist_close <= hist_vwap * 1.003:
                pullback_short_detected = True

        signals = []

        # LONG Setup check
        if (curr_close > curr_vwap and 
            curr_close > curr_ema and 
            ema_slope_up and 
            pullback_long_detected and 
            curr_close > curr_open and # Bullish confirmation close
            curr_vol >= curr_vol_ma * self.volume_multiplier):
            
            # Structured Stop Loss: lowest low of last 5 candles or fixed below VWAP
            recent_lows = df["low"].iloc[-5:]
            swing_low = float(recent_lows.min())
            fixed_sl = curr_vwap * (1 - self.stop_loss_pct)
            stop_loss = min(swing_low, fixed_sl)
            
            # Targets
            # Target 1 = previous swing high on lookback
            recent_highs = df["high"].iloc[-self.lookback_swings:-1]
            t1 = float(recent_highs.max()) if len(recent_highs) > 0 else curr_close * 1.01
            # Ensure T1 is higher than entry price
            if t1 <= curr_close:
                t1 = curr_close + (curr_close - stop_loss) * 1.5
                
            # Target 2 = 1:2 Risk-Reward ratio
            risk = curr_close - stop_loss
            t2 = curr_close + risk * 2
            
            signals.append(Signal(
                symbol=symbol,
                direction=Direction.LONG,
                entry_price=curr_close,
                stop_loss=stop_loss,
                target=t2,
                fib_level=0.0,
                swing_high=t1,
                swing_low=swing_low,
                timestamp=df.index[-1],
                confidence=0.8
            ))

        # SHORT Setup check
        elif (curr_close < curr_vwap and 
              curr_close < curr_ema and 
              ema_slope_down and 
              pullback_short_detected and 
              curr_close < curr_open and # Bearish confirmation close
              curr_vol >= curr_vol_ma * self.volume_multiplier):
              
            recent_highs = df["high"].iloc[-5:]
            swing_high = float(recent_highs.max())
            fixed_sl = curr_vwap * (1 + self.stop_loss_pct)
            stop_loss = max(swing_high, fixed_sl)
            
            # Targets
            recent_lows = df["low"].iloc[-self.lookback_swings:-1]
            t1 = float(recent_lows.min()) if len(recent_lows) > 0 else curr_close * 0.99
            if t1 >= curr_close:
                t1 = curr_close - (stop_loss - curr_close) * 1.5
                
            risk = stop_loss - curr_close
            t2 = curr_close - risk * 2
            
            signals.append(Signal(
                symbol=symbol,
                direction=Direction.SHORT,
                entry_price=curr_close,
                stop_loss=stop_loss,
                target=t2,
                fib_level=0.0,
                swing_high=swing_high,
                swing_low=t1,
                timestamp=df.index[-1],
                confidence=0.8
            ))

        return signals
