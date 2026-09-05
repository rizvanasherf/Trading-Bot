# Multi-Strategy Automated Trading Application (v2)

A complete, production-grade automated trading application for Indian NSE equities and index options using the **Angel One SmartAPI**. The application supports real-time concurrent market scanning, live option & equity trade signals, virtual paper trading, live order execution (MIS Intraday), granular per-bar condition diagnostics, advanced risk controls, and Telegram notifications.

---

## Supported Strategies

1. **CPR Intraday Strategy (`cpr_intraday`)**:
   - Specifically engineered for **NIFTY 50 Options Trading**.
   - Calculates daily Central Pivot Range (CPR) levels (TC, Pivot P, BC), 20 EMA, VWAP, and ATM option strikes.
   - Generates automated **Buy CE** (Call Option) and **Buy PE** (Put Option) trade signals based on 2-candle bias lock confirmation.

2. **Opening Range Breakout (`orb`)**:
   - Designed for high-volatility intraday stocks.
   - Defines the initial 15-minute Opening Range (High/Low).
   - Validates breakout signals using volume multipliers, 15m RSI momentum filter, and VWAP alignment.

> [!NOTE]
> Obsolete strategies (`fibonacci` and `vwap_pullback`) have been removed from the application engine to maintain lean, high-performance execution.

---

## Project Structure

```
Trading-Bot/
├── server.py                  # FastAPI backend server (concurrent scanner & APIs)
├── Dockerfile                 # Multi-stage production container build
├── docker-compose.yml         # Container orchestration (Backend + Nginx Frontend)
├── nginx.conf                 # Reverse proxy configuration for UI & API requests
├── frontend/                  # React + Vite web dashboard application
│   ├── src/
│   │   ├── App.jsx            # Main dashboard tabs, settings & state
│   │   └── components/
│   │       ├── AnalysisDashboard.jsx # Performance charts & calendar
│   │       ├── FibonacciChart.jsx    # Interactive candlestick chart
│   │       └── Logo.jsx              # App branding component
├── config/
│   ├── settings.py            # Pydantic-settings environment variables loader
│   └── config.yaml            # Strategy parameters & risk management settings
├── core/
│   ├── data_fetcher.py        # KiteDataFetcher wraps Angel One SmartAPI & Yahoo Finance
│   ├── strategy.py            # Shared signal models (Direction, Signal, FibLevels)
│   ├── orb_strategy.py        # Opening Range Breakout Strategy engine
│   ├── cpr_strategy.py        # NIFTY Options CPR strategy engine
│   ├── risk_manager.py        # RiskManager position sizer & circuit breakers
│   ├── order_executor.py      # OrderExecutor for Paper & Live MIS orders
│   ├── backtester.py          # Bar-by-bar historical strategy simulator
│   └── notifier.py            # TelegramNotifier via httpx Bot API
├── src/
│   └── data/
│       ├── angel_connector.py # Handles Angel One session connection
│       ├── session_manager.py # Automated daily sessions & reconnection (AB1010)
│       └── quote_fetcher.py   # Batch quotes fetcher with rate limit protection
├── tests/                     # Unit test suite (42/42 pytest tests)
├── requirements.txt           # Python dependencies
└── README.md                  # Application documentation
```

---

## Key Features & User Interface Architecture

### 1. Reorganized Dashboard & Navigation

- **Tab 1 — Live Dashboard**:
  - Financial KPI summary tiles (**Total Equity**, **Free Margin**, **Live Daily P&L**, **Trade Limits & Win Rate**).
  - Streamlined **System Overview Card** showing execution mode (`PAPER`/`LIVE`) and active primary strategy.

- **Tab 2 — Live Strategies**:
  - **Active Triggers**: Per-bar condition diagnostics with visual pass (`✓`) / fail (`✗`) indicator pills for Bias, EMA, RSI 15m, Volume Ratio, VWAP, and exact Risk Gate failure reason strings.
  - **CPR Intraday Options Monitor**: NIFTY Spot Index, Pivot Levels (TC, Pivot P, BC), Intraday Technicals (VWAP, EMA 20), ATM strikes, and active option signals (`Buy CE` / `Buy PE`).
  - **Current Positions Table**: Active trades grid with live LTP, P&L, stop loss, target, and one-click manual **Exit / Squareoff** buttons.
  - **Interactive Level Chart View**: Candlestick chart view with symbol selection.

- **Tab 3 — Data Analysis**:
  - Interactive **Equity Curve Line Chart** with hover tooltips.
  - Performance KPIs: **Sharpe Ratio, Profit Factor, Max Drawdown %, Win Rate**.
  - **Daily Returns Calendar**: Color-coded calendar showing daily profits/losses.

- **Tab 4 — Trade History**:
  - Search by symbol with dropdown filters for trade direction (`LONG`, `SHORT`) and exit reason (`SL`, `Target`, `Squareoff`).
  - Pagination (10 rows per page) and **CSV Export** button (`trade_history.csv`).

- **Tab 5 — System Settings**:
  - Strategy parameters & risk management control center.

### 2. Risk Management & Circuit Breakers

- **Exact Risk Gate Logging**: Whenever `risk_manager.can_trade()` blocks a trade attempt, the exact reason is logged (e.g. `Market closed for new entries`, `Max daily loss reached`, `Trade limit reached`).
- **Circuit Breaker Resiliency**: When daily risk limits are reached, new entries are blocked while **exit monitoring and trailing SL checks remain active** for existing positions.
- **Quick Exit (Panic Switch)**: Instant one-click exit to square off all open positions and cancel pending orders.

---

## Setup & Local Installation

### 1. Prerequisites
- Python 3.10 or higher.
- Node.js & npm (for React frontend).
- Angel One SmartAPI credentials (API Key, Client ID, PIN, TOTP secret).

### 2. Environment Configuration
Create a `.env` file in the root directory:
```ini
ANGEL_API_KEY=your_api_key_here
ANGEL_CLIENT_ID=your_client_id_here
ANGEL_PIN=your_4_digit_pin_here
ANGEL_TOTP_SECRET=your_totp_secret_key_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
TRADING_MODE=paper # "paper" (virtual) or "live" (real orders)
DATABASE_URL=sqlite:///config/trading_bot.db
```

### 3. Running Locally

**Start Backend Server:**
```bash
python server.py
```
*(Server runs at `http://localhost:8000`)*

**Start Frontend Development Server:**
```bash
cd frontend
npm install
npm run dev
```
*(Dashboard opens at `http://localhost:5173`)*

---

## AWS EC2 & Docker Deployment

### 1. Deploying via Docker Compose

```bash
# Pull latest code
git pull origin v2-development

# Rebuild and start containers in background
docker compose down
docker compose build --no-cache
docker compose up -d
```

### 2. Monitoring Container Logs
```bash
docker compose logs -f --tail=100
```

---

## Running Unit Tests

Execute the automated test suite using `pytest`:
```bash
python -m pytest
```
All **42 automated unit tests** verify CPR calculations, ORB breakout conditions, risk management constraints, idempotency tracking, and session lifecycle events.
