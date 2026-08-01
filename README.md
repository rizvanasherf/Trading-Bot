# Multi-Strategy Automated Trading App (Version 2)

A complete, production-grade automated trading application for Indian NSE equities and index options using the **Angel One SmartAPI**. The application supports real-time concurrent market scanning (Fibonacci, ORB, CPR Intraday, and VWAP Pullback strategies), virtual paper trading, live order execution (MIS Intraday), advanced risk controls, backtesting analytics, and Telegram notifications.

---

## Project Structure

```
Trading-Bot/
├── server.py                  # FastAPI backend server (concurrent scanner & APIs)
├── frontend/                  # React + Vite web dashboard application
│   ├── src/
│   │   ├── App.jsx            # Main dashboard container & settings
│   │   └── components/
│   │       └── AnalysisDashboard.jsx # Interactive performance charts & calendar
├── config/
│   ├── settings.py            # Pydantic-settings environment variables loader
│   └── config.yaml            # Strategy parameters & risk management settings
├── core/
│   ├── data_fetcher.py        # KiteDataFetcher wraps Angel One SmartAPI & Yahoo Finance
│   ├── strategy.py            # FibonacciStrategy swing & confirmation logic
│   ├── orb_strategy.py        # Opening Range Breakout Strategy logic
│   ├── cpr_strategy.py        # Nifty Options CPR strategy logic
│   ├── vwap_pullback_strategy.py # VWAP Pullback Strategy logic
│   ├── risk_manager.py        # RiskManager position sizer & circuit breakers
│   ├── order_executor.py      # OrderExecutor for Paper & Live MIS orders
│   ├── backtester.py          # Bar-by-bar Backtester with concentration limits
│   └── notifier.py            # TelegramNotifier via httpx Bot API
├── src/
│   └── data/
│       ├── angel_connector.py # Handles Angel One session connection
│       ├── session_manager.py # Automated daily sessions & reconnection (AB1010)
│       └── quote_fetcher.py   # Batch quotes fetcher with rate limit protection
├── tests/                     # Unit test suites (pytest)
├── requirements.txt           # Python package dependencies
└── README.md                  # Comprehensive documentation (this file)
```

---

## Key Version 2 (v2) Features

1. **Dedicated Trade History & Advanced Filtering**:
   - A dedicated history navigation tab that holds all completed trades, keeping the home dashboard decluttered.
   - Dynamic search by symbol, along with dropdown filters for trade direction (LONG, SHORT) and exit reason (SL, Target, Squareoff).
   - Pagination (10 rows per page) to handle high-frequency trade logs cleanly.
   - **CSV Exports**: One-click button to download `trade_history.csv` directly from the UI.

2. **Interactive Performance Analytics Dashboard**:
   - Custom SVG **Equity Curve Line Chart** plotting trade-by-trade cumulative return with interactive hover tooltips.
   - Auto-calculated trading KPIs: **Sharpe Ratio, Profit Factor, Max Drawdown %, and Win/Loss Ratio**.
   - **Daily Returns Calendar**: Color-coded calendar showing green/red daily profits/losses with mouseover tooltips.

3. **Multi-Strategy Scanner & Execution Engine**:
   - Concurrent scanning of multiple stocks and indices using a thread pool.
   - Strategies supported: **Fibonacci Retracement, CPR Intraday (CE/PE options), Opening Range Breakout (ORB), and VWAP Pullback**.
   - **ADX Trend Filter**: Suppresses Fibonacci trades in range-bound markets (ADX < 20).
   - **Volatility-Adjusted Position Sizing**: Reduces quantity using the ATR ratio during high volatility.
   - **Restart Protection**: Deduplication tracker saves placed signals to `placed_signals.json` to prevent duplicate orders upon restart.

4. **Production-Grade Security & Session Safeguards**:
   - **Circuit Breaker Resiliency**: When a daily risk limit (max trades or loss cap) is breached, the bot blocks new signals but **continues to run exit checks and auto-squareoffs for active trades**.
   - **Smart Session Recovery**: Intercepts session errors (`AB1010`, invalid token, or expired login) and auto-reconnects in the background.
   - **Quotes Fallback**: Seamless fallback to Yahoo Finance quotes if Angel One APIs hit rate limits or go offline.

---

## Setup & Installation

### 1. Prerequisites
- Python 3.10 or higher.
- Node.js & npm (for the React dashboard).
- An Angel One SmartAPI developer account (API Key, Client ID, PIN, and TOTP secret key).

### 2. Installation
Install python dependencies in your workspace:
```bash
pip install -r requirements.txt
```

### 3. Environment Configuration
Create a `.env` file in the root directory:
```bash
copy .env.example .env
```
Fill in your credentials:
```ini
ANGEL_API_KEY=your_api_key_here
ANGEL_CLIENT_ID=your_client_id_here
ANGEL_PIN=your_4_digit_pin_here
ANGEL_TOTP_SECRET=your_totp_secret_key_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
TRADING_MODE=paper # "paper" (virtual) or "live" (real orders to Angel One)

# Optional database URL (defaults to sqlite:///config/trading_bot.db if omitted)
DATABASE_URL=sqlite:///config/trading_bot.db
```

### 4. Running the Application

First, start the FastAPI backend server:
```bash
python server.py
```
The server runs at `http://localhost:8000`.

Next, start the Vite development server for the UI:
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` to access the dashboard.

---

## Running Unit Tests

Execute the automated test suite using `pytest`:
```bash
pytest -v
```
All tests check CPR calculations, swing high/low logic, risk management constraints, backtester calculations, and session lifecycle events.
