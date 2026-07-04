"""
core/order_executor.py
-----------------------
OrderExecutor: places, tracks, and squares off positions.
  • Paper mode  – tracks everything in memory
  • Live mode   – calls Angel One SmartAPI (LIMIT orders with 0.1% buffer)

Auto-squareoff at 3:15 PM IST is enforced inside update_positions_pnl().
"""
from __future__ import annotations

import uuid
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from config.settings import settings
from core.strategy import Direction, Signal
from utils.logger import logger
from utils.helpers import now_ist, is_after_squareoff
from src.data.angel_connector import connector
from src.utils.rate_limiter import broker_limiters


@dataclass
class Position:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    symbol: str = ""
    direction: Direction = Direction.LONG
    qty: int = 0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0
    ltp: float = 0.0
    pnl: float = 0.0
    entry_time: datetime = field(default_factory=now_ist)
    status: str = "OPEN"   # OPEN | CLOSED_SL | CLOSED_TARGET | CLOSED_SQUAREOFF

    def update_pnl(self, ltp: float) -> None:
        self.ltp = ltp
        multiplier = 1 if self.direction == Direction.LONG else -1
        self.pnl = round((ltp - self.entry_price) * self.qty * multiplier, 2)


class OrderExecutor:
    def __init__(self, smart=None):
        self._positions: Dict[str, Position] = {}
        self._trade_log: List[dict] = []

    def _place_order_live(self, params: dict) -> dict:
        broker_limiters.get("orders").acquire("Place Order Live API")
        return connector.smart.placeOrder(params)

    def _cancel_order_live(self, variety: str, order_id: str) -> dict:
        broker_limiters.get("orders").acquire("Cancel Order Live API")
        return connector.smart.cancelOrder(variety=variety, orderid=order_id)

    def _get_order_book_live(self) -> dict:
        broker_limiters.get("orders").acquire("Order Book Live API")
        return connector.smart.orderBook()

    # ── Entry ──────────────────────────────────────────────────────────────────

    def execute_entry(self, signal: Signal, qty: int) -> Optional[Position]:
        if qty <= 0:
            logger.warning(f"[{signal.symbol}] Skipping entry – qty=0.")
            return None

        pos = Position(
            symbol=signal.symbol,
            direction=signal.direction,
            qty=qty,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            target=signal.target,
            ltp=signal.entry_price,
            entry_time=now_ist(),
        )

        if settings.is_live and connector.smart is not None:
            try:
                token, trading_symbol = connector.get_token_info(signal.symbol)
                if not token:
                    raise ValueError(f"Token not found for {signal.symbol}")

                transaction = "BUY" if signal.direction == Direction.LONG else "SELL"
                
                # LIMIT order buffer rules: buy slightly above LTP, sell slightly below LTP to ensure fill
                if signal.direction == Direction.LONG:
                    limit_price = round(signal.entry_price * 1.001, 2)
                else:
                    limit_price = round(signal.entry_price * 0.999, 2)

                logger.info(f"[{signal.symbol}] Placing live Angel One LIMIT entry order: {transaction} {qty} shares @ ₹{limit_price}")
                params = {
                    "variety": "NORMAL",
                    "tradingsymbol": trading_symbol,
                    "symboltoken": token,
                    "transactiontype": transaction,
                    "exchange": "NSE",
                    "ordertype": "LIMIT",
                    "producttype": "INTRADAY",
                    "duration": "DAY",
                    "price": limit_price,
                    "quantity": qty
                }
                
                response = self._place_order_live(params)
                if response.get("status") is True:
                    order_id = response["data"]["orderid"]
                    logger.success(f"[{signal.symbol}] Live ENTRY order placed. ID={order_id}")
                    self._place_sl_order(signal, qty, token, trading_symbol)
                    self._place_target_order(signal, qty, token, trading_symbol)
                else:
                    raise ValueError(response.get("message", "Order rejected by exchange"))
            except Exception as exc:
                logger.error(f"[{signal.symbol}] Live order failed: {exc}")
                return None
        else:
            logger.info(
                f"[PAPER] {signal.direction} {qty}×{signal.symbol} "
                f"@ ₹{signal.entry_price} | SL ₹{signal.stop_loss} | TGT ₹{signal.target}"
            )

        self._positions[pos.id] = pos
        return pos

    # ── SL / Target orders (live) ──────────────────────────────────────────────

    def _place_sl_order(self, signal: Signal, qty: int, token: str, trading_symbol: str) -> None:
        if not (settings.is_live and connector.smart is not None):
            return
        try:
            # SL is placed in opposite direction
            transaction = "SELL" if signal.direction == Direction.LONG else "BUY"
            
            # SL limit price offset to avoid execution skip
            if signal.direction == Direction.LONG:
                limit_price = round(signal.stop_loss * 0.999, 2)
            else:
                limit_price = round(signal.stop_loss * 1.001, 2)

            logger.info(f"[{signal.symbol}] Placing live Angel One STOPLOSS order: {transaction} {qty} shares @ ₹{limit_price} (Trigger: ₹{signal.stop_loss})")
            params = {
                "variety": "STOPLOSS",
                "tradingsymbol": trading_symbol,
                "symboltoken": token,
                "transactiontype": transaction,
                "exchange": "NSE",
                "ordertype": "STOPLOSS_LIMIT",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "triggerprice": round(signal.stop_loss, 2),
                "price": limit_price,
                "quantity": qty
            }
            self._place_order_live(params)
        except Exception as exc:
            logger.error(f"[{signal.symbol}] SL order placement failed: {exc}")

    def _place_target_order(self, signal: Signal, qty: int, token: str, trading_symbol: str) -> None:
        if not (settings.is_live and connector.smart is not None):
            return
        try:
            transaction = "SELL" if signal.direction == Direction.LONG else "BUY"
            logger.info(f"[{signal.symbol}] Placing live Angel One Target LIMIT order: {transaction} {qty} shares @ ₹{signal.target}")
            params = {
                "variety": "NORMAL",
                "tradingsymbol": trading_symbol,
                "symboltoken": token,
                "transactiontype": transaction,
                "exchange": "NSE",
                "ordertype": "LIMIT",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "price": round(signal.target, 2),
                "quantity": qty
            }
            self._place_order_live(params)
        except Exception as exc:
            logger.error(f"[{signal.symbol}] Target order placement failed: {exc}")

    def _log_closed_trade(self, pos: Position, exit_price: float) -> None:
        """Append closed trade details to logs/trade_history.csv."""
        import os
        import csv
        from utils.helpers import now_ist
        
        file_path = "logs/trade_history.csv"
        os.makedirs("logs", exist_ok=True)
        
        file_exists = os.path.exists(file_path)
        
        row = {
            "timestamp": now_ist().strftime("%Y-%m-%d %H:%M:%S"),
            "id": pos.id,
            "symbol": pos.symbol,
            "direction": pos.direction.value,
            "qty": pos.qty,
            "entry_price": round(pos.entry_price, 2),
            "exit_price": round(exit_price, 2),
            "pnl": round(pos.pnl, 2),
            "exit_reason": pos.status,
            "entry_time": pos.entry_time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        try:
            with open(file_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(row.keys()))
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
        except Exception as e:
            logger.error(f"Failed to log trade to CSV: {e}")

    # ── PnL updater ────────────────────────────────────────────────────────────

    def update_positions_pnl(self, ltp_map: Dict[str, float]) -> List[dict]:
        """
        Call this on every refresh cycle.
        Returns list of closed-trade dicts for RiskManager.
        """
        closed: List[dict] = []
        squareoff = is_after_squareoff()

        for pos_id, pos in list(self._positions.items()):
            if pos.status != "OPEN":
                continue

            ltp = ltp_map.get(pos.symbol)
            if ltp is None:
                continue

            pos.update_pnl(ltp)

            if squareoff:
                pos.status = "CLOSED_SQUAREOFF"
                logger.warning(f"[{pos.symbol}] Auto-squareoff at 3:15 PM. PnL ₹{pos.pnl:+,.2f}")
                self._log_closed_trade(pos, ltp)
                closed.append({"symbol": pos.symbol, "pnl": pos.pnl, "qty": pos.qty, "exit_price": ltp})
                continue

            if pos.direction == Direction.LONG:
                if ltp <= pos.stop_loss:
                    pos.status = "CLOSED_SL"
                    logger.warning(f"[{pos.symbol}] SL hit @ ₹{ltp}. PnL ₹{pos.pnl:+,.2f}")
                    self._log_closed_trade(pos, ltp)
                    closed.append({"symbol": pos.symbol, "pnl": pos.pnl, "qty": pos.qty, "exit_price": ltp})
                elif ltp >= pos.target:
                    pos.status = "CLOSED_TARGET"
                    logger.success(f"[{pos.symbol}] Target hit @ ₹{ltp}. PnL ₹{pos.pnl:+,.2f}")
                    self._log_closed_trade(pos, ltp)
                    closed.append({"symbol": pos.symbol, "pnl": pos.pnl, "qty": pos.qty, "exit_price": ltp})
            else:  # SHORT
                if ltp >= pos.stop_loss:
                    pos.status = "CLOSED_SL"
                    logger.warning(f"[{pos.symbol}] SL hit @ ₹{ltp}. PnL ₹{pos.pnl:+,.2f}")
                    self._log_closed_trade(pos, ltp)
                    closed.append({"symbol": pos.symbol, "pnl": pos.pnl, "qty": pos.qty, "exit_price": ltp})
                elif ltp <= pos.target:
                    pos.status = "CLOSED_TARGET"
                    logger.success(f"[{pos.symbol}] Target hit @ ₹{ltp}. PnL ₹{pos.pnl:+,.2f}")
                    self._log_closed_trade(pos, ltp)
                    closed.append({"symbol": pos.symbol, "pnl": pos.pnl, "qty": pos.qty, "exit_price": ltp})

        return closed

    def squareoff_position(self, pos_id: str, exit_price: float) -> Optional[Position]:
        """Manually square off an open position and log it to CSV."""
        pos = self._positions.get(pos_id)
        if pos and pos.status == "OPEN":
            if settings.is_live and connector.smart is not None:
                try:
                    token, trading_symbol = connector.get_token_info(pos.symbol)
                    transaction = "SELL" if pos.direction == Direction.LONG else "BUY"
                    
                    # For manual exit, place a Limit order slightly below/above LTP to ensure quick fill
                    if pos.direction == Direction.LONG:
                        limit_price = round(exit_price * 0.999, 2)
                    else:
                        limit_price = round(exit_price * 1.001, 2)
                        
                    logger.warning(f"[{pos.symbol}] Placing live Angel One manual exit order: {transaction} {pos.qty} @ ₹{limit_price}")
                    params = {
                        "variety": "NORMAL",
                        "tradingsymbol": trading_symbol,
                        "symboltoken": token,
                        "transactiontype": transaction,
                        "exchange": "NSE",
                        "ordertype": "LIMIT",
                        "producttype": "INTRADAY",
                        "duration": "DAY",
                        "price": limit_price,
                        "quantity": pos.qty
                    }
                    self._place_order_live(params)
                except Exception as exc:
                    logger.error(f"[{pos.symbol}] Live squareoff order failed: {exc}")
                    
            pos.status = "CLOSED_SQUAREOFF"
            pos.update_pnl(exit_price)
            self._log_closed_trade(pos, exit_price)
            return pos
        return None

    def panic_close_all(self, data_fetcher=None) -> int:
        """Cancel all pending orders and close all open positions at market price."""
        closed_count = 0
        
        # 1. Live mode cancellations & closures
        if settings.is_live and connector.smart is not None:
            try:
                # Cancel all pending/open orders
                book_res = self._get_order_book_live()
                if book_res.get("status") is True and "data" in book_res:
                    for order in book_res["data"]:
                        if order.get("status") in ["open", "validation pending", "trigger pending"]:
                            order_id = order.get("orderid")
                            variety = order.get("variety", "NORMAL")
                            self._cancel_order_live(variety=variety, order_id=order_id)
                            logger.warning(f"Live order cancelled: ID={order_id}")
            except Exception as exc:
                logger.error(f"Live panic order cancellation failed: {exc}")
        
        # 2. Close all open positions at current LTP
        for pos in list(self.open_positions):
            exit_price = pos.ltp
            if data_fetcher:
                try:
                    exit_price = data_fetcher.get_ltp(pos.symbol)
                except Exception:
                    pass
            
            if settings.is_live and connector.smart is not None:
                try:
                    token, trading_symbol = connector.get_token_info(pos.symbol)
                    transaction = "SELL" if pos.direction == Direction.LONG else "BUY"
                    
                    if pos.direction == Direction.LONG:
                        limit_price = round(exit_price * 0.999, 2)
                    else:
                        limit_price = round(exit_price * 1.001, 2)

                    logger.warning(f"[{pos.symbol}] Placing live panic squareoff order: {transaction} {pos.qty} @ ₹{limit_price}")
                    params = {
                        "variety": "NORMAL",
                        "tradingsymbol": trading_symbol,
                        "symboltoken": token,
                        "transactiontype": transaction,
                        "exchange": "NSE",
                        "ordertype": "LIMIT",
                        "producttype": "INTRADAY",
                        "duration": "DAY",
                        "price": limit_price,
                        "quantity": pos.qty
                    }
                    self._place_order_live(params)
                except Exception as exc:
                    logger.error(f"[{pos.symbol}] Live panic squareoff order failed: {exc}")
                    
            pos.status = "CLOSED_SQUAREOFF"
            pos.update_pnl(exit_price)
            self._log_closed_trade(pos, exit_price)
            closed_count += 1
            
        return closed_count

    # ── Accessors ──────────────────────────────────────────────────────────────

    @property
    def open_positions(self) -> List[Position]:
        return [p for p in self._positions.values() if p.status == "OPEN"]

    @property
    def all_positions(self) -> List[Position]:
        return list(self._positions.values())

    @property
    def total_open_pnl(self) -> float:
        return sum(p.pnl for p in self.open_positions)
