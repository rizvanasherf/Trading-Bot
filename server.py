"""
server.py
---------
FastAPI backend server for the Fibonacci Retracement Automated Trading Bot.
Manages the real-time scanning thread, order execution, configuration, and serves APIs to the React frontend.
"""

import os
import sys
import yaml
import asyncio
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Inject local path if necessary
sys.path.append(str(Path(__file__).parent))

from config.settings import settings
from src.data.angel_connector import connector
from src.data.optimized_client import optimized_client
from core.data_fetcher import KiteDataFetcher
from core.strategy import FibonacciStrategy, Direction
from core.orb_strategy import ORBStrategy
from core.vwap_pullback_strategy import VWAPPullbackStrategy
from core.risk_manager import RiskManager
from core.order_executor import OrderExecutor, Position
from core.backtester import Backtester
from utils.logger import logger
from utils.helpers import fmt_inr, now_ist, is_after_squareoff, IdempotencyTracker

signal_tracker = IdempotencyTracker()

app = FastAPI(title="Fib Trader Backend API")

# Configure CORS for React frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local development simplicity
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_PATH = Path("config/config.yaml")

# Global instances
global_config = {}
data_fetcher: Optional[KiteDataFetcher] = None
strategy: Optional[FibonacciStrategy] = None
secondary_strategy: Optional[FibonacciStrategy] = None
risk_manager: Optional[RiskManager] = None
order_executor: Optional[OrderExecutor] = None

# Scanner control variables
scanning_active = False
scanner_thread: Optional[threading.Thread] = None
scanner_stop_event = threading.Event()
latest_cpr_data = None

def load_yaml_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_yaml_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False)

def init_trading_components():
    global global_config, data_fetcher, strategy, secondary_strategy, risk_manager, order_executor
    
    # Reload settings singleton to fetch any updated .env variables
    new_settings = settings.__class__()
    fields = settings.model_fields.keys() if hasattr(settings, "model_fields") else settings.__fields__.keys()
    for field_name in fields:
        setattr(settings, field_name, getattr(new_settings, field_name))
        
    global_config = load_yaml_config()
    
    # Re-trigger connection with new settings
    connector.connect()
    
    data_fetcher = KiteDataFetcher()
    strat_cfg = global_config.get("strategy", {})
    strategy_type = strat_cfg.get("strategy_type", "fibonacci")
    secondary_strategy_type = strat_cfg.get("secondary_strategy_type", "none")
    
    if strategy_type == "orb":
        strategy = ORBStrategy(global_config)
    elif strategy_type == "vwap_pullback":
        strategy = VWAPPullbackStrategy(global_config)
    elif strategy_type == "cpr_intraday":
        from core.cpr_strategy import CPRIntradayStrategy
        strategy = CPRIntradayStrategy(global_config)
    else:
        strategy = FibonacciStrategy(global_config)
        
    if strategy_type == "cpr_intraday" and secondary_strategy_type != "none":
        if secondary_strategy_type == "orb":
            secondary_strategy = ORBStrategy(global_config)
        elif secondary_strategy_type == "vwap_pullback":
            secondary_strategy = VWAPPullbackStrategy(global_config)
        elif secondary_strategy_type == "fibonacci":
            secondary_strategy = FibonacciStrategy(global_config)
        else:
            secondary_strategy = None
    else:
        secondary_strategy = None
    
    capital_val = (
        data_fetcher.get_account_balance().get("available", 100_000)
        if settings.is_live
        else global_config.get("risk", {}).get("capital", 100_000)
    )
    
    risk_manager = RiskManager(global_config, capital=capital_val)
    order_executor = OrderExecutor()
    logger.info("Core trading components initialized successfully.")

# Initial core setup
init_trading_components()

# ── Background Scanning Loop ──────────────────────────────────────────────────

def run_scanning_loop():
    global scanning_active
    logger.info("Background scanning loop started.")
    
    from concurrent.futures import ThreadPoolExecutor

    while not scanner_stop_event.is_set():
        if not scanning_active:
            scanner_stop_event.wait(timeout=1.0)
            continue
            
        try:
            # 1. Reset daily counters
            risk_manager.reset_daily_counters()
            
            # 2. Check daily circuit breakers
            allowed, reason = risk_manager.can_trade(active_positions_count=len(order_executor.open_positions))
            if not allowed:
                logger.warning(f"Scanner halted: {reason}")
                scanning_active = False
                continue
                
            # 3. Fetch configurations
            strategy_type = global_config["strategy"].get("strategy_type", "fibonacci")
            secondary_strategy_type = global_config["strategy"].get("secondary_strategy_type", "none")
            
            scan_tasks = []
            if strategy_type == "cpr_intraday":
                scan_tasks.append(("NIFTY", "5minute", strategy))
                if secondary_strategy_type != "none" and secondary_strategy is not None:
                    stock_symbols = global_config["strategy"].get("symbols", [])
                    stock_timeframe = global_config["strategy"].get("timeframe", "15minute")
                    for sym in stock_symbols:
                        if sym != "NIFTY":
                            scan_tasks.append((sym, stock_timeframe, secondary_strategy))
            else:
                stock_symbols = global_config["strategy"].get("symbols", [])
                stock_timeframe = global_config["strategy"].get("timeframe", "15minute")
                for sym in stock_symbols:
                    scan_tasks.append((sym, stock_timeframe, strategy))
            
            # Fetch data concurrently for all scan tasks
            def fetch_task_data(task):
                sym, tf, strat_inst = task
                try:
                    ltp = data_fetcher.get_ltp(sym)
                    df_hist = data_fetcher.get_historical_data(sym, interval=tf, days=5)
                    return sym, ltp, df_hist, strat_inst
                except Exception as e:
                    logger.error(f"Error fetching data for concurrent scan on {sym}: {e}")
                    return sym, None, None, None

            with ThreadPoolExecutor(max_workers=min(len(scan_tasks), 15)) as executor:
                fetch_results = list(executor.map(fetch_task_data, scan_tasks))

            ltps = {}
            for sym, ltp, df_hist, strat_inst in fetch_results:
                if ltp is None or df_hist is None or df_hist.empty or strat_inst is None:
                    continue
                ltps[sym] = ltp
                
                try:
                    # Check circuit breakers for specific stock
                    can_tr, _ = risk_manager.can_trade(sym, active_positions_count=len(order_executor.open_positions))
                    if not can_tr:
                        continue
                        
                    # Evaluate strategy signals
                    signals = strat_inst.generate_signals(sym, df_hist)
                    if signals:
                        sig = signals[0]
                        open_syms = [p.symbol for p in order_executor.open_positions]
                        
                        if sym not in open_syms:
                            # Volatility-adjusted sizing
                            atr_val = None
                            try:
                                atr_series = strat_inst._atr(df_hist)
                                if not atr_series.empty:
                                    atr_val = float(atr_series.iloc[-1])
                            except Exception as ex:
                                logger.error(f"Error calculating ATR for sizing: {ex}")
                            
                            qty = risk_manager.calculate_position_size(sym, sig.entry_price, sig.stop_loss, atr=atr_val)
                            if qty > 0:
                                # Idempotency deduplication check
                                date_str = sig.timestamp.strftime("%Y-%m-%d")
                                if not signal_tracker.check_and_add(sym, sig.direction.value, date_str):
                                    logger.info(f"[{sym}] Signal for {sig.direction.value} already executed today. Skipping double placement.")
                                    continue
                                
                                pos = order_executor.execute_entry(sig, qty)
                                if pos:
                                    risk_manager.add_position_exposure(sym, qty * sig.entry_price)
                                    logger.info(f"[{sym}] Target entry filled. {qty} shares @ {sig.entry_price}")
                except Exception as e:
                    logger.error(f"Error scanning symbol {sym} strategy: {e}")

            # If active strategy is cpr_intraday, update the global cpr_data from the scan result
            if strategy_type == "cpr_intraday" and strategy is not None:
                nifty_res = next((res for res in fetch_results if res[0] == "NIFTY"), None)
                if nifty_res and nifty_res[2] is not None and not nifty_res[2].empty:
                    try:
                        sym, ltp, df, _ = nifty_res
                        cpr_vals = strategy.calculate_cpr("NIFTY")
                        if cpr_vals:
                            pivot, tc, bc = cpr_vals
                            latest_close = float(df["close"].iloc[-1])
                            vwap_series = strategy._calculate_vwap(df)
                            latest_vwap = float(vwap_series.iloc[-1])
                            ema_series = df["close"].ewm(span=strategy.ema_period, adjust=False).mean()
                            latest_ema = float(ema_series.iloc[-1])
                            atm_strike = int(round(latest_close / 50.0) * 50)
                            
                            signals = strategy.generate_signals("NIFTY", df)
                            signal_str = "Wait"
                            if signals:
                                signal_str = "Buy CE" if signals[0].direction == "LONG" else "Buy PE"
                                
                            global latest_cpr_data
                            latest_cpr_data = {
                                "pivot": round(float(pivot), 2),
                                "tc": round(float(tc), 2),
                                "bc": round(float(bc), 2),
                                "vwap": round(float(latest_vwap), 2),
                                "ema20": round(float(latest_ema), 2),
                                "atm_strike": int(atm_strike),
                                "signal": signal_str,
                                "spot_price": round(float(latest_close), 2)
                            }
                    except Exception as ex:
                        logger.error(f"Error updating global CPR data in scanner: {ex}")
            
            # 4. Update open positions P&L and process exits
            closed_trades = order_executor.update_positions_pnl(ltps)
            for trade in closed_trades:
                risk_manager.record_trade_result(
                    symbol=trade["symbol"],
                    pnl=trade["pnl"],
                    qty=trade["qty"],
                    exit_price=trade["exit_price"]
                )
                
        except Exception as exc:
            logger.error(f"Background scanner exception: {exc}")
            
        # Wait 10 seconds before next scan cycle
        scanner_stop_event.wait(timeout=10.0)

# Start background thread automatically
scanner_thread = threading.Thread(target=run_scanning_loop, daemon=True)
scanner_thread.start()

# ── API Models ────────────────────────────────────────────────────────────────

class ConfigModel(BaseModel):
    risk: dict
    strategy: dict
    orb: Optional[dict] = None
    vwap_pullback: Optional[dict] = None
    cpr_intraday: Optional[dict] = None

class AngelAuthModel(BaseModel):
    api_key: str
    client_id: str
    pin: str
    totp_secret: str

# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    global scanning_active, latest_cpr_data
    angel_connected = optimized_client.session.is_connected()
    api_status = "Connected" if angel_connected else "Disconnected"
    
    strategy_type = global_config.get("strategy", {}).get("strategy_type", "fibonacci")
    secondary_strategy_type = global_config.get("strategy", {}).get("secondary_strategy_type", "none")
    
    return {
        "scanning_active": scanning_active,
        "is_live": settings.is_live,
        "trading_mode": "live" if settings.is_live else "paper",
        "api_connected": angel_connected,
        "api_status": api_status,
        "last_checked": now_ist().strftime("%Y-%m-%d %H:%M:%S"),
        "cpr_data": latest_cpr_data,
        "strategy_type": strategy_type,
        "secondary_strategy_type": secondary_strategy_type
    }

@app.get("/api/diagnostics")
def get_diagnostics():
    return optimized_client.api_stats()

@app.post("/api/scanner/start")
def start_scanner():
    global scanning_active
    if not scanning_active:
        # Check daily breakers before starting
        allowed, reason = risk_manager.can_trade(active_positions_count=len(order_executor.open_positions))
        if not allowed:
            raise HTTPException(status_code=400, detail=f"Cannot start scanner: {reason}")
        scanning_active = True
        logger.info("Live Scanning activated via API.")
    return {"message": "Scanner started successfully."}

@app.post("/api/scanner/stop")
def stop_scanner():
    global scanning_active
    if scanning_active:
        scanning_active = False
        logger.info("Live Scanning deactivated via API.")
    return {"message": "Scanner stopped successfully."}

@app.post("/api/mode/toggle")
def toggle_trading_mode():
    global scanning_active
    scanning_active = False  # Deactivate scanning when swapping modes
    
    new_mode = "paper" if settings.is_live else "live"
    settings.TRADING_MODE = new_mode
    
    # Save selection back to .env
    env_path = Path(".env")
    lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    updated = False
    new_lines = []
    for line in lines:
        if line.strip().startswith("TRADING_MODE="):
            new_lines.append(f"TRADING_MODE={new_mode}\n")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"TRADING_MODE={new_mode}\n")
        
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
        
    # Reinitialize components
    init_trading_components()
    logger.info(f"Trading mode swapped to {new_mode.upper()} via API.")
    return {"trading_mode": new_mode}

@app.get("/api/metrics")
def get_metrics():
    stats = risk_manager.stats
    open_pnl = order_executor.total_open_pnl
    gross_pnl = stats.gross_pnl
    total_pnl = gross_pnl + open_pnl
    capital = risk_manager.capital
    pnl_pct = (total_pnl / capital) * 100 if capital else 0.0
    
    # Live vs. Paper margin calculations
    if not settings.is_live:
        available_margin = capital + gross_pnl
    else:
        bal = data_fetcher.get_account_balance()
        available_margin = bal.get("available", capital)
    
    open_positions = order_executor.open_positions
    used_margin = 0.0
    for p in open_positions:
        used_margin += p.entry_price * p.qty * 0.2  # 5x intraday margin proxy
        
    free_margin = available_margin - used_margin
    if free_margin < 0:
        free_margin = 0.0
        
    total_equity = free_margin + used_margin + open_pnl
    
    return {
        "capital": capital,
        "formatted_capital": fmt_inr(capital),
        "total_equity": total_equity,
        "formatted_equity": fmt_inr(total_equity),
        "available_margin": free_margin,
        "formatted_available": fmt_inr(free_margin),
        "used_margin": used_margin,
        "formatted_used": fmt_inr(used_margin),
        "margin_utilization_pct": round((used_margin / (free_margin + used_margin)) * 100, 1) if (free_margin + used_margin) > 0 else 0.0,
        "realized_pnl": gross_pnl,
        "formatted_realized": fmt_inr(gross_pnl),
        "unrealized_pnl": open_pnl,
        "formatted_unrealized": fmt_inr(open_pnl),
        "total_pnl": total_pnl,
        "formatted_pnl": fmt_inr(total_pnl),
        "pnl_pct": round(pnl_pct, 2),
        "win_rate": stats.win_rate,
        "formatted_win_rate": f"{stats.win_rate:.1%}",
        "winners": stats.winners,
        "losers": stats.losers,
        "trades_count": stats.trades,
        "trades_limit": global_config.get("risk", {}).get("max_daily_trades", 10),
        "consecutive_losses": stats.consecutive_losses
    }

@app.get("/api/positions")
def get_positions():
    open_pos = order_executor.open_positions
    pos_list = []
    for p in open_pos:
        pos_list.append({
            "id": p.id,
            "symbol": p.symbol,
            "direction": p.direction.value,
            "qty": p.qty,
            "entry_price": p.entry_price,
            "ltp": p.ltp,
            "stop_loss": p.stop_loss,
            "target": p.target,
            "pnl": p.pnl,
            "entry_time": p.entry_time.strftime("%H:%M:%S")
        })
    return pos_list

@app.post("/api/positions/{pos_id}/squareoff")
def squareoff_position_endpoint(pos_id: str):
    # Fetch ltp from data_fetcher
    pos = order_executor._positions.get(pos_id)
    if not pos or pos.status != "OPEN":
        raise HTTPException(status_code=404, detail="Active position not found.")
        
    try:
        ltp = data_fetcher.get_ltp(pos.symbol)
    except Exception:
        ltp = pos.ltp
        
    closed_pos = order_executor.squareoff_position(pos_id, ltp)
    if closed_pos:
        risk_manager.record_trade_result(
            symbol=closed_pos.symbol,
            pnl=closed_pos.pnl,
            qty=closed_pos.qty,
            exit_price=ltp
        )
        logger.info(f"[{closed_pos.symbol}] Position manually squared off via API.")
        return {"message": f"Successfully squared off {closed_pos.symbol}."}
    else:
        raise HTTPException(status_code=400, detail="Squareoff failed.")

@app.post("/api/trades/clear")
def clear_trades():
    try:
        # 1. Clear CSV log file
        trade_history_file = Path("logs/trade_history.csv")
        if trade_history_file.exists():
            with open(trade_history_file, "w", encoding="utf-8") as f:
                f.write("timestamp,id,symbol,direction,qty,entry_price,exit_price,pnl,exit_reason,entry_time\n")
        
        # 2. Reset RiskManager stats
        risk_manager.stats.gross_pnl = 0.0
        risk_manager.stats.winners = 0
        risk_manager.stats.losers = 0
        risk_manager.stats.trades = 0
        risk_manager.stats.consecutive_losses = 0
        
        # 3. Clear in-memory order executor positions
        order_executor._positions = {}
        order_executor._trade_log = []
        
        logger.info("Trade history, statistics, and positions successfully cleared via API.")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Failed to clear trades: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/trades")
def get_trades(period: str = "Today's Trades"):
    trade_history_file = Path("logs/trade_history.csv")
    if not trade_history_file.exists():
        return []
        
    import pandas as pd
    try:
        df_trades = pd.read_csv(trade_history_file)
        if df_trades.empty:
            return []
            
        df_trades['dt'] = pd.to_datetime(df_trades['timestamp'])
        today = now_ist().date()
        yesterday = today - pd.Timedelta(days=1)
        start_of_week = today - pd.Timedelta(days=7)
        
        # Filter logic
        if period == "Today's Trades":
            df_filtered = df_trades[df_trades['dt'].dt.date == today]
        elif period == "Yesterday's Trades":
            df_filtered = df_trades[df_trades['dt'].dt.date == yesterday]
        elif period == "This Month's Trades":
            df_filtered = df_trades[
                (df_trades['dt'].dt.year == today.year) & 
                (df_trades['dt'].dt.month == today.month)
            ]
        elif period == "Last Month's Trades":
            last_month_val = 12 if today.month == 1 else today.month - 1
            last_month_year = today.year - 1 if today.month == 1 else today.year
            df_filtered = df_trades[
                (df_trades['dt'].dt.year == last_month_year) & 
                (df_trades['dt'].dt.month == last_month_val)
            ]
        elif period == "Last 7 Days":
            df_filtered = df_trades[df_trades['dt'].dt.date >= start_of_week]
        else:  # All Historical Trades
            df_filtered = df_trades
            
        if df_filtered.empty:
            return []
            
        df_filtered = df_filtered.sort_values(by="dt", ascending=False)
        
        trades_list = []
        for _, row in df_filtered.iterrows():
            trades_list.append({
                "timestamp": row["timestamp"],
                "symbol": row["symbol"],
                "direction": row["direction"],
                "qty": int(row["qty"]),
                "entry_price": float(row["entry_price"]),
                "exit_price": float(row["exit_price"]),
                "pnl": float(row["pnl"]),
                "exit_reason": row["exit_reason"]
            })
        return trades_list
    except Exception as e:
        logger.error(f"Error reading trade log CSV: {e}")
        return []

@app.get("/api/config")
def get_config():
    return load_yaml_config()

@app.post("/api/config")
def save_config(config: ConfigModel):
    try:
        new_cfg = config.dict()
        save_yaml_config(new_cfg)
        init_trading_components()
        logger.info("Configurations updated and reloaded successfully via API.")
        return {"message": "Configurations saved and loaded successfully."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/logs")
def get_logs(lines: int = 40):
    log_file_path = Path("logs/trading.log")
    if not log_file_path.exists():
        return ""
    try:
        with open(log_file_path, "r", encoding="utf-8") as f:
            log_lines = f.readlines()
        return "".join(log_lines[-lines:])
    except Exception as e:
        return f"Error reading logs: {e}"

@app.get("/api/chart/{symbol}")
def get_chart_data(symbol: str):
    try:
        strategy_type = global_config.get("strategy", {}).get("strategy_type", "fibonacci")
        secondary_strategy_type = global_config.get("strategy", {}).get("secondary_strategy_type", "none")
        
        active_strat_type = strategy_type
        active_strategy = strategy
        
        if strategy_type == "cpr_intraday" and symbol != "NIFTY" and secondary_strategy_type != "none":
            active_strat_type = secondary_strategy_type
            active_strategy = secondary_strategy
            
        timeframe = global_config["strategy"].get("timeframe", "15minute")
        if active_strat_type == "cpr_intraday":
            timeframe = "5minute"  # CPR options strategy uses 5m timeframe
            
        df_chart = data_fetcher.get_historical_data(symbol, interval=timeframe, days=5)
        
        if df_chart.empty:
            raise HTTPException(status_code=404, detail="No chart data returned from feed.")
            
        candles = []
        direction = None
        sh_res = None
        sl_res = None
        orh = None
        orl = None
        fib_levels = {}
        fib_extensions = {}
        
        sh_idx_val = None
        sl_idx_val = None
        
        if active_strat_type == "fibonacci" and active_strategy is not None:
            sh_res = active_strategy.find_swing_high(df_chart["high"])
            sl_res = active_strategy.find_swing_low(df_chart["low"])
            
            if sh_res and sl_res:
                sh_idx, sh_val = sh_res
                sl_idx, sl_val = sl_res
                direction = "LONG" if sl_idx < sh_idx else "SHORT"
                fib = active_strategy.calculate_fib_levels(sh_val, sl_val, Direction.LONG if direction == "LONG" else Direction.SHORT)
                fib_levels = {str(k): float(v) for k, v in fib.levels.items()}
                fib_extensions = {str(k): float(v) for k, v in fib.extensions.items()}
                sh_idx_val = sh_idx
                sl_idx_val = sl_idx
                
        elif active_strat_type == "orb" and active_strategy is not None:
            # Calculate ORH/ORL for the most recent day in historical df_chart
            last_day = df_chart.index[-1].date()
            df_day = df_chart[df_chart.index.date == last_day]
            orh, orl = active_strategy.calculate_opening_range(df_day)
            
            if orh is not None and orl is not None:
                # Expose ORH/ORL as fib_levels with string keys to trigger horizontal chart lines in frontend
                fib_levels = {"ORH": orh, "ORL": orl}
                range_size = orh - orl
                fib_extensions = {
                    "Target 1 (1.0x)": orh + range_size if range_size > 0 else 0,
                    "Target 2 (1.5x)": orh + range_size * 1.5 if range_size > 0 else 0
                }
                sh_res = (0, orh)
                sl_res = (0, orl)
                
        elif active_strat_type == "vwap_pullback" and active_strategy is not None:
            vwap = active_strategy._calculate_vwap(df_chart)
            ema = df_chart["close"].ewm(span=active_strategy.ema_period, adjust=False).mean()
            
            curr_vwap = float(vwap.iloc[-1])
            curr_ema = float(ema.iloc[-1])
            
            fib_levels = {"VWAP": curr_vwap, "EMA9": curr_ema}
            curr_close = float(df_chart["close"].iloc[-1])
            # Default target for layout purposes
            fib_extensions = {
                "Target (1:2)": curr_close + (curr_close - curr_vwap) * 2
            }
            orh = curr_vwap
            orl = curr_ema
            
        elif active_strat_type == "cpr_intraday" and active_strategy is not None:
            vwap = active_strategy._calculate_vwap(df_chart)
            ema = df_chart["close"].ewm(span=active_strategy.ema_period, adjust=False).mean()
            
            curr_vwap = float(vwap.iloc[-1])
            curr_ema = float(ema.iloc[-1])
            
            # Retrieve daily CPR levels
            cpr_vals = active_strategy.calculate_cpr(symbol)
            if cpr_vals:
                pivot, tc, bc = cpr_vals
                fib_levels = {
                    "Pivot": float(pivot),
                    "TC": float(tc),
                    "BC": float(bc),
                    "VWAP": curr_vwap,
                    "EMA20": curr_ema
                }
                orh = float(tc)
                orl = float(bc)
            else:
                fib_levels = {
                    "VWAP": curr_vwap,
                    "EMA20": curr_ema
                }
                orh = curr_vwap
                orl = curr_ema
                
        for idx, (t, row) in enumerate(df_chart.iterrows()):
            candles.append({
                "time": int(t.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "is_swing_high": idx == sh_idx_val if sh_idx_val is not None else False,
                "is_swing_low": idx == sl_idx_val if sl_idx_val is not None else False
            })
            
        return {
            "symbol": symbol,
            "candles": candles,
            "direction": direction,
            "swing_high": float(sh_res[1]) if sh_res and active_strat_type == "fibonacci" else (orh if active_strat_type == "orb" and orh else None),
            "swing_low": float(sl_res[1]) if sl_res and active_strat_type == "fibonacci" else (orl if active_strat_type == "orb" and orl else None),
            "fib_levels": fib_levels,
            "fib_extensions": fib_extensions,
            "strategy_type": active_strat_type
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/backtest")
def run_backtest_endpoint(bt_params: dict):
    try:
        bt_symbol = bt_params["symbol"]
        bt_tf = bt_params["timeframe"]
        bt_days = int(bt_params["days"])
        bt_capital = float(bt_params["capital"])
        bt_risk = float(bt_params["risk"])
        
        strategy_type = bt_params.get("strategy_type", "fibonacci")
        
        # Load historical candles once using Yahoo Finance
        df_bt = data_fetcher.get_historical_data_yfinance(bt_symbol, interval=bt_tf, days=bt_days)
        if df_bt.empty or len(df_bt) < 40:
            raise HTTPException(status_code=400, detail="Insufficient historical data returned for backtesting.")

        def run_single_backtest(s_type: str) -> dict:
            bt_config = {
                "strategy": {
                    "strategy_type": s_type,
                    "swing_threshold": global_config["strategy"].get("swing_threshold", 4),
                    "price_tolerance": global_config["strategy"].get("price_tolerance", 0.0025),
                    "confirmation_candles": global_config["strategy"].get("confirmation_candles", 1),
                    "volume_multiplier": global_config["strategy"].get("volume_multiplier", 1.3),
                    "min_trend_strength": global_config["strategy"].get("min_trend_strength", 2.5),
                    "fib_levels": global_config["strategy"].get("fib_levels", [0.382, 0.5, 0.618]),
                    "fib_extensions": global_config["strategy"].get("fib_extensions", [1.272, 1.618]),
                    "timeframe": bt_tf
                },
                "orb": global_config.get("orb", {}),
                "vwap_pullback": global_config.get("vwap_pullback", {}),
                "risk": {
                    "capital": bt_capital,
                    "risk_per_trade": bt_risk / 100.0,
                    "min_risk_reward": global_config["risk"].get("min_risk_reward", 2.5)
                }
            }
            
            from core.backtester import Backtester
            tester = Backtester(bt_config)
            res = tester.run(bt_symbol, df_bt)
            
            # Serialize trades
            trades_list = []
            for t in res.trades:
                entry_time = df_bt.index[t.entry_idx].strftime("%Y-%m-%d %H:%M") if t.entry_idx < len(df_bt) else "N/A"
                exit_time = df_bt.index[t.exit_idx].strftime("%Y-%m-%d %H:%M") if (t.exit_idx and t.exit_idx < len(df_bt)) else "N/A"
                trades_list.append({
                    "symbol": t.symbol,
                    "direction": t.direction.value,
                    "qty": t.qty,
                    "entry_price": float(t.entry_price),
                    "exit_price": float(t.exit_price) if t.exit_price else None,
                    "exit_reason": t.exit_reason,
                    "pnl": float(t.pnl),
                    "entry_time": entry_time,
                    "exit_time": exit_time
                })
                
            # Serialize equity curve for Recharts
            equity_points = []
            for idx, val in enumerate(res.equity_curve):
                t_idx = idx if idx < len(df_bt) else len(df_bt) - 1
                timestamp = int(df_bt.index[t_idx].timestamp())
                equity_points.append({
                    "time": timestamp,
                    "equity": round(float(val), 2)
                })
                
            return {
                "symbol": bt_symbol,
                "initial_capital": res.initial_capital,
                "final_equity": round(float(res.equity_curve[-1]), 2),
                "total_return": res.total_return,
                "cagr": res.cagr,
                "sharpe": res.sharpe,
                "max_drawdown": res.max_drawdown,
                "win_rate": res.win_rate,
                "profit_factor": res.profit_factor,
                "winners": res.winners,
                "losers": res.losers,
                "trades": trades_list,
                "equity_curve": equity_points
            }

        if strategy_type == "compare_all":
            results = {}
            for s in ["fibonacci", "orb", "vwap_pullback"]:
                results[s] = run_single_backtest(s)
            return {
                "comparison": True,
                "results": results
            }
        else:
            single_res = run_single_backtest(strategy_type)
            single_res["comparison"] = False
            return single_res
    except Exception as e:
        logger.exception("Backtest run failed")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/auth-callback")
def handle_auth_callback(auth_data: AngelAuthModel):
    try:
        from SmartApi import SmartConnect
        import pyotp
        
        logger.info(f"Testing Angel One authentication for client: {auth_data.client_id}...")
        smart = SmartConnect(api_key=auth_data.api_key)
        totp_val = pyotp.TOTP(auth_data.totp_secret).now()
        
        session_data = smart.generateSession(
            clientCode=auth_data.client_id,
            password=auth_data.pin,
            totp=totp_val
        )
        
        if session_data.get("status") is not True:
            raise ValueError(session_data.get("message", "Session generation rejected by Angel One"))
            
        # Save credentials to .env
        env_path = Path(".env")
        lines = []
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
        keys_to_update = {
            "ANGEL_API_KEY": auth_data.api_key,
            "ANGEL_CLIENT_ID": auth_data.client_id,
            "ANGEL_PIN": auth_data.pin,
            "ANGEL_TOTP_SECRET": auth_data.totp_secret
        }
        
        keys_to_remove = ["KITE_API_KEY", "KITE_API_SECRET", "KITE_ACCESS_TOKEN"]
        
        updated_keys = set()
        new_lines = []
        for line in lines:
            if any(line.strip().startswith(f"{k}=") for k in keys_to_remove):
                continue
                
            match = False
            for k, v in keys_to_update.items():
                if line.strip().startswith(f"{k}="):
                    new_lines.append(f"{k}={v}\n")
                    updated_keys.add(k)
                    match = True
                    break
            if not match:
                new_lines.append(line)
                
        for k, v in keys_to_update.items():
            if k not in updated_keys:
                new_lines.append(f"{k}={v}\n")
                
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
            
        # Reinitialize core components
        init_trading_components()
        user_name = session_data.get("data", {}).get("name", "Trader")
        return {"status": "success", "user_name": user_name}
    except Exception as e:
        logger.error(f"Angel One credentials validation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/panic")
def trigger_panic_close():
    try:
        closed_count = order_executor.panic_close_all(data_fetcher=data_fetcher)
        return {"status": "success", "closed_positions": closed_count}
    except Exception as e:
        logger.error(f"Panic close execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
