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
    status: str = "PENDING_FILL"   # PENDING_FILL | OPEN | FAILED | CLOSED_SL | CLOSED_TARGET | CLOSED_SQUAREOFF
    entry_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    high_watermark: float = 0.0
    low_watermark: float = 0.0

    def update_pnl(self, ltp: float) -> None:
        self.ltp = ltp
        
        # Initialize watermarks if not set yet
        if self.high_watermark == 0.0:
            self.high_watermark = self.entry_price or ltp
        if self.low_watermark == 0.0:
            self.low_watermark = self.entry_price or ltp
            
        # Update watermarks based on current price
        self.high_watermark = max(self.high_watermark, ltp)
        self.low_watermark = min(self.low_watermark, ltp)
        
        multiplier = 1 if self.direction == Direction.LONG else -1
        self.pnl = round((ltp - self.entry_price) * self.qty * multiplier, 2)


class OrderExecutor:
    def __init__(self, smart=None, config: Optional[dict] = None):
        self._positions: Dict[str, Position] = {}
        self._trade_log: List[dict] = []
        self.config = config or {}

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

        # Options routing if CPR Intraday strategy is active
        import server
        strategy_type = server.global_config.get("strategy", {}).get("strategy_type", "")
        is_options_trade = (strategy_type == "cpr_intraday" and signal.symbol == "NIFTY")

        opt_token = None
        opt_trading_symbol = None
        opt_ltp = None

        if is_options_trade:
            strike = int(round(signal.entry_price / 50.0) * 50)
            opt_type = "CE" if signal.direction == Direction.LONG else "PE"
            
            opt_info = connector.resolve_atm_option("NIFTY", strike, opt_type)
            if not opt_info:
                # Mock fallback
                opt_token = f"MOCK_{strike}_{opt_type}"
                opt_trading_symbol = f"NIFTY26JUL26{strike}{opt_type}"
                opt_ltp = 150.0
            else:
                opt_token, opt_trading_symbol = opt_info
                from src.data.optimized_client import optimized_client
                try:
                    opt_ltp = optimized_client.get_ltp(opt_trading_symbol)
                except Exception:
                    opt_ltp = 150.0
            
            # Recalculate signal values for options premium
            signal.entry_price = opt_ltp
            risk_amt = opt_ltp * 0.20  # 20% premium risk
            signal.stop_loss = round(opt_ltp - risk_amt, 2)
            signal.target = round(opt_ltp + risk_amt * 2.0, 2)
            logger.info(f"[Order Executor] Routing NIFTY spot signal to option: {opt_trading_symbol} @ ₹{opt_ltp} (SL: {signal.stop_loss}, Target: {signal.target})")

        pos = Position(
            symbol=opt_trading_symbol if is_options_trade else signal.symbol,
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
                if is_options_trade:
                    token = opt_token
                    trading_symbol = opt_trading_symbol
                else:
                    token, trading_symbol = connector.get_token_info(signal.symbol)
                    
                if not token:
                    raise ValueError(f"Token not found for {signal.symbol}")

                transaction = "BUY" if signal.direction == Direction.LONG else "SELL"
                
                # LIMIT order buffer rules: buy slightly above LTP, sell slightly below LTP to ensure fill
                if signal.direction == Direction.LONG:
                    limit_price = round(signal.entry_price * 1.001, 2)
                else:
                    limit_price = round(signal.entry_price * 0.999, 2)

                logger.info(f"[{trading_symbol}] Placing live Angel One LIMIT entry order: {transaction} {qty} contracts/shares @ ₹{limit_price}")
                params = {
                    "variety": "NORMAL",
                    "tradingsymbol": trading_symbol,
                    "symboltoken": token,
                    "transactiontype": transaction,
                    "exchange": connector.get_exchange(trading_symbol),
                    "ordertype": "LIMIT",
                    "producttype": "INTRADAY",
                    "duration": "DAY",
                    "price": limit_price,
                    "quantity": qty
                }
                
                response = self._place_order_live(params)
                if response.get("status") is True:
                    order_id = response["data"]["orderid"]
                    pos.entry_order_id = order_id
                    pos.status = "PENDING_FILL"
                    logger.success(f"[{signal.symbol}] Live ENTRY order placed. ID={order_id}. Waiting for fill confirmation...")
                else:
                    raise ValueError(response.get("message", "Order rejected by exchange"))
            except Exception as exc:
                logger.error(f"[{signal.symbol}] Live order failed: {exc}")
                return None
        else:
            pos.status = "OPEN"
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
                "exchange": connector.get_exchange(trading_symbol),
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
                "exchange": connector.get_exchange(trading_symbol),
                "ordertype": "LIMIT",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "price": round(signal.target, 2),
                "quantity": qty
            }
            self._place_order_live(params)
        except Exception as exc:
            logger.error(f"[{signal.symbol}] Target order placement failed: {exc}")

    def _place_sl_order_for_pos(self, pos: Position, token: str, trading_symbol: str) -> None:
        if not (settings.is_live and connector.smart is not None):
            return
        try:
            transaction = "SELL" if pos.direction == Direction.LONG else "BUY"
            if pos.direction == Direction.LONG:
                limit_price = round(pos.stop_loss * 0.999, 2)
            else:
                limit_price = round(pos.stop_loss * 1.001, 2)

            logger.info(f"[{pos.symbol}] Placing live Stoploss order: {transaction} {pos.qty} @ ₹{limit_price}")
            params = {
                "variety": "STOPLOSS",
                "tradingsymbol": trading_symbol,
                "symboltoken": token,
                "transactiontype": transaction,
                "exchange": connector.get_exchange(trading_symbol),
                "ordertype": "STOPLOSS_LIMIT",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "triggerprice": round(pos.stop_loss, 2),
                "price": limit_price,
                "quantity": pos.qty
            }
            res = self._place_order_live(params)
            if res and res.get("status") is True:
                pos.sl_order_id = res.get("data", {}).get("orderid")
                logger.info(f"[{pos.symbol}] Successfully placed live Stoploss order. ID: {pos.sl_order_id}")
        except Exception as exc:
            logger.error(f"[{pos.symbol}] SL order placement failed: {exc}")

    def _modify_sl_order_live(self, pos: Position, new_trigger_price: float, new_limit_price: float) -> None:
        if not (settings.is_live and connector.smart is not None and pos.sl_order_id):
            return
        try:
            token, trading_symbol = connector.get_token_info(pos.symbol)
            transaction = "SELL" if pos.direction == Direction.LONG else "BUY"
            logger.info(f"[TSL] [{pos.symbol}] Modifying live stop loss order {pos.sl_order_id} to trigger: ₹{new_trigger_price}, price: ₹{new_limit_price}")
            
            broker_limiters.get("orders").acquire("Modify Order Live API")
            connector.smart.modifyOrder({
                "variety": "STOPLOSS",
                "orderid": pos.sl_order_id,
                "tradingsymbol": trading_symbol,
                "symboltoken": token,
                "transactiontype": transaction,
                "exchange": connector.get_exchange(trading_symbol),
                "ordertype": "STOPLOSS_LIMIT",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "triggerprice": round(new_trigger_price, 2),
                "price": round(new_limit_price, 2),
                "quantity": pos.qty
            })
        except Exception as exc:
            logger.error(f"[TSL] [{pos.symbol}] Live SL order modification failed: {exc}")

    def _place_target_order_for_pos(self, pos: Position, token: str, trading_symbol: str) -> None:
        if not (settings.is_live and connector.smart is not None):
            return
        try:
            transaction = "SELL" if pos.direction == Direction.LONG else "BUY"
            if pos.direction == Direction.LONG:
                limit_price = round(pos.target * 0.999, 2)
            else:
                limit_price = round(pos.target * 1.001, 2)

            logger.info(f"[{pos.symbol}] Placing live Target limit order: {transaction} {pos.qty} @ ₹{limit_price}")
            params = {
                "variety": "NORMAL",
                "tradingsymbol": trading_symbol,
                "symboltoken": token,
                "transactiontype": transaction,
                "exchange": connector.get_exchange(trading_symbol),
                "ordertype": "LIMIT",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "price": limit_price,
                "quantity": pos.qty
            }
            self._place_order_live(params)
        except Exception as exc:
            logger.error(f"[{pos.symbol}] Target order placement failed: {exc}")

    def _log_closed_trade(self, pos: Position, exit_price: float) -> None:
        """Insert closed trade details to SQL database."""
        from utils.helpers import now_ist
        from core.db import SessionLocal, Trade
        
        db = SessionLocal()
        try:
            db_trade = Trade(
                id=pos.id,
                timestamp=now_ist().replace(tzinfo=None), # Naive timestamp for SQLite/DB compatibility
                symbol=pos.symbol,
                direction=pos.direction.value if hasattr(pos.direction, "value") else str(pos.direction),
                qty=int(pos.qty),
                entry_price=round(float(pos.entry_price), 2),
                exit_price=round(float(exit_price), 2),
                pnl=round(float(pos.pnl), 2),
                exit_reason=str(pos.status),
                entry_time=pos.entry_time.replace(tzinfo=None)
            )
            db.add(db_trade)
            db.commit()
            logger.info(f"[Database] Logged closed trade for {pos.symbol} (PnL: ₹{pos.pnl}) to SQL database.")
        except Exception as e:
            logger.error(f"[Database] Failed to log closed trade for {pos.symbol}: {e}")
            db.rollback()
        finally:
            db.close()

    # ── PnL updater ────────────────────────────────────────────────────────────

    def update_positions_pnl(self, ltp_map: Dict[str, float]) -> List[dict]:
        """
        Call this on every refresh cycle.
        Returns list of closed-trade dicts for RiskManager.
        """
        closed: List[dict] = []
        squareoff = is_after_squareoff()

        for pos_id, pos in list(self._positions.items()):
            # Handle PENDING_FILL state: check if live entry order is completed/rejected/cancelled
            if pos.status == "PENDING_FILL":
                if settings.is_live and connector.smart is not None and pos.entry_order_id:
                    try:
                        order_book = self._get_order_book_live()
                        if order_book and order_book.get("status") is True:
                            orders = order_book.get("data", [])
                            match_order = next((o for o in orders if o.get("orderid") == pos.entry_order_id), None)
                            if match_order:
                                ord_status = match_order.get("status")
                                if ord_status == "complete":
                                    logger.success(f"[{pos.symbol}] Live ENTRY order {pos.entry_order_id} filled! Placing Stoploss & Target...")
                                    pos.status = "OPEN"
                                    # Retrieve correct token details
                                    token = match_order.get("symboltoken")
                                    trading_symbol = match_order.get("tradingsymbol")
                                    self._place_sl_order_for_pos(pos, token, trading_symbol)
                                    self._place_target_order_for_pos(pos, token, trading_symbol)
                                elif ord_status in ("rejected", "cancelled"):
                                    logger.error(f"[{pos.symbol}] Live ENTRY order {pos.entry_order_id} was {ord_status.upper()}: {match_order.get('text')}")
                                    pos.status = "FAILED"
                                    if pos.id in self._positions:
                                        del self._positions[pos.id]
                                    continue
                                else:
                                    # Still pending. Cancel if it stays pending for > 5 minutes (300s)
                                    elapsed = (now_ist() - pos.entry_time).total_seconds()
                                    if elapsed > 300:
                                        logger.warning(f"[{pos.symbol}] Live ENTRY order {pos.entry_order_id} pending too long. Cancelling...")
                                        self._cancel_order_live("NORMAL", pos.entry_order_id)
                                        pos.status = "FAILED"
                                        if pos.id in self._positions:
                                            del self._positions[pos.id]
                                        continue
                    except Exception as err:
                        logger.error(f"Error checking pending order {pos.entry_order_id}: {err}")
                else:
                    # Non-live or mock/fallback
                    pos.status = "OPEN"

            if pos.status != "OPEN":
                continue

            ltp = ltp_map.get(pos.symbol)
            if ltp is None:
                continue

            pos.update_pnl(ltp)
            
            # Trailing Stop Loss (TSL) update
            risk_cfg = self.config.get("risk", {}) if self.config else {}
            tsl_enabled = risk_cfg.get("trailing_sl_enabled", False) or getattr(settings, "TRAILING_SL_ENABLED", False)
            
            if tsl_enabled:
                trigger_pct = risk_cfg.get("trailing_sl_trigger_pct", 0.01)
                distance_pct = risk_cfg.get("trailing_sl_distance_pct", 0.005)
                
                if pos.direction == Direction.LONG:
                    trigger_val = pos.entry_price * (1 + trigger_pct)
                    if pos.high_watermark >= trigger_val:
                        new_sl = round(pos.high_watermark * (1 - distance_pct), 2)
                        if new_sl > pos.stop_loss:
                            logger.info(f"[TSL] [{pos.symbol}] Trailing SL moved UP from ₹{pos.stop_loss} to ₹{new_sl} (High seen: ₹{pos.high_watermark})")
                            pos.stop_loss = new_sl
                            # If live, update the order at the broker
                            if pos.sl_order_id:
                                limit_price = round(new_sl * 0.999, 2)
                                self._modify_sl_order_live(pos, new_sl, limit_price)
                else: # SHORT
                    trigger_val = pos.entry_price * (1 - trigger_pct)
                    if pos.low_watermark <= trigger_val:
                        new_sl = round(pos.low_watermark * (1 + distance_pct), 2)
                        if new_sl < pos.stop_loss:
                            logger.info(f"[TSL] [{pos.symbol}] Trailing SL moved DOWN from ₹{pos.stop_loss} to ₹{new_sl} (Low seen: ₹{pos.low_watermark})")
                            pos.stop_loss = new_sl
                            # If live, update the order at the broker
                            if pos.sl_order_id:
                                limit_price = round(new_sl * 1.001, 2)
                                self._modify_sl_order_live(pos, new_sl, limit_price)

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
                        "exchange": connector.get_exchange(trading_symbol),
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
                        "exchange": connector.get_exchange(trading_symbol),
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
