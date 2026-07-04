"""
core/backtester.py
------------------
Bar-by-bar Backtester with no look-ahead bias.
Computes KPIs: Total Return, CAGR, Sharpe, Max Drawdown, Win Rate, Profit Factor.
Generates Matplotlib equity curve with buy/sell markers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

from core.strategy import FibonacciStrategy, Signal, Direction
from core.orb_strategy import ORBStrategy
from core.vwap_pullback_strategy import VWAPPullbackStrategy
from utils.logger import logger


@dataclass
class BacktestTrade:
    symbol: str
    direction: Direction
    entry_idx: int
    entry_price: float
    stop_loss: float
    target: float
    qty: int
    exit_idx: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0

    @property
    def closed(self) -> bool:
        return self.exit_idx is not None


@dataclass
class BacktestResult:
    symbol: str
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    initial_capital: float = 500_000.0

    # KPIs (computed by Backtester.compute_kpis)
    total_return: float = 0.0
    cagr: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    winners: int = 0
    losers: int = 0


class Backtester:
    def __init__(self, config: dict):
        self.config = config
        strat_cfg = config.get("strategy", {})
        strategy_type = strat_cfg.get("strategy_type", "fibonacci")
        if strategy_type == "orb":
            self.strategy = ORBStrategy(config)
        elif strategy_type == "vwap_pullback":
            self.strategy = VWAPPullbackStrategy(config)
        else:
            self.strategy = FibonacciStrategy(config)
            
        risk = config.get("risk", {})
        self.initial_capital: float = risk.get("capital", 500_000)
        self.risk_per_trade: float = risk.get("risk_per_trade", 0.01)

    # ── Bar-by-bar loop ────────────────────────────────────────────────────────

    def run(self, symbol: str, df: pd.DataFrame) -> BacktestResult:
        result = BacktestResult(symbol=symbol, initial_capital=self.initial_capital)
        capital = self.initial_capital
        
        warmup = self.strategy.warmup_period
        
        # Populate the warmup period with initial capital to align indices
        for _ in range(warmup):
            result.equity_curve.append(capital)
            
        active_trade: Optional[BacktestTrade] = None

        for i in range(warmup, len(df)):
            bar = df.iloc[i]

            # ── Check open trade exit ────────────────────────────────────────
            if active_trade and not active_trade.closed:
                high = bar["high"]
                low = bar["low"]

                if active_trade.direction == Direction.LONG:
                    if low <= active_trade.stop_loss:
                        active_trade.exit_idx = i
                        active_trade.exit_price = active_trade.stop_loss
                        active_trade.exit_reason = "SL"
                    elif high >= active_trade.target:
                        active_trade.exit_idx = i
                        active_trade.exit_price = active_trade.target
                        active_trade.exit_reason = "TARGET"
                else:  # SHORT
                    if high >= active_trade.stop_loss:
                        active_trade.exit_idx = i
                        active_trade.exit_price = active_trade.stop_loss
                        active_trade.exit_reason = "SL"
                    elif low <= active_trade.target:
                        active_trade.exit_idx = i
                        active_trade.exit_price = active_trade.target
                        active_trade.exit_reason = "TARGET"

                if active_trade.closed:
                    mult = 1 if active_trade.direction == Direction.LONG else -1
                    pnl = (active_trade.exit_price - active_trade.entry_price) * active_trade.qty * mult
                    active_trade.pnl = pnl
                    capital += pnl
                    result.trades.append(active_trade)
                    logger.debug(
                        f"[BT {symbol}] Bar {i}: {active_trade.exit_reason} "
                        f"@ ₹{active_trade.exit_price:.2f} PnL ₹{pnl:+.2f}"
                    )
                    active_trade = None

            # ── Look for new signal (only when flat) ─────────────────────────
            if active_trade is None:
                window = df.iloc[:i + 1]   # no future data
                signals = self.strategy.generate_signals(symbol, window)
                if signals:
                    sig = signals[0]
                    risk_amt = capital * self.risk_per_trade
                    price_risk = abs(sig.entry_price - sig.stop_loss)
                    qty = int(risk_amt / price_risk) if price_risk > 0 else 0
                    if qty > 0:
                        active_trade = BacktestTrade(
                            symbol=symbol,
                            direction=sig.direction,
                            entry_idx=i,
                            entry_price=sig.entry_price,
                            stop_loss=sig.stop_loss,
                            target=sig.target,
                            qty=qty,
                        )

            result.equity_curve.append(capital)

        # Force-close any open position at last bar
        if active_trade and not active_trade.closed:
            last_price = df["close"].iloc[-1]
            mult = 1 if active_trade.direction == Direction.LONG else -1
            pnl = (last_price - active_trade.entry_price) * active_trade.qty * mult
            active_trade.exit_idx = len(df) - 1
            active_trade.exit_price = last_price
            active_trade.exit_reason = "EOD"
            active_trade.pnl = pnl
            capital += pnl
            result.trades.append(active_trade)
            
            # Update final equity element with the EOD exit PnL
            result.equity_curve[-1] = capital

        self._compute_kpis(result, df)
        return result

    # ── KPI computation ────────────────────────────────────────────────────────

    def _compute_kpis(self, result: BacktestResult, df: pd.DataFrame) -> None:
        eq = np.array(result.equity_curve)
        initial = result.initial_capital
        final = eq[-1]

        result.total_return = (final - initial) / initial
        result.total_trades = len(result.trades)

        if result.total_trades == 0:
            return

        wins = [t for t in result.trades if t.pnl > 0]
        losses = [t for t in result.trades if t.pnl <= 0]
        result.winners = len(wins)
        result.losers = len(losses)
        result.win_rate = result.winners / result.total_trades

        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        result.profit_factor = gross_profit / gross_loss if gross_loss else float("inf")

        # CAGR – approximate using number of trading days
        n_days = len(df) / 26   # ~26 candles/day at 15min
        years = n_days / 252
        result.cagr = (final / initial) ** (1 / years) - 1 if years > 0 else 0.0

        # Sharpe – daily PnL series
        daily_pnl = pd.Series([t.pnl for t in result.trades])
        if len(daily_pnl) > 1 and daily_pnl.std() > 0:
            result.sharpe = (daily_pnl.mean() / daily_pnl.std()) * math.sqrt(252)
        else:
            result.sharpe = 0.0

        # Max Drawdown
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        result.max_drawdown = float(dd.min())

    # ── Chart ──────────────────────────────────────────────────────────────────

    def plot_equity_curve(self, result: BacktestResult) -> plt.Figure:
        eq = np.array(result.equity_curve)
        xs = np.arange(len(eq))

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(12, 7), gridspec_kw={"height_ratios": [3, 1]}, dpi=100
        )
        fig.patch.set_facecolor("#0f1117")
        for ax in (ax1, ax2):
            ax.set_facecolor("#1a1d2e")
            ax.tick_params(colors="#b0b8cc")
            ax.spines[:].set_color("#2a2d3e")

        # ── Equity line ────────────────────────────────────────────────────
        ax1.plot(xs, eq, color="#4fc3f7", linewidth=1.5, zorder=3)
        ax1.fill_between(xs, result.initial_capital, eq,
                         where=eq >= result.initial_capital, alpha=0.15, color="#00e676")
        ax1.fill_between(xs, result.initial_capital, eq,
                         where=eq < result.initial_capital, alpha=0.15, color="#ef5350")

        # Max drawdown highlight
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        dd_end = int(dd.argmin())
        dd_start = int(np.argmax(peak[:dd_end + 1]))
        ax1.axvspan(dd_start, dd_end, alpha=0.12, color="#ef5350", label="Max Drawdown")

        # Entry/exit markers
        for t in result.trades:
            color = "#00e676" if t.pnl > 0 else "#ef5350"
            marker = "^" if t.direction == Direction.LONG else "v"
            ax1.scatter(t.entry_idx, eq[t.entry_idx], color=color, marker=marker, s=60, zorder=5)
            if t.exit_idx is not None and t.exit_idx < len(eq):
                ax1.scatter(t.exit_idx, eq[t.exit_idx], color=color, marker="x", s=60, zorder=5)

        ax1.axhline(result.initial_capital, color="#555", linestyle="--", linewidth=0.8)
        ax1.set_title(
            f"{result.symbol} – Equity Curve  |  Return {result.total_return:.1%}  "
            f"|  Sharpe {result.sharpe:.2f}  |  MaxDD {result.max_drawdown:.1%}",
            color="#e0e6f0", fontsize=11,
        )
        ax1.set_ylabel("Portfolio Value (₹)", color="#b0b8cc")

        # ── Drawdown pane ──────────────────────────────────────────────────
        ax2.fill_between(xs, 0, dd * 100, color="#ef5350", alpha=0.5)
        ax2.set_ylabel("DD %", color="#b0b8cc")
        ax2.set_ylim(dd.min() * 100 * 1.1, 2)

        # Legend
        patches = [
            mpatches.Patch(color="#00e676", label="Winner"),
            mpatches.Patch(color="#ef5350", label="Loser / MaxDD"),
        ]
        ax1.legend(handles=patches, facecolor="#1a1d2e", edgecolor="#2a2d3e",
                   labelcolor="#b0b8cc", fontsize=8)

        plt.tight_layout()
        return fig
