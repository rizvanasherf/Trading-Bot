# Fibonacci Retracement Automated Trading App

A complete, production-grade automated trading application for Indian NSE equities using a Fibonacci Retracement strategy. The app supports real-time market data scanning, virtual paper trading, live Zerodha Kite Connect order execution (MIS Intraday), performance backtesting, and instant Telegram notifications.

---

## Project Structure

```
fib_trader/
├── app.py                     # Streamlit dashboard (Live Trading, Backtest, Config, Auth)
├── config/
│   ├── settings.py            # Pydantic-settings environment variables loader
│   └── config.yaml            # Strategy & risk management parameter settings
├── core/
│   ├── data_fetcher.py        # KiteDataFetcher with caching, pagination, mock fallback
│   ├── strategy.py            # FibonacciStrategy swing & confirmation logic
│   ├── risk_manager.py        # RiskManager position sizer & circuit breakers
│   ├── order_executor.py      # OrderExecutor for Paper & Live MIS orders
│   ├── backtester.py          # Bar-by-bar Backtester with performance KPIs
│   └── notifier.py            # TelegramNotifier via httpx Bot API
├── utils/
│   ├── logger.py              # Loguru dual console & file logger (logs/trading.log)
│   └── helpers.py             # Timezone, date comparisons, and currency formatting
├── tests/
│   ├── test_strategy.py       # Unit tests for swing & Fibonacci level math
│   ├── test_risk_manager.py   # Unit tests for risk rules & position sizing
│   └── test_backtester.py     # Unit tests for backtesting loops & KPIs
├── .env.example               # Environment variables template
├── requirements.txt           # Python package dependencies
└── README.md                  # Detailed documentation (this file)
```

---

## Key Features

1. **Dual Trading Mode**:
   - `paper`: Tracks open and closed positions in-memory, updating PnL via simulated ticks.
   - `live`: Places MIS market entry orders and matching limit target/stop-loss orders using the Angel One SmartAPI.
2. **Advanced Strategy & Regime Filters**:
   - **ADX Trend Regime Filter**: Automatically scans the average directional index; suppresses Fibonacci trades in range-bound/choppy markets (ADX < 20) to prevent whipsaw losses.
   - **Fibonacci Retracement Logic**: Calculates real-time swing highs and lows, Fibonacci levels (38.2%, 50%, 61.8%), and target extensions.
3. **Smart Position Sizing & Risk Controls**:
   - **Volatility-Adjusted Sizing**: Automatically reduces trade size using ATR ratio when asset volatility spikes.
   - **Rigorous Circuit Breakers**: Halts trading upon breaching daily loss limits, maximum trades limit, or consecutive losses. Auto-squares off at 3:15 PM IST.
4. **Execution State Machine & Idempotency**:
   - **Order Confirmation Loop**: Defers Stop-Loss and Target orders until live entry orders are confirmed as fully filled (complete). Automatically cancels entry if pending > 5 mins.
   - **Deduplication Tracker**: Saves executed signal keys to a local `logs/placed_signals.json` database to avoid double-placing trades on restarts.
5. **Interactive Dashboard**:
   - Real-time card grids for performance statistics.
   - Interactive candlestick charts with volume histograms and indicators.
   - Steps manager for broker logins and access token saves.

---

## Setup & Installation

### 1. Prerequisites
- Python 3.10 or higher.
- A Zerodha Kite Connect API account (Base API + Historical API subscriptions required for live trading).

### 2. Installation
Clone/copy the workspace directory and install dependencies:
```bash
# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration
Create a `.env` file in the root directory:
```bash
copy .env.example .env
```
Open `.env` and fill in your credentials:
```ini
KITE_API_KEY=your_api_key
KITE_API_SECRET=your_api_secret
KITE_ACCESS_TOKEN=your_access_token # Generated daily via Auth page
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TRADING_MODE=paper
```

### 4. Running the Dashboard
Start the Streamlit application:
```bash
streamlit run app.py
```
Visit `http://localhost:8501` in your browser.

---

## Running the Application

### Live Trading Dashboard
- Click **Start Live Scanning** to initiate the tick loop (refreshes every 10 seconds).
- The system checks for entry signals across the symbol list.
- If a signal matches, it calculates the position size, places the trade, and emits Telegram notifications.
- View real-time position values and PnL, with emergency manual square-off actions.

### Backtesting
- Navigate to the **Historical Backtesting** tab.
- Choose a stock symbol, timeframe, and lookback range.
- Run the backtest to calculate metrics: CAGR, Sharpe Ratio, Win Rate, Profit Factor, and Max Drawdown.
- Review the equity curve and drawdown charts along with a table of historical trades.

---

## Running Unit Tests

Execute the automated test suite using `pytest`:
```bash
pytest -v
```
These tests cover all aspects of level calculation, swing peaks, circuit breakers, position allocations, and backtester iterations.
