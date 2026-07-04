"""
app.py
------
Streamlit Dashboard for the Fibonacci Retracement Automated Trading App.
Features:
- Live Trading Tab (Metrics, Plotly Candlestick Chart, Positions Tracker, Logs Stream, Autorefresh)
- Backtesting Tab (KPI Summary, Equity & Drawdown Chart, Trades Table)
- Config Editor Tab (YAML Editor)
- Zerodha Auth Tab (OAuth Token Generator)
"""
import os
import sys
import yaml
import time
from pathlib import Path
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# Inject local path if necessary
sys.path.append(str(Path(__file__).parent))

from config.settings import settings
import config.settings
from core.data_fetcher import KiteDataFetcher
from core.strategy import FibonacciStrategy, Direction
from core.risk_manager import RiskManager
from core.order_executor import OrderExecutor, Position
from core.backtester import Backtester
from utils.logger import logger

from utils.helpers import fmt_inr, fmt_pct, now_ist, is_market_open, is_after_squareoff

# ══════════════════════════════════════════════════════════════════════════════
# Page Configurations & Design
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Fib Trader",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom premium styling using CSS injection
CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=JetBrains+Mono:wght@400;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }
    
    /* Code styling */
    code, pre {
        font-family: 'JetBrains Mono', monospace !important;
    }
    
    /* Sleek gradient background */
    .stApp {
        background-color: #0c0e17;
        background-image: radial-gradient(at 0% 0%, rgba(26, 29, 46, 0.8) 0, transparent 50%),
                          radial-gradient(at 100% 0%, rgba(15, 82, 186, 0.15) 0, transparent 50%);
        color: #e0e6f0;
    }
    
    /* Cards styling */
    .metric-card {
        background: rgba(26, 29, 46, 0.65);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
        backdrop-filter: blur(8px);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        border-color: rgba(79, 195, 247, 0.3);
    }
    .metric-title {
        font-size: 14px;
        color: #8c96ad;
        font-weight: 600;
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }
    .metric-value {
        font-size: 28px;
        font-weight: 800;
        margin-top: 5px;
        color: #ffffff;
    }
    .metric-delta {
        font-size: 14px;
        margin-top: 5px;
        font-weight: 600;
    }
    .delta-green { color: #00e676; }
    .delta-red { color: #ef5350; }
    .delta-neutral { color: #8c96ad; }

    /* Custom sidebar styling */
    section[data-testid="stSidebar"] {
        background-color: #090a10 !important;
        border-right: 1px solid rgba(255, 255, 255, 0.05);
    }
    
    /* Custom headers */
    h1, h2, h3 {
        font-weight: 800 !important;
        background: linear-gradient(135deg, #ffffff 0%, #a5b4fc 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    /* Smooth transition for buttons */
    .stButton>button {
        background: linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 10px 24px !important;
        font-weight: 600 !important;
        transition: all 0.3s ease !important;
        box-shadow: 0 4px 15px rgba(59, 130, 246, 0.2) !important;
    }
    .stButton>button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 20px rgba(59, 130, 246, 0.4) !important;
    }
    
    /* Scrollable log container */
    .log-container {
        background-color: #05060b;
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 8px;
        padding: 15px;
        max-height: 300px;
        overflow-y: scroll;
        font-size: 13px;
        line-height: 1.5;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# Session State Initialisation
# ══════════════════════════════════════════════════════════════════════════════

CONFIG_PATH = Path("config/config.yaml")

def load_yaml_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_yaml_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False)

if "config" not in st.session_state:
    st.session_state.config = load_yaml_config()

# Helper to reload core modules when credentials/config change
def init_trading_components():
    # Reload settings singleton to fetch any updated .env variables
    new_settings = settings.__class__()
    fields = settings.model_fields.keys() if hasattr(settings, "model_fields") else settings.__fields__.keys()
    for field_name in fields:
        setattr(settings, field_name, getattr(new_settings, field_name))
    
    # Initialize Core modules
    st.session_state.data_fetcher = KiteDataFetcher()
    st.session_state.strategy = FibonacciStrategy(st.session_state.config)
    capital_val = (
        st.session_state.data_fetcher.get_account_balance().get("available", 100_000)
        if settings.is_live
        else st.session_state.config["risk"].get("capital", 100_000)
    )
    st.session_state.risk_manager = RiskManager(
        st.session_state.config, 
        capital=capital_val
    )
    st.session_state.order_executor = OrderExecutor(kite=st.session_state.data_fetcher._kite)
    st.session_state.initialized = True

if "initialized" not in st.session_state or st.sidebar.button("Force Reload Modules"):
    init_trading_components()
    st.toast("Core trading components initialized successfully!")

# Scanning status in session state
if "scanning_active" not in st.session_state:
    st.session_state.scanning_active = False

# ══════════════════════════════════════════════════════════════════════════════
# Sidebar Control Panel
# ══════════════════════════════════════════════════════════════════════════════

st.sidebar.markdown("## SYSTEM STATUS")

# Mode Switcher
current_mode = "live" if settings.is_live else "paper"
selected_mode = st.sidebar.selectbox(
    "Select Mode:",
    options=["Paper Trading (Virtual)", "Live Trading (Zerodha)"],
    index=1 if settings.is_live else 0,
    help="Switch between simulated paper trading and real order execution."
)
new_mode = "live" if "Live" in selected_mode else "paper"

if new_mode != current_mode:
    settings.TRADING_MODE = new_mode
    # Update .env file
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
        
    st.sidebar.success(f"Switched to {new_mode.upper()} mode!")
    init_trading_components()
    st.rerun()

mode = "LIVE" if settings.is_live else "PAPER"
api_status = "Connected" if not st.session_state.data_fetcher.is_mock else "Mock Mode"
mode_color = "#ef5350" if settings.is_live else "#4fc3f7"
api_color = "#00e676" if not st.session_state.data_fetcher.is_mock else "#ff8f00"

st.sidebar.markdown(f"""
<div style="background: rgba(26, 29, 46, 0.65); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; padding: 12px; margin-bottom: 15px;">
    <div style="font-size: 11px; text-transform: uppercase; color: #8c96ad; font-weight: 600; letter-spacing: 0.5px; margin-bottom: 4px;">Active Trading Mode</div>
    <div style="font-size: 16px; font-weight: 800; color: {mode_color};">{mode}</div>
    <div style="height: 10px;"></div>
    <div style="font-size: 11px; text-transform: uppercase; color: #8c96ad; font-weight: 600; letter-spacing: 0.5px; margin-bottom: 4px;">Kite API Status</div>
    <div style="font-size: 16px; font-weight: 800; color: {api_color};">{api_status}</div>
</div>
""", unsafe_allow_html=True)

# Display general information in sidebar
st.sidebar.markdown("---")
st.sidebar.markdown("### Active Universe")
for sym in st.session_state.config["strategy"]["symbols"]:
    st.sidebar.text(f"• {sym}")

# ══════════════════════════════════════════════════════════════════════════════
# Dashboard Header
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("## Fib Trader")
st.markdown("##### Automated Fibonacci Retracement trading system for NSE equities")
st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# Tabs Navigation
# ══════════════════════════════════════════════════════════════════════════════

tab_live, tab_backtest, tab_config, tab_auth = st.tabs([
    "Live Trading Dashboard", 
    "Historical Backtesting", 
    "Strategy & Risk Settings", 
    "Zerodha Authentication"
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: Live Trading Dashboard
# ══════════════════════════════════════════════════════════════════════════════

with tab_live:
    # Autorefresh when scanning is active (every 10 seconds)
    if st.session_state.scanning_active:
        st_refresh_id = st_autorefresh(interval=10000, key="trading_autorefresh")
    
    # ── Scanning Control Bar ────────────────────────────────────────────────
    col_ctrl_1, col_ctrl_2, col_ctrl_3 = st.columns([2, 2, 4])
    with col_ctrl_1:
        if not st.session_state.scanning_active:
            if st.button("Start Live Scanning", use_container_width=True):
                st.session_state.scanning_active = True
                logger.info("Live Scanning started.")
                st.rerun()
        else:
            if st.button("Stop Live Scanning", use_container_width=True):
                st.session_state.scanning_active = False
                logger.info("Live Scanning stopped.")
                st.rerun()
                
    with col_ctrl_2:
        # Check daily circuit breakers
        allowed, reason = st.session_state.risk_manager.can_trade(active_positions_count=len(st.session_state.order_executor.open_positions))
        if not allowed:
            status_text = f"Circuit Breaker Active: {reason}"
            status_color = "#ef5350"
            st.session_state.scanning_active = False
        elif st.session_state.scanning_active:
            status_text = "System active & scanning"
            status_color = "#00e676"
        else:
            status_text = "Scanning paused"
            status_color = "#8c96ad"
            
        st.markdown(f"""
        <div style="background: rgba(26, 29, 46, 0.4); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; padding: 10px 15px; height: 45px; display: flex; align-items: center;">
            <div style="width: 8px; height: 8px; border-radius: 50%; background-color: {status_color}; margin-right: 10px; display: inline-block;"></div>
            <span style="font-size: 14px; font-weight: 600; color: #ffffff;">{status_text}</span>
        </div>
        """, unsafe_allow_html=True)
            
    with col_ctrl_3:
        st.markdown(f"<div style='text-align: right; color:#8c96ad; font-size:14px; margin-top:10px;'>Last Checked: {now_ist().strftime('%Y-%m-%d %H:%M:%S')} IST</div>", unsafe_allow_html=True)

    # ── Core Scanning Execution Loop ────────────────────────────────────────
    if st.session_state.scanning_active:
        # 1. Reset counters at 9:15 AM
        st.session_state.risk_manager.reset_daily_counters()
        
        # 2. Check Auto square-off at 3:15 PM
        # order_executor will auto-squareoff inside update_positions_pnl if current time >= 15:15
        
        # 3. Scan each symbol
        symbols = st.session_state.config["strategy"]["symbols"]
        timeframe = st.session_state.config["strategy"]["timeframe"]
        lookback = st.session_state.config["strategy"].get("lookback_candles", 100)
        
        ltps = {}
        for sym in symbols:
            try:
                # Get LTP
                ltp = st.session_state.data_fetcher.get_ltp(sym)
                ltps[sym] = ltp
                
                # Fetch history for signal calculations
                df_hist = st.session_state.data_fetcher.get_historical_data(sym, interval=timeframe, days=5)
                
                # Avoid scans if no positions allowed
                can_tr, _ = st.session_state.risk_manager.can_trade(sym, active_positions_count=len(st.session_state.order_executor.open_positions))
                if not can_tr:
                    continue
                
                # Run strategy signals
                signals = st.session_state.strategy.generate_signals(sym, df_hist)
                
                # If signal, execute
                if signals:
                    sig = signals[0]
                    # Check if already open
                    open_syms = [p.symbol for p in st.session_state.order_executor.open_positions]
                    if sym not in open_syms:
                        qty = st.session_state.risk_manager.calculate_position_size(
                            sym, sig.entry_price, sig.stop_loss
                        )
                        if qty > 0:
                            pos = st.session_state.order_executor.execute_entry(sig, qty)
                            if pos:
                                st.session_state.risk_manager.add_position_exposure(sym, qty * sig.entry_price)
                                logger.info(f"[{sym}] Signal Executed: {sig.direction} {qty} shares.")
            except Exception as e:
                logger.error(f"Error scanning {sym}: {e}")
                
        # 4. Update Open Positions & Check Stop-losses / Targets
        closed_trades = st.session_state.order_executor.update_positions_pnl(ltps)
        for trade in closed_trades:
            st.session_state.risk_manager.record_trade_result(
                symbol=trade["symbol"],
                pnl=trade["pnl"],
                qty=trade["qty"],
                exit_price=trade["exit_price"]
            )


    # ── KPIs Metrics Row ────────────────────────────────────────────────────
    stats = st.session_state.risk_manager.stats
    open_pnl = st.session_state.order_executor.total_open_pnl
    gross_pnl = stats.gross_pnl
    total_pnl = gross_pnl + open_pnl
    capital = st.session_state.risk_manager.capital
    pnl_pct = (total_pnl / capital) * 100 if capital else 0.0
    
    st.markdown("### Metrics")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Available Capital</div>
            <div class="metric-value">{fmt_inr(capital)}</div>
            <div class="metric-delta delta-neutral">Intraday (MIS) System</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col2:
        delta_class = "delta-green" if total_pnl >= 0 else "delta-red"
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Today's P&L</div>
            <div class="metric-value">{fmt_inr(total_pnl)}</div>
            <div class="metric-delta {delta_class}">{total_pnl:+.2f} ({pnl_pct:+.2f}%)</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col3:
        win_rate_val = stats.win_rate * 100
        delta_class = "delta-green" if win_rate_val >= 50 else ("delta-red" if win_rate_val > 0 else "delta-neutral")
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Win Rate</div>
            <div class="metric-value">{stats.win_rate:.1%}</div>
            <div class="metric-delta {delta_class}">{stats.winners} W - {stats.losers} L</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col4:
        trades_limit = st.session_state.config["risk"]["max_daily_trades"]
        consec_losses = stats.consecutive_losses
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Daily Trades</div>
            <div class="metric-value">{stats.trades} / {trades_limit}</div>
            <div class="metric-delta {'delta-red' if consec_losses >= 3 else 'delta-neutral'}">Consecutive Losses: {consec_losses}</div>
        </div>
        """, unsafe_allow_html=True)

    # ── Active Positions & Visualisation ────────────────────────────────────
    st.markdown("---")
    st.markdown("### Current Positions")
    open_pos = st.session_state.order_executor.open_positions
    
    if not open_pos:
        st.markdown("""
        <div style="text-align: center; padding: 40px; background: rgba(26, 29, 46, 0.3); border: 1px dashed rgba(255, 255, 255, 0.1); border-radius: 12px; color: #8c96ad;">
            <div style="font-size: 15px; font-weight: 600; color: #ffffff;">No active positions</div>
            <div style="font-size: 13px; margin-top: 5px;">Positions will appear here once entry signals are triggered.</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Display open positions table
        pos_data = []
        for p in open_pos:
            # Add action button column for squareoff manually
            pos_data.append({
                "ID": p.id,
                "Symbol": p.symbol,
                "Direction": p.direction.value,
                "Quantity": p.qty,
                "Entry Price": f"₹{p.entry_price:,.2f}",
                "LTP": f"₹{p.ltp:,.2f}",
                "Stop Loss": f"₹{p.stop_loss:,.2f}",
                "Target": f"₹{p.target:,.2f}",
                "Unrealised P&L": p.pnl,
                "Entry Time": p.entry_time.strftime("%H:%M:%S")
            })
        
        df_pos = pd.DataFrame(pos_data)
        
        # Display styled table
        st.dataframe(
            df_pos.style.map(
                lambda x: "color: #00e676; font-weight: bold;" if isinstance(x, float) and x >= 0 else ("color: #ef5350; font-weight: bold;" if isinstance(x, float) and x < 0 else ""),
                subset=["Unrealised P&L"]
            ).format({"Unrealised P&L": "₹{:,.2f}"}),
            use_container_width=True,
            hide_index=True
        )
        
        # Interactive square-off controls
        st.markdown("##### Manual Emergency Actions")
        cols_sq = st.columns(len(open_pos))
        for idx, p in enumerate(open_pos):
            with cols_sq[idx]:
                if st.button(f"Square-off {p.symbol}", key=f"sq_{p.id}"):
                    # Execute manual exit via order_executor to trigger CSV logging
                    pos_closed = st.session_state.order_executor.squareoff_position(p.id, p.ltp)
                    if pos_closed:
                        st.session_state.risk_manager.record_trade_result(
                            symbol=pos_closed.symbol,
                            pnl=pos_closed.pnl,
                            qty=pos_closed.qty,
                            exit_price=p.ltp
                        )
                        st.success(f"Squared off {p.symbol}!")
                        st.rerun()

    # ── Completed Trades History Section ─────────────────────────────────────
    st.markdown("---")
    st.markdown("###  Completed Trades History")
    
    trade_history_file = Path("logs/trade_history.csv")
    if trade_history_file.exists():
        try:
            # Read trade history CSV
            df_trades = pd.read_csv(trade_history_file)
            
            if not df_trades.empty:
                # Add Date Filter Selectbox
                col_hist_filt, col_hist_summary = st.columns([4, 8])
                
                with col_hist_filt:
                    filter_option = st.selectbox(
                        "Filter Trades By Period:",
                        options=[
                            "Today's Trades",
                            "Yesterday's Trades",
                            "This Month's Trades",
                            "Last Month's Trades",
                            "Last 7 Days",
                            "All Historical Trades"
                        ],
                        index=0
                    )
                
                # Parse timestamps and determine date bounds
                df_trades['dt'] = pd.to_datetime(df_trades['timestamp'])
                today = now_ist().date()
                yesterday = today - pd.Timedelta(days=1)
                start_of_week = today - pd.Timedelta(days=7)
                
                # Filter dataframe based on selected option
                if filter_option == "Today's Trades":
                    df_filtered = df_trades[df_trades['dt'].dt.date == today]
                elif filter_option == "Yesterday's Trades":
                    df_filtered = df_trades[df_trades['dt'].dt.date == yesterday]
                elif filter_option == "This Month's Trades":
                    df_filtered = df_trades[
                        (df_trades['dt'].dt.year == today.year) & 
                        (df_trades['dt'].dt.month == today.month)
                    ]
                elif filter_option == "Last Month's Trades":
                    last_month_val = 12 if today.month == 1 else today.month - 1
                    last_month_year = today.year - 1 if today.month == 1 else today.year
                    df_filtered = df_trades[
                        (df_trades['dt'].dt.year == last_month_year) & 
                        (df_trades['dt'].dt.month == last_month_val)
                    ]
                elif filter_option == "Last 7 Days":
                    df_filtered = df_trades[df_trades['dt'].dt.date >= start_of_week]
                else:  # All Historical Trades
                    df_filtered = df_trades
                
                # Render results
                if not df_filtered.empty:
                    # Calculate summary stats for filtered range
                    total_t = len(df_filtered)
                    net_pnl_val = df_filtered['pnl'].sum()
                    winners_count = len(df_filtered[df_filtered['pnl'] > 0])
                    win_rate_val = (winners_count / total_t) * 100 if total_t > 0 else 0.0
                    
                    with col_hist_summary:
                        pnl_color = "#00e676" if net_pnl_val >= 0 else "#ef5350"
                        st.markdown(f"""
                        <div style="display: flex; gap: 20px; align-items: center; justify-content: flex-end; height: 100%; margin-top: 15px;">
                            <div style="text-align: center;">
                                <div style="font-size: 11px; text-transform: uppercase; color: #8c96ad; font-weight:600;">Trades</div>
                                <div style="font-size: 18px; font-weight:800; color: #ffffff;">{total_t}</div>
                            </div>
                            <div style="text-align: center; border-left: 1px solid rgba(255,255,255,0.1); padding-left: 20px;">
                                <div style="font-size: 11px; text-transform: uppercase; color: #8c96ad; font-weight:600;">Net P&L</div>
                                <div style="font-size: 18px; font-weight:800; color: {pnl_color};">{fmt_inr(net_pnl_val)}</div>
                            </div>
                            <div style="text-align: center; border-left: 1px solid rgba(255,255,255,0.1); padding-left: 20px;">
                                <div style="font-size: 11px; text-transform: uppercase; color: #8c96ad; font-weight:600;">Win Rate</div>
                                <div style="font-size: 18px; font-weight:800; color: {'#00e676' if win_rate_val >= 50 else '#8c96ad'};">{win_rate_val:.1f}%</div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    # Prepare table display
                    df_display = df_filtered.copy()
                    df_display = df_display.sort_values(by="dt", ascending=False)
                    
                    # Select and rename columns for display
                    display_cols = {
                        "timestamp": "Timestamp",
                        "symbol": "Symbol",
                        "direction": "Direction",
                        "qty": "Quantity",
                        "entry_price": "Entry Price",
                        "exit_price": "Exit Price",
                        "pnl": "Realised P&L",
                        "exit_reason": "Exit Reason"
                    }
                    df_display_tbl = df_display[list(display_cols.keys())].rename(columns=display_cols)
                    
                    st.dataframe(
                        df_display_tbl.style.map(
                            lambda x: "color: #00e676; font-weight: bold;" if isinstance(x, float) and x >= 0 else ("color: #ef5350; font-weight: bold;" if isinstance(x, float) and x < 0 else ""),
                            subset=["Realised P&L"]
                        ).format({"Realised P&L": "₹{:,.2f}", "Entry Price": "₹{:,.2f}", "Exit Price": "₹{:,.2f}"}),
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.markdown(f"<div style='color: #8c96ad; font-size:14px; font-style:italic; padding: 10px 0;'>No trades found for {filter_option}.</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='color: #8c96ad; font-size:14px; font-style:italic; padding: 10px 0;'>No trade history recorded yet in the log file.</div>", unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Could not load completed trades: {e}")
    else:
        st.markdown("<div style='color: #8c96ad; font-size:14px; font-style:italic; padding: 10px 0;'>No trade history file created yet.</div>", unsafe_allow_html=True)

    # ── Interactive Plotly Chart with Fibonacci Levels ──────────────────────
    st.markdown("---")
    st.markdown("### Interactive Level Analysis")
    
    col_chart_sel, col_chart_space = st.columns([3, 9])
    with col_chart_sel:
        selected_symbol = st.selectbox("Select symbol to chart:", st.session_state.config["strategy"]["symbols"])
        
    if selected_symbol:
        try:
            timeframe = st.session_state.config["strategy"]["timeframe"]
            # Fetch 100 candles of historical data
            df_chart = st.session_state.data_fetcher.get_historical_data(selected_symbol, interval=timeframe, days=10)
            
            if not df_chart.empty:
                # Re-calculate swing levels for plotting
                sh_res = st.session_state.strategy.find_swing_high(df_chart["high"])
                sl_res = st.session_state.strategy.find_swing_low(df_chart["low"])
                
                fig = go.Figure(data=[go.Candlestick(
                    x=df_chart.index,
                    open=df_chart['open'],
                    high=df_chart['high'],
                    low=df_chart['low'],
                    close=df_chart['close'],
                    name="Price"
                )])
                
                # Plot swing markers and fib levels if both exist
                if sh_res and sl_res:
                    sh_idx, sh_val = sh_res
                    sl_idx, sl_val = sl_res
                    
                    sh_time = df_chart.index[sh_idx]
                    sl_time = df_chart.index[sl_idx]
                    
                    # Highlight Swings
                    fig.add_trace(go.Scatter(
                        x=[sh_time], y=[sh_val],
                        mode="markers+text",
                        marker=dict(symbol="triangle-down", size=12, color="#ef5350"),
                        name="Swing High",
                        text=["Swing High"], textposition="top center"
                    ))
                    
                    fig.add_trace(go.Scatter(
                        x=[sl_time], y=[sl_val],
                        mode="markers+text",
                        marker=dict(symbol="triangle-up", size=12, color="#00e676"),
                        name="Swing Low",
                        text=["Swing Low"], textposition="bottom center"
                    ))
                    
                    # Calculate Fib Levels
                    direction = Direction.LONG if sl_idx < sh_idx else Direction.SHORT
                    fib = st.session_state.strategy.calculate_fib_levels(sh_val, sl_val, direction)
                    
                    # Plot horizontal lines for Retracement Levels
                    colors = {
                        0.0: "#888888",
                        0.236: "#ff8f00",
                        0.382: "#ffd54f",
                        0.500: "#81c784",
                        0.618: "#64b5f6", # Golden level
                        0.786: "#ba68c8",
                        1.0: "#888888"
                    }
                    
                    for ratio, lvl_price in fib.levels.items():
                        fig.add_hline(
                            y=lvl_price,
                            line_dash="dash",
                            line_color=colors.get(ratio, "#888888"),
                            annotation_text=f"Fib {ratio:.3f} (₹{lvl_price:,.2f})",
                            annotation_position="right",
                            annotation_font=dict(size=10, color="#b0b8cc")
                        )
                        
                    # Plot extension levels
                    for ratio, ext_price in fib.extensions.items():
                        fig.add_hline(
                            y=ext_price,
                            line_dash="dot",
                            line_color="#e91e63",
                            annotation_text=f"Ext {ratio:.3f} (₹{ext_price:,.2f})",
                            annotation_position="left",
                            annotation_font=dict(size=10, color="#f48fb1")
                        )
                
                fig.update_layout(
                    template="plotly_dark",
                    plot_bgcolor="#1a1d2e",
                    paper_bgcolor="#0c0e17",
                    xaxis_rangeslider_visible=False,
                    height=500,
                    margin=dict(l=10, r=10, t=30, b=10),
                    xaxis=dict(gridcolor="#2a2d3e"),
                    yaxis=dict(gridcolor="#2a2d3e", title="Price (₹)"),
                )
                
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.markdown("""
                <div style="text-align: center; padding: 30px; color: #8c96ad;">
                    No data available to chart.
                </div>
                """, unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Failed to generate level analysis chart: {e}")

    # ── Log Stream Section ──────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Log Stream")
    
    log_file_path = Path("logs/trading.log")
    if log_file_path.exists():
        try:
            with open(log_file_path, "r", encoding="utf-8") as f:
                logs = f.readlines()
            # Show last 40 lines
            log_tail = "".join(logs[-40:])
            st.markdown(f'<div class="log-container"><pre>{log_tail}</pre></div>', unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Could not read logs: {e}")
    else:
        st.markdown("<div style='color: #8c96ad; font-size:14px; font-style:italic;'>No trading logs generated yet.</div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: Historical Backtesting
# ══════════════════════════════════════════════════════════════════════════════

with tab_backtest:
    st.markdown("### Run Backtest")
    st.markdown("Simulate strategy performance over historical market bars without look-ahead bias.")
    
    col_bt_1, col_bt_2 = st.columns([1, 2])
    
    with col_bt_1:
        st.markdown("##### Backtest Parameters")
        bt_symbol = st.selectbox("Symbol to test:", st.session_state.config["strategy"]["symbols"], key="bt_sym")
        bt_tf = st.selectbox("Candle Timeframe:", ["minute", "3minute", "5minute", "15minute"], index=3, key="bt_tf")
        bt_days = st.slider("Historical Lookback (Days):", min_value=5, max_value=120, value=30, step=5, key="bt_days")
        bt_capital = st.number_input("Starting Capital (₹):", min_value=10000, value=500000, step=10000, key="bt_cap")
        bt_risk = st.slider("Risk Per Trade (%):", min_value=0.1, max_value=5.0, value=1.0, step=0.1, key="bt_risk")
        
        run_bt = st.button("Run Backtest", use_container_width=True)
        
    with col_bt_2:
        if run_bt:
            with st.spinner(f"Running backtest for {bt_symbol} ({bt_days} days)..."):
                try:
                    # Construct temporary configuration for backtester
                    bt_config = {
                        "strategy": {
                            "swing_threshold": st.session_state.config["strategy"].get("swing_threshold", 5),
                            "price_tolerance": st.session_state.config["strategy"].get("price_tolerance", 0.003),
                            "confirmation_candles": st.session_state.config["strategy"].get("confirmation_candles", 2),
                            "volume_multiplier": st.session_state.config["strategy"].get("volume_multiplier", 1.5),
                            "min_trend_strength": st.session_state.config["strategy"].get("min_trend_strength", 2.0),
                            "fib_levels": st.session_state.config["strategy"].get("fib_levels", [0.0, 0.236, 0.382, 0.500, 0.618, 0.786, 1.0]),
                            "fib_extensions": st.session_state.config["strategy"].get("fib_extensions", [1.272, 1.618])
                        },
                        "risk": {
                            "capital": bt_capital,
                            "risk_per_trade": bt_risk / 100.0,
                            "min_risk_reward": st.session_state.config["risk"].get("min_risk_reward", 2.0)
                        }
                    }
                    
                    # Fetch data specifically for backtester (can bypass cache)
                    # For backtester, we want clean, non-cached historical data
                    fetcher = st.session_state.data_fetcher
                    # Temporarily fetch historical data for backtester
                    df_bt = fetcher.get_historical_data(bt_symbol, interval=bt_tf, days=bt_days)
                    
                    if df_bt.empty or len(df_bt) < 50:
                        st.error("Insufficient historical bars returned for this range. Try increasing lookback days.")
                    else:
                        tester = Backtester(bt_config)
                        res = tester.run(bt_symbol, df_bt)
                        
                        # ── KPI Panels ──
                        st.markdown("##### Performance Summary")
                        col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
                        
                        with col_kpi1:
                            col_class = "delta-green" if res.total_return >= 0 else "delta-red"
                            st.markdown(f"""
                            <div class="metric-card">
                                <div class="metric-title">Total Return</div>
                                <div class="metric-value {col_class}">{res.total_return:+.1%}</div>
                                <div class="metric-delta delta-neutral">Capital: {fmt_inr(res.initial_capital)} → {fmt_inr(res.equity_curve[-1])}</div>
                            </div>
                            """, unsafe_allow_html=True)
                            
                        with col_kpi2:
                            col_class = "delta-green" if res.cagr >= 0 else "delta-red"
                            st.markdown(f"""
                            <div class="metric-card">
                                <div class="metric-title">CAGR (Est.)</div>
                                <div class="metric-value {col_class}">{res.cagr:+.1%}</div>
                                <div class="metric-delta delta-neutral">Sharpe: {res.sharpe:.2f}</div>
                            </div>
                            """, unsafe_allow_html=True)
                            
                        with col_kpi3:
                            st.markdown(f"""
                            <div class="metric-card">
                                <div class="metric-title">Max Drawdown</div>
                                <div class="metric-value delta-red">{res.max_drawdown:.1%}</div>
                                <div class="metric-delta delta-neutral">Risk Controlled</div>
                            </div>
                            """, unsafe_allow_html=True)
                            
                        with col_kpi4:
                            st.markdown(f"""
                            <div class="metric-card">
                                <div class="metric-title">Win Rate</div>
                                <div class="metric-value">{res.win_rate:.1%}</div>
                                <div class="metric-delta delta-neutral">Profit Factor: {res.profit_factor:.2f}</div>
                            </div>
                            """, unsafe_allow_html=True)
                        
                        # ── Equity Curve Chart ──
                        st.markdown("---")
                        st.markdown("##### Equity Curve & Drawdown Plot")
                        fig_bt = tester.plot_equity_curve(res)
                        st.pyplot(fig_bt, clear_figure=True)
                        
                        # ── Trades table ──
                        st.markdown("---")
                        st.markdown("##### Trades Execution Log")
                        if not res.trades:
                            st.markdown("""
                            <div style="text-align: center; padding: 30px; background: rgba(26, 29, 46, 0.3); border: 1px dashed rgba(255, 255, 255, 0.1); border-radius: 12px; color: #8c96ad;">
                                No trades executed during this backtest period. Try adjusting parameters or increasing lookback days.
                            </div>
                            """, unsafe_allow_html=True)
                        else:
                            trade_list = []
                            for t in res.trades:
                                trade_list.append({
                                    "Symbol": t.symbol,
                                    "Direction": t.direction.value,
                                    "Qty": t.qty,
                                    "Entry Price": round(t.entry_price, 2),
                                    "Exit Price": round(t.exit_price, 2) if t.exit_price else None,
                                    "Exit Reason": t.exit_reason,
                                    "PnL": round(t.pnl, 2),
                                })
                            df_trades = pd.DataFrame(trade_list)
                            st.dataframe(
                                df_trades.style.map(
                                    lambda x: "color: #00e676; font-weight: bold;" if isinstance(x, float) and x >= 0 else ("color: #ef5350; font-weight: bold;" if isinstance(x, float) and x < 0 else ""),
                                    subset=["PnL"]
                                ).format({"PnL": "₹{:,.2f}"}),
                                use_container_width=True,
                                hide_index=False
                            )
                except Exception as e:
                    st.error(f"Backtest execution failed: {e}")
                    logger.exception("Backtest failed")
        else:
            st.markdown("""
            <div style="text-align: center; padding: 80px; background: rgba(26, 29, 46, 0.2); border: 1px dashed rgba(255, 255, 255, 0.05); border-radius: 12px; color: #8c96ad; margin-top: 30px;">
                <div style="font-size: 16px; font-weight: 600; color: #ffffff;">Backtest Simulation Ready</div>
                <div style="font-size: 14px; margin-top: 5px; max-width: 400px; margin-left: auto; margin-right: auto;">Configure the parameters in the left panel and click "Run Backtest" to generate the performance simulation.</div>
            </div>
            """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: Strategy & Risk Settings (YAML Editor)
# ══════════════════════════════════════════════════════════════════════════════

with tab_config:
    st.markdown("### System Configuration")
    st.markdown("Directly adjust strategy parameters, trade sizing rules, and circuit breakers using the interactive controls below.")
    
    cfg = st.session_state.config
    
    with st.form("interactive_config_form"):
        col_strat, col_risk = st.columns(2)
        
        with col_strat:
            st.subheader("📊 Strategy Settings")
            
            timeframe_options = ["minute", "5minute", "10minute", "15minute", "30minute", "60minute", "day"]
            curr_tf = cfg["strategy"].get("timeframe", "15minute")
            tf = st.selectbox(
                "Timeframe:",
                options=timeframe_options,
                index=timeframe_options.index(curr_tf) if curr_tf in timeframe_options else 3,
                help="Bar interval for scanning and strategy signals."
            )
            
            lookback = st.number_input(
                "Lookback Candles:",
                min_value=10,
                max_value=1000,
                value=int(cfg["strategy"].get("lookback_candles", 100)),
                step=10,
                help="Number of historical candles to scan for swing points."
            )
            
            swing_thresh = st.slider(
                "Swing Threshold:",
                min_value=2,
                max_value=20,
                value=int(cfg["strategy"].get("swing_threshold", 5)),
                step=1,
                help="Required candles on both sides of a peak/trough to define a swing high/low."
            )
            
            price_tol = st.slider(
                "Price Tolerance (%):",
                min_value=0.05,
                max_value=1.50,
                value=float(cfg["strategy"].get("price_tolerance", 0.003) * 100),
                step=0.05,
                format="%.2f%%",
                help="How close the current price must be to a Fib level to qualify as near."
            ) / 100.0
            
            # --- VWAP & Pullback Strategy Upgrades ---
            use_vwap_val = st.checkbox(
                "Use VWAP Strategy:",
                value=bool(cfg["strategy"].get("use_vwap", True)),
                help="Check to calculate and enable the Volume Weighted Average Price (VWAP)."
            )
            
            vwap_filter_val = st.checkbox(
                "VWAP Trend Filter:",
                value=bool(cfg["strategy"].get("vwap_filter", True)),
                help="LONG trades only allowed above VWAP, SHORT trades only allowed below VWAP."
            )
            
            fib_zone_val = st.slider(
                "Fibonacci Entry Zone (±%):",
                min_value=0.05,
                max_value=1.50,
                value=float(cfg["strategy"].get("fib_zone", 0.002) * 100),
                step=0.05,
                format="%.2f%%",
                help="Entry zone tolerance around Fibonacci retracement levels."
            ) / 100.0
            
            conf_type = st.selectbox(
                "Confirmation Type:",
                options=["reversal_candle", "consecutive_candles"],
                index=0 if cfg["strategy"].get("confirmation_type", "reversal_candle") == "reversal_candle" else 1,
                help="Pick between a single reversal candle (Engulfing/Hammer/Marubozu) or standard consecutive candles."
            )
            
            conf_candles = st.slider(
                "Confirmation Candles:",
                min_value=1,
                max_value=5,
                value=int(cfg["strategy"].get("confirmation_candles", 2)),
                step=1,
                help="Used only if consecutive candles type is selected."
            )
            
            vol_period_val = st.number_input(
                "Volume MA Period:",
                min_value=5,
                max_value=100,
                value=int(cfg["strategy"].get("volume_period", 20)),
                step=1,
                help="Moving average lookback period to determine average volume."
            )
            
            vol_mult = st.slider(
                "Volume Multiplier:",
                min_value=0.5,
                max_value=4.0,
                value=float(cfg["strategy"].get("volume_multiplier", 1.5)),
                step=0.1,
                help="Required volume multiplier vs the average volume for confirmation."
            )
            
            min_trend = st.slider(
                "Min Trend Strength (ATR multiple):",
                min_value=0.5,
                max_value=5.0,
                value=float(cfg["strategy"].get("min_trend_strength", 2.0)),
                step=0.1,
                help="Minimum swing size divided by ATR to filter out sideways markets."
            )
            
            all_symbols = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BAJFINANCE", "WIPRO", "AXISBANK", "MARUTI"]
            curr_syms = cfg["strategy"].get("symbols", all_symbols)
            options_list = list(set(all_symbols + curr_syms))
            syms = st.multiselect(
                "Scanning Symbols:",
                options=options_list,
                default=curr_syms,
                help="List of NSE equity tickers to scan."
            )
            
        with col_risk:
            st.subheader("🛡️ Risk & Capital Settings")
            
            capital = st.number_input(
                "Trading Capital (₹):",
                min_value=1000.0,
                max_value=100000000.0,
                value=float(cfg["risk"].get("capital", 500_000)),
                step=50000.0,
                help="Base capital pool used to calculate trade sizing."
            )
            
            risk_pct = st.slider(
                "Risk Per Trade (% of Capital):",
                min_value=0.1,
                max_value=5.0,
                value=float(cfg["risk"].get("risk_per_trade", 0.01) * 100),
                step=0.1,
                format="%.1f%%",
                help="Maximum loss percentage of total capital tolerated per trade."
            ) / 100.0
            
            max_daily_loss = st.slider(
                "Max Daily Loss (% of Capital):",
                min_value=0.5,
                max_value=10.0,
                value=float(cfg["risk"].get("max_daily_loss", 0.03) * 100),
                step=0.5,
                format="%.1f%%",
                help="Circuit breaker: Halts trading if day's realized loss exceeds this limit."
            ) / 100.0
            
            max_consec_losses = st.slider(
                "Max Consecutive Losses:",
                min_value=1,
                max_value=10,
                value=int(cfg["risk"].get("max_consecutive_losses", 4)),
                step=1,
                help="Circuit breaker: Halts trading if consecutive losses hit this number."
            )
            
            max_daily_trades = st.slider(
                "Max Daily Trades:",
                min_value=1,
                max_value=30,
                value=int(cfg["risk"].get("max_daily_trades", 10)),
                step=1,
                help="Maximum number of trade entries allowed per single day."
            )
            
            min_rr = st.slider(
                "Min Risk-Reward Ratio (x):",
                min_value=1.0,
                max_value=5.0,
                value=float(cfg["risk"].get("min_risk_reward", 2.0)),
                step=0.1,
                format="%.1fx",
                help="Minimum expected reward relative to risk required to enter a trade."
            )
            
            max_conc = st.slider(
                "Max Stock Concentration (% of Capital):",
                min_value=5.0,
                max_value=100.0,
                value=float(cfg["risk"].get("max_stock_concentration", 0.2) * 100),
                step=5.0,
                format="%.0f%%",
                help="Maximum exposure allowed in a single stock ticker."
            ) / 100.0
            
            mkt_open = st.text_input(
                "Market Open Time (IST):",
                value=str(cfg["risk"].get("market_open", "09:15")),
                help="Time when trading scans can begin (HH:MM)."
            )
            
            sq_time = st.text_input(
                "Auto Squareoff Time (IST):",
                value=str(cfg["risk"].get("squareoff_time", "15:15")),
                help="Time to trigger emergency squareoff of open positions (HH:MM)."
            )

        submit_config = st.form_submit_button("Save Configuration", use_container_width=True)
        if submit_config:
            if not syms:
                st.error("You must select at least one symbol to scan!")
            else:
                try:
                    new_cfg = {
                        "strategy": {
                            "timeframe": tf,
                            "lookback_candles": lookback,
                            "swing_threshold": swing_thresh,
                            "price_tolerance": price_tol,
                            "use_vwap": use_vwap_val,
                            "vwap_filter": vwap_filter_val,
                            "fib_zone": fib_zone_val,
                            "confirmation_type": conf_type,
                            "confirmation_candles": conf_candles,
                            "volume_period": vol_period_val,
                            "volume_multiplier": vol_mult,
                            "min_trend_strength": min_trend,
                            "symbols": syms,
                            "fib_levels": cfg["strategy"].get("fib_levels", [0.382, 0.5, 0.618]),
                            "fib_extensions": cfg["strategy"].get("fib_extensions", [1.272, 1.618])
                        },
                        "risk": {
                            "capital": capital,
                            "risk_per_trade": risk_pct,
                            "max_daily_loss": max_daily_loss,
                            "max_consecutive_losses": max_consec_losses,
                            "max_daily_trades": max_daily_trades,
                            "min_risk_reward": min_rr,
                            "max_stock_concentration": max_conc,
                            "market_open": mkt_open,
                            "squareoff_time": sq_time
                        }
                    }
                    save_yaml_config(new_cfg)
                    st.session_state.config = new_cfg
                    init_trading_components()
                    st.success("Configuration updated and reloaded successfully!")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Failed to save configuration: {ex}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: Angel One Authentication
# ══════════════════════════════════════════════════════════════════════════════

with tab_auth:
    st.markdown("### Angel One SmartAPI Authentication Manager")
    st.markdown("Configure and validate your OpenAPI credentials to establish connection to Angel One servers.")
    
    st.markdown("##### 1. Validate SmartAPI Credentials")
    st.markdown("<div style='color: #8c96ad; font-size:13px; margin-bottom: 15px;'>These credentials should be loaded from your .env file for security. You can modify them here dynamically to update active credentials.</div>", unsafe_allow_html=True)
    
    api_key_val = st.text_input("Angel API Key (ANGEL_API_KEY):", value=settings.ANGEL_API_KEY or "", type="password")
    client_id_val = st.text_input("Angel Client ID (ANGEL_CLIENT_ID):", value=settings.ANGEL_CLIENT_ID or "")
    pin_val = st.text_input("Angel 4-Digit PIN (ANGEL_PIN):", value=settings.ANGEL_PIN or "", type="password")
    totp_secret_val = st.text_input("Angel TOTP Secret (ANGEL_TOTP_SECRET):", value=settings.ANGEL_TOTP_SECRET or "", type="password")
    
    test_conn_btn = st.button("Validate & Save Connection")
    
    if test_conn_btn:
        if not api_key_val or not client_id_val or not pin_val or not totp_secret_val:
            st.error("API Key, Client ID, PIN, and TOTP Secret are all required to establish a session!")
        else:
            with st.spinner("Connecting to Angel One SmartAPI servers..."):
                try:
                    from SmartApi import SmartConnect
                    import pyotp
                    
                    smart = SmartConnect(api_key=api_key_val)
                    totp_val = pyotp.TOTP(totp_secret_val).now()
                    
                    session_data = smart.generateSession(
                        clientCode=client_id_val,
                        password=pin_val,
                        totp=totp_val
                    )
                    
                    if session_data.get("status") is not True:
                        raise ValueError(session_data.get("message", "Session rejected by Angel One"))
                        
                    user_name = session_data.get("data", {}).get("name", "Trader")
                    st.success(f"Success! Connected to Angel One as {user_name}.")
                    
                    # Update .env file
                    env_path = Path(".env")
                    lines = []
                    if env_path.exists():
                        with open(env_path, "r", encoding="utf-8") as f:
                            lines = f.readlines()
                    
                    keys_to_update = {
                        "ANGEL_API_KEY": api_key_val,
                        "ANGEL_CLIENT_ID": client_id_val,
                        "ANGEL_PIN": pin_val,
                        "ANGEL_TOTP_SECRET": totp_secret_val
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
                        
                    st.toast("Credentials successfully saved to .env file!")
                    
                    # Reinitialize trading components
                    init_trading_components()
                    st.rerun()
                except Exception as ex:
                    st.error(f"Angel One connection validation failed: {ex}")
                    logger.exception("Angel connection failed")
