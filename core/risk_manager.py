"""
core/risk_manager.py
--------------------
RiskManager enforces position sizing, circuit breakers, and daily limits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Optional

from utils.logger import logger
from utils.helpers import now_ist


@dataclass
class DailyStats:
    date: date = field(default_factory=lambda: now_ist().date())
    trades: int = 0
    winners: int = 0
    losers: int = 0
    gross_pnl: float = 0.0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0

    @property
    def win_rate(self) -> float:
        total = self.winners + self.losers
        return self.winners / total if total else 0.0

    @property
    def drawdown(self) -> float:
        return min(self.gross_pnl, 0.0)


class RiskManager:
    def __init__(self, config: dict, capital: Optional[float] = None):
        risk = config.get("risk", {})
        self.capital: float = capital or risk.get("capital", 500_000)
        self.risk_per_trade: float = risk.get("risk_per_trade", 0.01)
        self.max_daily_loss: float = risk.get("max_daily_loss", 0.03)
        self.max_consecutive_losses: int = risk.get("max_consecutive_losses", 4)
        self.max_daily_trades: int = risk.get("max_daily_trades", 10)
        self.min_risk_reward: float = risk.get("min_risk_reward", 2.0)
        self.max_stock_concentration: float = risk.get("max_stock_concentration", 0.20)

        self.stats = DailyStats()
        self._position_exposure: Dict[str, float] = {}  # symbol → INR value

    # ── Daily reset ────────────────────────────────────────────────────────────

    def reset_daily_counters(self) -> None:
        today = now_ist().date()
        if self.stats.date != today:
            logger.info("Resetting daily risk counters for new session.")
            self.stats = DailyStats(date=today)
            self._position_exposure.clear()

    # ── Position sizing ────────────────────────────────────────────────────────

    def calculate_position_size(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        current_capital: Optional[float] = None,
        atr: Optional[float] = None,
    ) -> int:
        """
        Returns number of shares to trade.
        Risk per trade = risk_per_trade * capital (adjusted dynamically for high volatility).
        Also caps stock concentration at max_stock_concentration.
        """
        cap = current_capital or self.capital
        risk_per_trade = self.risk_per_trade

        # Dynamic volatility scaling: reduce risk amount if ATR/Price exceeds baseline (1.5%)
        if atr is not None and entry_price > 0:
            natr = atr / entry_price
            baseline_vol = 0.015
            if natr > baseline_vol:
                scaling_factor = max(baseline_vol / natr, 0.25)
                risk_per_trade = self.risk_per_trade * scaling_factor
                logger.info(
                    f"[{symbol}] High volatility detected (ATR/Price: {natr*100:.2f}%). "
                    f"Scaling risk down to {risk_per_trade*100:.3f}% (factor: {scaling_factor:.2f})."
                )

        risk_amount = cap * risk_per_trade
        price_risk = abs(entry_price - stop_loss)

        if price_risk <= 0:
            logger.warning(f"[{symbol}] Zero price risk; skipping position size.")
            return 0

        qty_by_risk = int(risk_amount / price_risk)

        # Concentration cap
        existing_exposure = self._position_exposure.get(symbol, 0.0)
        max_allowed = cap * self.max_stock_concentration
        remaining_room = max(max_allowed - existing_exposure, 0)
        qty_by_concentration = int(remaining_room / entry_price) if entry_price > 0 else 0

        qty = min(qty_by_risk, qty_by_concentration)

        if qty <= 0:
            logger.warning(
                f"[{symbol}] Position size = 0 "
                f"(risk_qty={qty_by_risk}, conc_qty={qty_by_concentration})."
            )
        return qty

    # ── Can-trade gate ─────────────────────────────────────────────────────────

    def can_trade(self, symbol: Optional[str] = None, active_positions_count: int = 0) -> tuple[bool, str]:
        """
        Returns (allowed: bool, reason: str).
        Pass *symbol* to additionally check concentration.
        """
        self.reset_daily_counters()

        daily_loss_limit = self.capital * self.max_daily_loss
        if self.stats.gross_pnl <= -daily_loss_limit:
            return False, f"Daily loss limit hit (₹{-self.stats.gross_pnl:,.0f} ≥ ₹{daily_loss_limit:,.0f})"

        if self.stats.consecutive_losses >= self.max_consecutive_losses:
            return False, f"Consecutive loss circuit breaker ({self.stats.consecutive_losses} losses)"

        total_trades_initiated = self.stats.trades + active_positions_count
        if total_trades_initiated >= self.max_daily_trades:
            return False, f"Max daily trades reached ({self.max_daily_trades})"

        return True, "OK"

    # ── Record result ──────────────────────────────────────────────────────────

    def record_trade_result(self, symbol: str, pnl: float, qty: int, exit_price: float) -> None:
        """Call this after every closed trade."""
        self.stats.trades += 1
        self.stats.gross_pnl += pnl

        if pnl > 0:
            self.stats.winners += 1
            self.stats.consecutive_losses = 0
        else:
            self.stats.losers += 1
            self.stats.consecutive_losses += 1
            self.stats.max_consecutive_losses = max(
                self.stats.max_consecutive_losses, self.stats.consecutive_losses
            )

        # Remove position exposure
        self._position_exposure.pop(symbol, None)
        logger.info(
            f"[{symbol}] Trade closed | PnL ₹{pnl:+,.2f} | "
            f"Day P&L ₹{self.stats.gross_pnl:+,.2f} | "
            f"Consecutive losses: {self.stats.consecutive_losses}"
        )

    def add_position_exposure(self, symbol: str, value: float) -> None:
        self._position_exposure[symbol] = self._position_exposure.get(symbol, 0.0) + value

    @property
    def summary(self) -> dict:
        return {
            "trades": self.stats.trades,
            "winners": self.stats.winners,
            "losers": self.stats.losers,
            "win_rate": self.stats.win_rate,
            "gross_pnl": self.stats.gross_pnl,
            "consecutive_losses": self.stats.consecutive_losses,
            "drawdown": self.stats.drawdown,
        }
