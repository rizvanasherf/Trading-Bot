import React, { useState, useEffect, useCallback } from 'react';
import { 
  Play, Square, RefreshCw, BarChart2, Shield, Settings, Key, 
  ArrowUpRight, ArrowDownRight, Activity, TrendingUp, 
  CheckCircle, Clock, Save, FileText, Globe, PieChart, Wallet
} from 'lucide-react';
import FibonacciChart from './components/FibonacciChart';
import AnalysisDashboard from './components/AnalysisDashboard';
import './App.css';

const API_BASE = 'http://127.0.0.1:8000/api';

const renderDateTime = (dtStr) => {
  if (!dtStr || dtStr === "N/A") return <span>N/A</span>;
  const parts = dtStr.split(" ");
  return (
    <div>
      <div style={{ fontWeight: 500, whiteSpace: 'nowrap' }}>{parts[0]}</div>
      <div style={{ color: '#8a90a6', fontSize: '11px', marginTop: '2px' }}>{parts[1]}</div>
    </div>
  );
};

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [status, setStatus] = useState({
    scanning_active: false,
    is_live: false,
    trading_mode: 'paper',
    api_connected: false,
    api_status: 'Checking...',
    last_checked: ''
  });
  
  const [metrics, setMetrics] = useState({
    capital: 0,
    formatted_capital: '₹0.00',
    total_equity: 0,
    formatted_equity: '₹0.00',
    available_margin: 0,
    formatted_available: '₹0.00',
    used_margin: 0,
    formatted_used: '₹0.00',
    margin_utilization_pct: 0,
    realized_pnl: 0,
    formatted_realized: '₹0.00',
    unrealized_pnl: 0,
    formatted_unrealized: '₹0.00',
    total_pnl: 0,
    formatted_pnl: '₹0.00',
    pnl_pct: 0,
    win_rate: 0,
    formatted_win_rate: '0.0%',
    winners: 0,
    losers: 0,
    trades_count: 0,
    trades_limit: 10,
    consecutive_losses: 0
  });

  const [positions, setPositions] = useState([]);
  const [trades, setTrades] = useState([]);
  const [selectedPeriod, setSelectedPeriod] = useState("Today's Trades");
  
  // Config Form state
  const [config, setConfig] = useState({
    risk: {
      capital: 50000,
      risk_per_trade: 0.01,
      max_daily_loss: 0.03,
      max_consecutive_losses: 3,
      max_daily_trades: 5,
      min_risk_reward: 2.5,
      max_stock_concentration: 0.2,
      market_open: "09:30",
      squareoff_time: "15:15"
    },
    strategy: {
      strategy_type: "fibonacci",
      timeframe: "15minute",
      lookback_candles: 150,
      swing_threshold: 4,
      fib_levels: [0.382, 0.5, 0.618],
      fib_extensions: [1.272, 1.618],
      fib_zone: 0.0025,
      price_tolerance: 0.0025,
      use_vwap: true,
      vwap_filter: true,
      confirmation_type: "reversal_candle",
      confirmation_candles: 1,
      volume_period: 20,
      volume_multiplier: 1.3,
      min_trend_strength: 2.5,
      symbols: ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BAJFINANCE", "AXISBANK"]
    },
    orb: {
      start_time: "09:15",
      end_time: "09:30",
      volume_period: 20,
      volume_multiplier: 1.3,
      use_vwap_filter: true,
      target_multiplier: 1.5,
      max_range_pct: 0.02,
      min_range_pct: 0.001
    },
    vwap_pullback: {
      ema_period: 9,
      vwap_buffer_pct: 0.0015,
      volume_period: 20,
      volume_multiplier: 1.2,
      stop_loss_pct: 0.005,
      lookback_swings: 20
    }
  });

  // Chart state
  const [chartSymbol, setChartSymbol] = useState('');
  const [chartData, setChartData] = useState(null);
  const [diagnostics, setDiagnostics] = useState({
    total_api_calls: 0,
    cache_hits: 0,
    cache_misses: 0,
    rate_limit_waits: 0,
    circuit_breaker_trips: 0,
    hit_ratio_pct: 0,
    reconnects_scheduled: 0,
    session_active: false
  });

  const [btParams, setBtParams] = useState({
    strategy_type: 'compare_all',
    symbol: 'RELIANCE',
    timeframe: '15minute',
    days: 30,
    capital: 500000,
    risk: 1.0
  });
  const [btResults, setBtResults] = useState(null);
  const [btLoading, setBtLoading] = useState(false);

  // Auth Form State
  const [authData, setAuthData] = useState({
    api_key: '',
    client_id: '',
    pin: '',
    totp_secret: ''
  });

  // Alert State
  const [alert, setAlert] = useState(null);

  const triggerAlert = (type, message) => {
    setAlert({ type, message });
    setTimeout(() => setAlert(null), 5000);
  };

  // ── Fetch Operations ──────────────────────────────────────────────────────

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/status`);
      const data = await res.json();
      setStatus(data);
    } catch (e) {
      console.error("Error fetching status:", e);
    }
  }, []);

  const fetchDiagnostics = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/diagnostics`);
      const data = await res.json();
      setDiagnostics(data);
    } catch (e) {
      console.error("Error fetching diagnostics:", e);
    }
  }, []);

  const fetchMetrics = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/metrics`);
      const data = await res.json();
      setMetrics(data);
    } catch (e) {
      console.error("Error fetching metrics:", e);
    }
  }, []);

  const fetchPositions = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/positions`);
      const data = await res.json();
      setPositions(data);
    } catch (e) {
      console.error("Error fetching positions:", e);
    }
  }, []);

  const fetchTrades = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/trades?period=${encodeURIComponent(selectedPeriod)}`);
      const data = await res.json();
      setTrades(data);
    } catch (e) {
      console.error("Error fetching trades:", e);
    }
  }, [selectedPeriod]);

  const fetchConfig = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/config`);
      const data = await res.json();
      setConfig(data);
      if (data.strategy?.symbols?.length > 0 && !chartSymbol) {
        setChartSymbol(data.strategy.symbols[0]);
      }
    } catch (e) {
      console.error("Error fetching config:", e);
    }
  }, [chartSymbol]);

  const fetchChart = useCallback(async () => {
    if (!chartSymbol) return;
    try {
      const res = await fetch(`${API_BASE}/chart/${chartSymbol}`);
      const data = await res.json();
      setChartData(data);
    } catch (e) {
      console.error("Error fetching chart:", e);
    }
  }, [chartSymbol]);

  // Periodic Polling
  useEffect(() => {
    fetchStatus();
    fetchDiagnostics();
    fetchMetrics();
    fetchPositions();
    fetchTrades();
    fetchConfig();
  }, [fetchStatus, fetchDiagnostics, fetchMetrics, fetchPositions, fetchTrades, fetchConfig]);

  useEffect(() => {
    const timer = setInterval(() => {
      fetchStatus();
      fetchDiagnostics();
      fetchMetrics();
      fetchPositions();
      fetchTrades();
    }, 10000);
    return () => clearInterval(timer);
  }, [fetchStatus, fetchDiagnostics, fetchMetrics, fetchPositions, fetchTrades]);

  useEffect(() => {
    if (activeTab !== 'dashboard') return;
    const timer = setInterval(() => {
      fetchChart();
    }, 30000);
    return () => clearInterval(timer);
  }, [activeTab, fetchChart]);

  // Load chart when tab is active or selected symbol changes
  useEffect(() => {
    if (activeTab === 'dashboard' && chartSymbol) {
      fetchChart();
    }
  }, [activeTab, chartSymbol, fetchChart]);

  // ── Actions ───────────────────────────────────────────────────────────────

  const toggleScanner = async () => {
    const endpoint = status.scanning_active ? 'stop' : 'start';
    try {
      const res = await fetch(`${API_BASE}/scanner/${endpoint}`, { method: 'POST' });
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Failed to toggle scanner.");
      }
      fetchStatus();
      triggerAlert('success', `Live scanning ${endpoint === 'start' ? 'activated' : 'deactivated'}.`);
    } catch (e) {
      triggerAlert('error', e.message);
    }
  };

  const toggleMode = async () => {
    try {
      const res = await fetch(`${API_BASE}/mode/toggle`, { method: 'POST' });
      const data = await res.json();
      fetchStatus();
      fetchMetrics();
      triggerAlert('success', `Switched trading mode to ${data.trading_mode.toUpperCase()}`);
    } catch (e) {
      triggerAlert('error', "Failed to switch trading mode.");
    }
  };

  const squareoffPosition = async (id, symbol) => {
    try {
      const res = await fetch(`${API_BASE}/positions/${id}/squareoff`, { method: 'POST' });
      if (!res.ok) throw new Error("Failed to execute squareoff.");
      fetchPositions();
      fetchMetrics();
      fetchTrades();
      triggerAlert('success', `Position for ${symbol} successfully squared off.`);
    } catch (e) {
      triggerAlert('error', e.message);
    }
  };

  const triggerPanicClose = async () => {
    const confirmClose = window.confirm("WARNING: Clicking this will instantly close ALL open positions at market price and cancel all pending orders. Are you sure you want to proceed?");
    if (!confirmClose) return;

    try {
      const res = await fetch(`${API_BASE}/panic`, {
        method: 'POST'
      });
      const data = await res.json();
      if (data.status === 'success') {
        triggerAlert('success', `PANIC SWITCH ACTIVATED: Successfully closed ${data.closed_positions} positions and cancelled all open orders.`);
        fetchPositions();
        fetchTrades();
        fetchMetrics();
      } else {
        triggerAlert('error', `Panic execution failed: ${data.detail}`);
      }
    } catch (e) {
      triggerAlert('error', `Network error triggering panic switch: ${e.message}`);
    }
  };

  const clearTrades = async () => {
    const confirmClear = window.confirm("Are you sure you want to clear all active positions, completed trade logs, and reset dashboard statistics? This cannot be undone.");
    if (!confirmClear) return;

    try {
      const res = await fetch(`${API_BASE}/trades/clear`, {
        method: 'POST'
      });
      if (!res.ok) throw new Error("Failed to clear trade history.");
      triggerAlert('success', "Trade history and statistics successfully cleared!");
      fetchPositions();
      fetchTrades();
      fetchMetrics();
    } catch (e) {
      triggerAlert('error', e.message);
    }
  };

  const saveConfig = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });
      if (!res.ok) throw new Error("Could not save settings.");
      fetchConfig();
      fetchMetrics();
      triggerAlert('success', "Strategy & Risk configurations successfully saved and reloaded!");
    } catch (e) {
      triggerAlert('error', e.message);
    }
  };

  const runBacktest = async () => {
    if (btParams.strategy_type === 'compare_all') {
      await runMultiStrategyComparison();
      return;
    }
    setBtLoading(true);
    setBtResults(null);
    try {
      const res = await fetch(`${API_BASE}/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(btParams)
      });
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Backtest simulation failed.");
      }
      const data = await res.json();
      setBtResults(data);
      triggerAlert('success', `Backtest simulation complete for ${btParams.symbol}!`);
    } catch (e) {
      triggerAlert('error', e.message);
    } finally {
      setBtLoading(false);
    }
  };

  const runMultiStrategyComparison = async () => {
    setBtLoading(true);
    setBtResults(null);
    try {
      const strategies = ["fibonacci", "orb", "vwap_pullback"];
      const promises = strategies.map(async (stratType) => {
        const res = await fetch(`${API_BASE}/backtest`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...btParams,
            strategy_type: stratType
          })
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || `Backtest failed for strategy: ${stratType}`);
        }
        const data = await res.json();
        return { stratType, data };
      });
      
      const resultsArray = await Promise.all(promises);
      
      const combined = {
        isComparison: true,
        symbol: btParams.symbol,
        initial_capital: btParams.capital,
        strategies: {}
      };
      
      resultsArray.forEach(({ stratType, data }) => {
        combined.strategies[stratType] = data;
      });
      
      setBtResults(combined);
      triggerAlert('success', `Comparison complete for all 3 strategies!`);
    } catch (e) {
      triggerAlert('error', e.message);
    } finally {
      setBtLoading(false);
    }
  };

  const generateAuthToken = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/auth-callback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(authData)
      });
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Authentication handshake failed.");
      }
      const data = await res.json();
      fetchStatus();
      triggerAlert('success', `Successfully authenticated Angel One session for ${data.user_name}!`);
    } catch (e) {
      triggerAlert('error', e.message);
    }
  };

  return (
    <div className="app-container">
      {/* Sidebar Navigation */}
      <aside className="sidebar">
        <div className="logo-section">
          <TrendingUp className="logo-icon" />
          <span className="logo-text">FIB TRADER</span>
        </div>
        
        <nav className="nav-links">
          <button 
            className={`nav-item ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => setActiveTab('dashboard')}
          >
            <Activity size={18} />
            Live Dashboard
          </button>
          
          <button 
            className={`nav-item ${activeTab === 'backtest' ? 'active' : ''}`}
            onClick={() => setActiveTab('backtest')}
          >
            <BarChart2 size={18} />
            Backtest Simulator
          </button>
          
          <button 
            className={`nav-item ${activeTab === 'analysis' ? 'active' : ''}`}
            onClick={() => setActiveTab('analysis')}
          >
            <PieChart size={18} />
            Data Analysis
          </button>
          
          <button 
            className={`nav-item ${activeTab === 'settings' ? 'active' : ''}`}
            onClick={() => setActiveTab('settings')}
          >
            <Settings size={18} />
            System Settings
          </button>
          
          <button 
            className={`nav-item ${activeTab === 'auth' ? 'active' : ''}`}
            onClick={() => setActiveTab('auth')}
          >
            <Key size={18} />
            Angel One Auth
          </button>
        </nav>
        
        <div className="sidebar-footer" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div 
            onClick={toggleMode} 
            style={{ 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'space-between', 
              background: 'rgba(255,255,255,0.03)', 
              padding: '10px 14px', 
              borderRadius: '24px', 
              cursor: 'pointer', 
              border: '1px solid rgba(255,255,255,0.08)',
              userSelect: 'none',
              transition: 'all 0.2s ease',
              width: '100%'
            }}
            title="Click to toggle trading mode"
          >
            <span style={{ fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', color: status.trading_mode === 'paper' ? '#00d2ff' : '#8f8c96', transition: 'color 0.2s' }}>Paper</span>
            
            <div style={{ 
              width: '36px', 
              height: '18px', 
              background: status.trading_mode === 'live' ? 'rgba(255, 23, 68, 0.15)' : 'rgba(0, 210, 255, 0.15)', 
              border: status.trading_mode === 'live' ? '1px solid #ff1744' : '1px solid #00d2ff',
              borderRadius: '9px', 
              position: 'relative', 
              transition: 'all 0.2s ease',
              margin: '0 8px'
            }}>
              <div style={{ 
                width: '12px', 
                height: '12px', 
                background: status.trading_mode === 'live' ? '#ff1744' : '#00d2ff', 
                borderRadius: '50%', 
                position: 'absolute', 
                top: '2px', 
                left: status.trading_mode === 'live' ? '20px' : '2px', 
                transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                boxShadow: status.trading_mode === 'live' ? '0 0 8px #ff1744' : '0 0 8px #00d2ff'
              }} />
            </div>
            
            <span style={{ fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', color: status.trading_mode === 'live' ? '#ff1744' : '#8f8c96', transition: 'color 0.2s' }}>Live</span>
          </div>
          <button 
            className="btn"
            onClick={triggerPanicClose}
            style={{ 
              background: '#2b1010', 
              color: '#ff5252', 
              border: '1px solid #5a1c1c', 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'center',
              gap: '6px', 
              fontWeight: 600,
              padding: '10px 12px',
              fontSize: '13px',
              borderRadius: '6px',
              width: '100%',
              cursor: 'pointer',
              transition: 'all 0.2s ease'
            }}
          >
            <Shield size={14} />
            Quick Exit
          </button>
        </div>
      </aside>

      {/* Main Panel */}
      <main className="main-content">
        {alert && (
          <div className={`alert alert-${alert.type}`}>
            {alert.message}
          </div>
        )}

        {/* Topbar System Status Bar */}
        <header className="topbar">
          <div className="status-group">
            <div className="status-indicator">
              <span className="status-label">Scanner Status</span>
              <span className="status-value">
                <span className={`dot ${status.scanning_active ? 'green' : 'red'}`}></span>
                {status.scanning_active ? 'Scanning Active' : 'Paused'}
              </span>
            </div>
            
            <div className="status-indicator">
              <span className="status-label">Angel One API</span>
              <span className="status-value">
                <span className={`dot ${status.api_connected ? 'green' : 'amber'}`}></span>
                {status.api_status}
              </span>
            </div>
            
            <div className="status-indicator">
              <span className="status-label">Last Evaluated</span>
              <span className="status-value">
                <Clock size={16} style={{ color: '#8a90a6' }} />
                {status.last_checked || 'Waiting...'}
              </span>
            </div>
          </div>
          
          <div className="control-actions" style={{ display: 'flex', gap: '10px' }}>
            <button 
              className="btn btn-primary"
              onClick={toggleScanner}
            >
              {status.scanning_active ? <Square size={16} /> : <Play size={16} />}
              {status.scanning_active ? 'Stop Scanning' : 'Start Scanning'}
            </button>
          </div>
        </header>

        {/* Dynamic Panels */}
        
        {/* TAB 1: Live Dashboard */}
        {activeTab === 'dashboard' && (
          <>
            {/* KPI Cards Row */}
            <div className="metrics-grid">
              {/* Card 1: Total Equity */}
              <div className="live-metric-card">
                <div className="live-icon-box cyan">
                  <Wallet size={20} />
                </div>
                <div className="live-metric-text">
                  <span className="live-metric-label">Total Equity</span>
                  <span className="live-metric-val">{metrics.formatted_equity}</span>
                  <span className="live-metric-subtext">Capital: {metrics.formatted_capital}</span>
                </div>
              </div>

              {/* Card 2: Free Margin */}
              <div className="live-metric-card">
                <div className="live-icon-box cyan">
                  <Shield size={20} />
                </div>
                <div className="live-metric-text">
                  <span className="live-metric-label">Free Margin</span>
                  <span className="live-metric-val">{metrics.formatted_available}</span>
                  <span className="live-metric-subtext">
                    Utilized: {metrics.margin_utilization_pct}% ({metrics.formatted_used})
                  </span>
                </div>
              </div>

              {/* Card 3: Live Daily P&L */}
              <div className="live-metric-card">
                <div className={`live-icon-box ${metrics.total_pnl > 0 ? 'green' : metrics.total_pnl < 0 ? 'red' : ''}`}>
                  <TrendingUp size={20} />
                </div>
                <div className="live-metric-text">
                  <span className="live-metric-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    Live Daily P&L
                    {metrics.unrealized_pnl !== 0 && (
                      <span className="live-pulse-dot" style={{
                        width: '6px',
                        height: '6px',
                        background: metrics.unrealized_pnl >= 0 ? '#00e676' : '#ff1744',
                        borderRadius: '50%',
                        display: 'inline-block',
                        boxShadow: `0 0 8px ${metrics.unrealized_pnl >= 0 ? '#00e676' : '#ff1744'}`
                      }} />
                    )}
                  </span>
                  <span className="live-metric-val" style={{ color: metrics.total_pnl > 0 ? '#00e676' : metrics.total_pnl < 0 ? '#ff1744' : '#ffffff' }}>
                    {metrics.formatted_pnl}
                  </span>
                  <span className="live-metric-subtext">
                    Realized: {metrics.formatted_realized} | Unrealized: {metrics.formatted_unrealized}
                  </span>
                </div>
              </div>

              {/* Card 4: Trade Limits */}
              <div className="live-metric-card">
                <div className="live-icon-box amber">
                  <Activity size={20} />
                </div>
                <div className="live-metric-text">
                  <span className="live-metric-label">Trade Limits</span>
                  <span className="live-metric-val">
                    {metrics.trades_count} / {metrics.trades_limit} Trades
                  </span>
                  <span className="live-metric-subtext">
                    Win Rate: {metrics.formatted_win_rate} ({metrics.winners}W - {metrics.losers}L)
                  </span>
                </div>
              </div>
            </div>

            {/* Open Positions Grid */}
            <div className="card-panel">
              <div className="panel-header">
                <h3 className="panel-title">
                  <Activity size={18} style={{ color: '#2979ff' }} />
                  Current Positions
                </h3>
              </div>
              
              {positions.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '40px 0', color: '#8a90a6' }}>
                  No active open positions.
                </div>
              ) : (
                <div className="table-container">
                  <table className="custom-table">
                    <thead>
                      <tr>
                        <th>Symbol</th>
                        <th>Direction</th>
                        <th>Qty</th>
                        <th>Entry Price</th>
                        <th>LTP</th>
                        <th>Stop Loss</th>
                        <th>Target</th>
                        <th>Unrealised P&L</th>
                        <th>Entry Time</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions.map(p => (
                        <tr key={p.id}>
                          <td style={{ fontWeight: 700 }}>{p.symbol}</td>
                          <td>
                            <span className={`badge ${p.direction === 'LONG' ? 'badge-green' : 'badge-red'}`}>
                              {p.direction}
                            </span>
                          </td>
                          <td>{p.qty}</td>
                          <td>₹{p.entry_price.toFixed(2)}</td>
                          <td>₹{p.ltp.toFixed(2)}</td>
                          <td style={{ color: '#ff1744' }}>₹{p.stop_loss.toFixed(2)}</td>
                          <td style={{ color: '#00e676' }}>₹{p.target.toFixed(2)}</td>
                          <td style={{ fontWeight: 700, color: p.pnl >= 0 ? '#00e676' : '#ff1744' }}>
                            ₹{p.pnl.toFixed(2)}
                          </td>
                          <td>{p.entry_time}</td>
                          <td>
                            <button 
                              className="btn btn-danger"
                              style={{ padding: '6px 12px', fontSize: '12px' }}
                              onClick={() => squareoffPosition(p.id, p.symbol)}
                            >
                              Exit
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Completed Trades Log */}
            <div className="card-panel">
              <div className="panel-header">
                <h3 className="panel-title">
                  <FileText size={18} style={{ color: '#ffd54f' }} />
                  Completed Trades History
                </h3>
                
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                  <select 
                    className="input-control"
                    value={selectedPeriod}
                    onChange={(e) => {
                      setSelectedPeriod(e.target.value);
                      setTimeout(fetchTrades, 50);
                    }}
                    style={{ padding: '6px 12px', minWidth: '180px' }}
                  >
                    <option>Today's Trades</option>
                    <option>Yesterday's Trades</option>
                    <option>This Month's Trades</option>
                    <option>Last Month's Trades</option>
                    <option>Last 7 Days</option>
                    <option>All Historical Trades</option>
                  </select>
                  <button 
                    className="btn"
                    onClick={clearTrades}
                    style={{ 
                      padding: '6px 12px', 
                      fontSize: '12px', 
                      background: 'rgba(255, 23, 68, 0.12)', 
                      color: '#ff1744', 
                      border: '1px solid rgba(255, 23, 68, 0.25)',
                      fontWeight: 600
                    }}
                  >
                    Clear History
                  </button>
                </div>
              </div>
              
              {trades.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '30px 0', color: '#8a90a6', fontStyle: 'italic' }}>
                  No completed trades recorded for {selectedPeriod}.
                </div>
              ) : (
                <div className="table-container">
                  <table className="custom-table">
                    <thead>
                      <tr>
                        <th>Timestamp</th>
                        <th>Symbol</th>
                        <th>Direction</th>
                        <th>Quantity</th>
                        <th>Entry Price</th>
                        <th>Exit Price</th>
                        <th>Realised P&L</th>
                        <th>Exit Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trades.map((t, idx) => (
                        <tr key={idx}>
                          <td style={{ color: '#8a90a6' }}>{t.timestamp}</td>
                          <td style={{ fontWeight: 700 }}>{t.symbol}</td>
                          <td>
                            <span className={`badge ${t.direction === 'LONG' ? 'badge-green' : 'badge-red'}`}>
                              {t.direction}
                            </span>
                          </td>
                          <td>{t.qty}</td>
                          <td>₹{t.entry_price.toFixed(2)}</td>
                          <td>₹{t.exit_price.toFixed(2)}</td>
                          <td style={{ fontWeight: 700, color: t.pnl >= 0 ? '#00e676' : '#ff1744' }}>
                            ₹{t.pnl.toFixed(2)}
                          </td>
                          <td style={{ color: '#8a90a6' }}>{t.exit_reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Candlestick Level Chart */}
            <div className="card-panel">
              <div className="chart-header">
                <h3 className="panel-title">
                  <TrendingUp size={18} style={{ color: '#00e676' }} />
                  Interactive Level Analysis
                </h3>
                
                <select 
                  className="input-control"
                  value={chartSymbol}
                  onChange={(e) => setChartSymbol(e.target.value)}
                  style={{ minWidth: '150px' }}
                >
                  {config.strategy?.symbols?.map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
              
              {chartData ? (
                <FibonacciChart chartData={chartData} />
              ) : (
                <div style={{ textAlign: 'center', padding: '100px 0', color: '#8a90a6' }}>
                  Select a symbol to display chart data.
                </div>
              )}
            </div>
          </>
        )}

        {/* TAB 2: Historical Backtester */}
        {activeTab === 'backtest' && (
          <div className="backtest-layout">
            <aside className="backtest-sidebar">
              <h4 style={{ fontSize: '15px', fontWeight: 700 }}>Backtest Settings</h4>
              
              <div className="form-group">
                <label>Strategy Type</label>
                <select 
                  className="input-control"
                  value={btParams.strategy_type || "compare_all"}
                  onChange={(e) => setBtParams({ ...btParams, strategy_type: e.target.value })}
                >
                  <option value="compare_all">Compare All 3 Strategies</option>
                  <option value="fibonacci">VWAP + Fibonacci Pullback</option>
                  <option value="orb">Opening Range Breakout (ORB)</option>
                  <option value="vwap_pullback">VWAP Pullback - Nifty 50</option>
                </select>
              </div>

              <div className="form-group">
                <label>Symbol</label>
                <select 
                  className="input-control"
                  value={btParams.symbol}
                  onChange={(e) => setBtParams({ ...btParams, symbol: e.target.value })}
                >
                  {config.strategy?.symbols?.map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
              
              <div className="form-group">
                <label>Timeframe</label>
                <select 
                  className="input-control"
                  value={btParams.timeframe}
                  onChange={(e) => setBtParams({ ...btParams, timeframe: e.target.value })}
                >
                  <option value="minute">1 Minute</option>
                  <option value="3minute">3 Minute</option>
                  <option value="5minute">5 Minute</option>
                  <option value="15minute">15 Minute</option>
                </select>
              </div>
              
              <div className="form-group">
                <label>Lookback Period (Days): {btParams.days}</label>
                <input 
                  type="range"
                  min="5"
                  max="120"
                  step="5"
                  value={btParams.days}
                  onChange={(e) => setBtParams({ ...btParams, days: parseInt(e.target.value) })}
                />
              </div>
              
              <div className="form-group">
                <label>Starting Capital (₹)</label>
                <input 
                  type="number"
                  className="input-control"
                  value={btParams.capital}
                  onChange={(e) => setBtParams({ ...btParams, capital: parseFloat(e.target.value) })}
                />
              </div>
              
              <div className="form-group">
                <label>Risk Per Trade (%): {btParams.risk.toFixed(1)}%</label>
                <input 
                  type="range"
                  min="0.1"
                  max="5.0"
                  step="0.1"
                  value={btParams.risk}
                  onChange={(e) => setBtParams({ ...btParams, risk: parseFloat(e.target.value) })}
                />
              </div>
              
              <button 
                className="btn btn-primary btn-block"
                onClick={runBacktest}
                disabled={btLoading}
              >
                {btLoading ? 'Running...' : 'Execute Simulator'}
              </button>

            </aside>
            
            <div className="backtest-results">
              {btResults ? (
                <>
                  {btResults.isComparison ? (
                    <>
                      {/* Comparison Metrics Grid */}
                      <div className="card-panel">
                        <h3 className="panel-title" style={{ marginBottom: '15px' }}>Multi-Strategy Comparison Summary</h3>
                        <div className="table-container">
                          <table className="custom-table" style={{ width: '100%' }}>
                            <thead>
                              <tr>
                                <th>Strategy</th>
                                <th>Total Return</th>
                                <th>Est. CAGR</th>
                                <th>Sharpe Ratio</th>
                                <th>Max Drawdown</th>
                                <th>Win Rate</th>
                                <th>Winners / Losers</th>
                              </tr>
                            </thead>
                            <tbody>
                              {Object.entries(btResults.strategies).map(([stratKey, data]) => {
                                const labelMap = {
                                  fibonacci: "VWAP + Fibonacci Pullback",
                                  orb: "Opening Range Breakout (ORB)",
                                  vwap_pullback: "VWAP Pullback - Nifty 50"
                                };
                                return (
                                  <tr key={stratKey}>
                                    <td style={{ fontWeight: 700 }}>{labelMap[stratKey]}</td>
                                    <td style={{ fontWeight: 700, color: data.total_return >= 0 ? '#00e676' : '#ff1744' }}>
                                      {data.total_return >= 0 ? '+' : ''}{(data.total_return * 100).toFixed(1)}%
                                    </td>
                                    <td>{(data.cagr * 100).toFixed(1)}%</td>
                                    <td>{data.sharpe.toFixed(2)}</td>
                                    <td style={{ color: '#ff1744' }}>-{(data.max_drawdown * 100).toFixed(1)}%</td>
                                    <td>{(data.win_rate * 100).toFixed(1)}%</td>
                                    <td>{data.winners} W / {data.losers} L</td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      </div>

                      {/* Multi-Strategy Equity curve chart */}
                      <div className="card-panel">
                        <h3 className="panel-title" style={{ marginBottom: '15px' }}>Overlapping Equity Curve Comparison</h3>
                        <div className="chart-wrapper">
                          <FibonacciChart chartData={{
                            isComparison: true,
                            comparison: {
                              fibonacci: btResults.strategies.fibonacci.equity_curve,
                              orb: btResults.strategies.orb.equity_curve,
                              vwap_pullback: btResults.strategies.vwap_pullback.equity_curve
                            }
                          }} />
                        </div>
                        <div style={{ display: 'flex', gap: '20px', justifyContent: 'center', marginTop: '15px', fontSize: '12px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span style={{ display: 'inline-block', width: '12px', height: '12px', background: '#ffd54f', borderRadius: '2px' }}></span>
                            <span>Fibonacci Pullback</span>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span style={{ display: 'inline-block', width: '12px', height: '12px', background: '#2979ff', borderRadius: '2px' }}></span>
                            <span>ORB Breakout</span>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span style={{ display: 'inline-block', width: '12px', height: '12px', background: '#00e676', borderRadius: '2px' }}></span>
                            <span>VWAP Pullback</span>
                          </div>
                        </div>
                      </div>
                    </>
                  ) : (
                    <>
                      {/* Standard metrics grid */}
                      <div className="metrics-grid">
                        <div className="metric-card">
                          <div className="metric-title">Total Return</div>
                          <div className={`metric-value ${btResults.total_return >= 0 ? 'green' : 'red'}`} style={{ color: btResults.total_return >= 0 ? '#00e676' : '#ff1744' }}>
                            {btResults.total_return >= 0 ? '+' : ''}{(btResults.total_return * 100).toFixed(1)}%
                          </div>
                          <div className="metric-delta neutral">Capital: ₹{btResults.initial_capital.toLocaleString()} → ₹{btResults.final_equity.toLocaleString()}</div>
                        </div>
                        
                        <div className="metric-card">
                          <div className="metric-title">CAGR (Est.)</div>
                          <div className={`metric-value ${btResults.cagr >= 0 ? 'green' : 'red'}`} style={{ color: btResults.cagr >= 0 ? '#00e676' : '#ff1744' }}>
                            {btResults.cagr >= 0 ? '+' : ''}{(btResults.cagr * 100).toFixed(1)}%
                          </div>
                          <div className="metric-delta neutral">Sharpe Ratio: {btResults.sharpe.toFixed(2)}</div>
                        </div>
                        
                        <div className="metric-card">
                          <div className="metric-title">Max Drawdown</div>
                          <div className="metric-value" style={{ color: '#ff1744' }}>
                            -{(btResults.max_drawdown * 100).toFixed(1)}%
                          </div>
                          <div className="metric-delta neutral">Risk Controlled</div>
                        </div>
                        
                        <div className="metric-card">
                          <div className="metric-title">Win Rate</div>
                          <div className="metric-value">{(btResults.win_rate * 100).toFixed(1)}%</div>
                          <div className="metric-delta neutral">Profit Factor: {btResults.profit_factor.toFixed(2)}</div>
                        </div>
                      </div>

                      {/* Equity curve chart */}
                      <div className="card-panel">
                        <h3 className="panel-title" style={{ marginBottom: '15px' }}>Equity Curve Performance</h3>
                        <div className="chart-wrapper">
                          <FibonacciChart chartData={{ candles: btResults.equity_curve.map(p => ({
                            time: p.time,
                            open: p.equity,
                            high: p.equity,
                            low: p.equity,
                            close: p.equity
                          })) }} />
                        </div>
                      </div>

                      {/* Executed Trades Grid */}
                      <div className="card-panel">
                        <h3 className="panel-title" style={{ marginBottom: '15px' }}>Trades Execution Log</h3>
                        {btResults.trades.length === 0 ? (
                          <div style={{ textAlign: 'center', padding: '30px 0', color: '#8a90a6' }}>
                            No trades executed in this backtest.
                          </div>
                        ) : (
                          <div className="trades-card-list">
                            {btResults.trades.map((t, idx) => (
                              <div className="trade-card-item" key={idx}>
                                <div className="trade-card-header">
                                  <div className="trade-card-symbol-badge">
                                    <span className="trade-card-symbol">{t.symbol}</span>
                                    <span className={`badge ${t.direction === 'LONG' ? 'badge-green' : 'badge-red'}`}>
                                      {t.direction}
                                    </span>
                                    <span className="trade-card-qty">Qty: {t.qty}</span>
                                  </div>
                                  <div 
                                    className="trade-card-pnl" 
                                    style={{ color: t.pnl >= 0 ? '#00e676' : '#ff1744' }}
                                  >
                                    {t.pnl >= 0 ? '+' : ''}₹{t.pnl.toFixed(2)}
                                  </div>
                                </div>

                                <div className="trade-card-details">
                                  <div className="trade-point">
                                    <span className="trade-point-label">Entry Point</span>
                                    <span className="trade-point-price">₹{t.entry_price.toFixed(2)}</span>
                                    <span className="trade-point-time">{t.entry_time}</span>
                                  </div>
                                  <div className="trade-point">
                                    <span className="trade-point-label">Exit Point</span>
                                    <span className="trade-point-price">
                                      {t.exit_price ? `₹${t.exit_price.toFixed(2)}` : '-'}
                                    </span>
                                    <span className="trade-point-time">{t.exit_time}</span>
                                  </div>
                                </div>

                                <div className="trade-card-footer">
                                  <span>Exit Reason</span>
                                  <span style={{ fontWeight: 500, color: '#ffffff' }}>{t.exit_reason}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </>
              ) : (
                <div className="card-panel" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#8a90a6', textAlign: 'center', padding: '100px 0' }}>
                  <div>
                    <h4 style={{ color: '#ffffff', marginBottom: '8px' }}>Simulation Ready</h4>
                    <p style={{ maxWidth: '400px', fontSize: '14px' }}>Adjust variables in the sidebar and run the backtest simulator to view returns, metrics, and trades.</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* TAB 3: Strategy Settings */}
        {activeTab === 'settings' && (
          <form className="card-panel" onSubmit={saveConfig}>
            <div className="panel-header">
              <h3 className="panel-title">
                <Settings size={18} style={{ color: '#2979ff' }} />
                Strategy & Risk Configurations
              </h3>
              <button type="submit" className="btn btn-primary">
                <Save size={16} />
                Save Settings
              </button>
            </div>
            
            <div className="form-grid">
              {/* Strategy Parameters */}
              <div className="form-section">
                <h4 className="form-section-title">Strategy Settings</h4>

                <div className="form-group">
                  <label>Active Trading Strategy</label>
                  <select 
                    className="input-control"
                    value={config.strategy.strategy_type || "fibonacci"}
                    onChange={(e) => setConfig({
                      ...config,
                      strategy: { ...config.strategy, strategy_type: e.target.value }
                    })}
                  >
                    <option value="fibonacci">VWAP + Fibonacci Pullback</option>
                    <option value="orb">Opening Range Breakout (ORB)</option>
                    <option value="vwap_pullback">VWAP Pullback - Nifty 50</option>
                  </select>
                </div>
                
                {(!config.strategy.strategy_type || config.strategy.strategy_type === 'fibonacci') && (
                  <>
                    <div className="form-group">
                      <label>Candle Interval</label>
                      <select 
                        className="input-control"
                        value={config.strategy.timeframe}
                        onChange={(e) => setConfig({
                          ...config,
                          strategy: { ...config.strategy, timeframe: e.target.value }
                        })}
                      >
                        <option value="minute">1 Minute</option>
                        <option value="5minute">5 Minute</option>
                        <option value="10minute">10 Minute</option>
                        <option value="15minute">15 Minute</option>
                        <option value="30minute">30 Minute</option>
                        <option value="60minute">60 Minute</option>
                      </select>
                    </div>
                    
                    <div className="form-group">
                      <label>Lookback Candles</label>
                      <input 
                        type="number"
                        className="input-control"
                        value={config.strategy.lookback_candles}
                        onChange={(e) => setConfig({
                          ...config,
                          strategy: { ...config.strategy, lookback_candles: parseInt(e.target.value) }
                        })}
                      />
                    </div>
                    
                    <div className="form-group">
                      <label>Swing Threshold (candles): {config.strategy.swing_threshold}</label>
                      <input 
                        type="range"
                        min="2"
                        max="20"
                        step="1"
                        value={config.strategy.swing_threshold}
                        onChange={(e) => setConfig({
                          ...config,
                          strategy: { ...config.strategy, swing_threshold: parseInt(e.target.value) }
                        })}
                      />
                    </div>
                    
                    <div className="form-group">
                      <label>Fibonacci Entry Zone (±%): {(config.strategy.fib_zone * 100).toFixed(2)}%</label>
                      <input 
                        type="range"
                        min="0.05"
                        max="1.50"
                        step="0.05"
                        value={config.strategy.fib_zone * 100}
                        onChange={(e) => setConfig({
                          ...config,
                          strategy: { ...config.strategy, fib_zone: parseFloat(e.target.value) / 100.0 }
                        })}
                      />
                    </div>
                    
                    <div className="form-group" style={{ flexDirection: 'row', gap: '10px', alignItems: 'center', marginTop: '10px' }}>
                      <input 
                        type="checkbox"
                        id="useVwap"
                        checked={config.strategy.use_vwap}
                        onChange={(e) => setConfig({
                          ...config,
                          strategy: { ...config.strategy, use_vwap: e.target.checked }
                        })}
                      />
                      <label htmlFor="useVwap">Calculate VWAP</label>
                    </div>
                    
                    <div className="form-group" style={{ flexDirection: 'row', gap: '10px', alignItems: 'center' }}>
                      <input 
                        type="checkbox"
                        id="vwapFilter"
                        checked={config.strategy.vwap_filter}
                        onChange={(e) => setConfig({
                          ...config,
                          strategy: { ...config.strategy, vwap_filter: e.target.checked }
                        })}
                      />
                      <label htmlFor="vwapFilter">Filter Entries with VWAP</label>
                    </div>
                    
                    <div className="form-group">
                      <label>Volume MA Period</label>
                      <input 
                        type="number"
                        className="input-control"
                        value={config.strategy.volume_period}
                        onChange={(e) => setConfig({
                          ...config,
                          strategy: { ...config.strategy, volume_period: parseInt(e.target.value) }
                        })}
                      />
                    </div>
                    
                    <div className="form-group">
                      <label>Volume Multiplier: {config.strategy.volume_multiplier}x</label>
                      <input 
                        type="range"
                        min="0.5"
                        max="4.0"
                        step="0.1"
                        value={config.strategy.volume_multiplier}
                        onChange={(e) => setConfig({
                          ...config,
                          strategy: { ...config.strategy, volume_multiplier: parseFloat(e.target.value) }
                        })}
                      />
                    </div>
                    
                    <div className="form-group">
                      <label>Min Trend Strength (ATR x): {config.strategy.min_trend_strength}</label>
                      <input 
                        type="range"
                        min="0.5"
                        max="5.0"
                        step="0.1"
                        value={config.strategy.min_trend_strength}
                        onChange={(e) => setConfig({
                          ...config,
                          strategy: { ...config.strategy, min_trend_strength: parseFloat(e.target.value) }
                        })}
                      />
                    </div>
                  </>
                )}

                {config.strategy.strategy_type === 'orb' && (
                  <>
                    <div className="form-group">
                      <label>Candle Interval</label>
                      <select 
                        className="input-control"
                        value={config.strategy.timeframe}
                        onChange={(e) => setConfig({
                          ...config,
                          strategy: { ...config.strategy, timeframe: e.target.value }
                        })}
                      >
                        <option value="minute">1 Minute</option>
                        <option value="5minute">5 Minute</option>
                        <option value="15minute">15 Minute</option>
                      </select>
                    </div>

                    <div className="form-group">
                      <label>ORB Start Time (IST)</label>
                      <input 
                        type="text" 
                        className="input-control"
                        value={config.orb?.start_time || "09:15"}
                        onChange={(e) => setConfig({
                          ...config,
                          orb: { ...config.orb, start_time: e.target.value }
                        })}
                      />
                    </div>

                    <div className="form-group">
                      <label>ORB End Time (IST)</label>
                      <input 
                        type="text" 
                        className="input-control"
                        value={config.orb?.end_time || "09:30"}
                        onChange={(e) => setConfig({
                          ...config,
                          orb: { ...config.orb, end_time: e.target.value }
                        })}
                      />
                    </div>

                    <div className="form-group">
                      <label>Volume MA Period</label>
                      <input 
                        type="number" 
                        className="input-control"
                        value={config.orb?.volume_period || 20}
                        onChange={(e) => setConfig({
                          ...config,
                          orb: { ...config.orb, volume_period: parseInt(e.target.value) }
                        })}
                      />
                    </div>

                    <div className="form-group">
                      <label>Volume Breakout Multiplier: {config.orb?.volume_multiplier}x</label>
                      <input 
                        type="range"
                        min="1.0"
                        max="3.0"
                        step="0.1"
                        value={config.orb?.volume_multiplier || 1.3}
                        onChange={(e) => setConfig({
                          ...config,
                          orb: { ...config.orb, volume_multiplier: parseFloat(e.target.value) }
                        })}
                      />
                    </div>

                    <div className="form-group">
                      <label>Target Multiplier (T1 range x): {config.orb?.target_multiplier}x</label>
                      <input 
                        type="range"
                        min="0.5"
                        max="3.0"
                        step="0.1"
                        value={config.orb?.target_multiplier || 1.5}
                        onChange={(e) => setConfig({
                          ...config,
                          orb: { ...config.orb, target_multiplier: parseFloat(e.target.value) }
                        })}
                      />
                    </div>

                    <div className="form-group">
                      <label>Min Opening Range Size (%): {((config.orb?.min_range_pct || 0.001) * 100).toFixed(2)}%</label>
                      <input 
                        type="range"
                        min="0.05"
                        max="1.0"
                        step="0.05"
                        value={(config.orb?.min_range_pct || 0.001) * 100}
                        onChange={(e) => setConfig({
                          ...config,
                          orb: { ...config.orb, min_range_pct: parseFloat(e.target.value) / 100.0 }
                        })}
                      />
                    </div>

                    <div className="form-group">
                      <label>Max Opening Range Size (%): {((config.orb?.max_range_pct || 0.02) * 100).toFixed(1)}%</label>
                      <input 
                        type="range"
                        min="1.0"
                        max="5.0"
                        step="0.5"
                        value={(config.orb?.max_range_pct || 0.02) * 100}
                        onChange={(e) => setConfig({
                          ...config,
                          orb: { ...config.orb, max_range_pct: parseFloat(e.target.value) / 100.0 }
                        })}
                      />
                    </div>

                    <div className="form-group" style={{ flexDirection: 'row', gap: '10px', alignItems: 'center', marginTop: '10px' }}>
                      <input 
                        type="checkbox"
                        id="useVwapFilterOrb"
                        checked={config.orb?.use_vwap_filter !== false}
                        onChange={(e) => setConfig({
                          ...config,
                          orb: { ...config.orb, use_vwap_filter: e.target.checked }
                        })}
                      />
                      <label htmlFor="useVwapFilterOrb">Filter Entries with VWAP</label>
                    </div>
                  </>
                )}

                {config.strategy.strategy_type === 'vwap_pullback' && (
                  <>
                    <div className="form-group">
                      <label>Candle Interval</label>
                      <select 
                        className="input-control"
                        value={config.strategy.timeframe}
                        onChange={(e) => setConfig({
                          ...config,
                          strategy: { ...config.strategy, timeframe: e.target.value }
                        })}
                      >
                        <option value="minute">1 Minute</option>
                        <option value="5minute">5 Minute</option>
                        <option value="15minute">15 Minute</option>
                      </select>
                    </div>

                    <div className="form-group">
                      <label>EMA Slope Period (EMA9)</label>
                      <input 
                        type="number" 
                        className="input-control"
                        value={config.vwap_pullback?.ema_period || 9}
                        onChange={(e) => setConfig({
                          ...config,
                          vwap_pullback: { ...config.vwap_pullback, ema_period: parseInt(e.target.value) }
                        })}
                      />
                    </div>

                    <div className="form-group">
                      <label>VWAP Pullback Buffer Size (%): {((config.vwap_pullback?.vwap_buffer_pct || 0.0015) * 100).toFixed(3)}%</label>
                      <input 
                        type="range"
                        min="0.05"
                        max="0.50"
                        step="0.01"
                        value={(config.vwap_pullback?.vwap_buffer_pct || 0.0015) * 100}
                        onChange={(e) => setConfig({
                          ...config,
                          vwap_pullback: { ...config.vwap_pullback, vwap_buffer_pct: parseFloat(e.target.value) / 100.0 }
                        })}
                      />
                    </div>

                    <div className="form-group">
                      <label>Volume MA Period</label>
                      <input 
                        type="number" 
                        className="input-control"
                        value={config.vwap_pullback?.volume_period || 20}
                        onChange={(e) => setConfig({
                          ...config,
                          vwap_pullback: { ...config.vwap_pullback, volume_period: parseInt(e.target.value) }
                        })}
                      />
                    </div>

                    <div className="form-group">
                      <label>Volume Confirmation Multiplier: {config.vwap_pullback?.volume_multiplier}x</label>
                      <input 
                        type="range"
                        min="1.0"
                        max="3.0"
                        step="0.1"
                        value={config.vwap_pullback?.volume_multiplier || 1.2}
                        onChange={(e) => setConfig({
                          ...config,
                          vwap_pullback: { ...config.vwap_pullback, volume_multiplier: parseFloat(e.target.value) }
                        })}
                      />
                    </div>

                    <div className="form-group">
                      <label>Stop Loss Distance (%): {((config.vwap_pullback?.stop_loss_pct || 0.005) * 100).toFixed(2)}%</label>
                      <input 
                        type="range"
                        min="0.1"
                        max="2.0"
                        step="0.1"
                        value={(config.vwap_pullback?.stop_loss_pct || 0.005) * 100}
                        onChange={(e) => setConfig({
                          ...config,
                          vwap_pullback: { ...config.vwap_pullback, stop_loss_pct: parseFloat(e.target.value) / 100.0 }
                        })}
                      />
                    </div>

                    <div className="form-group">
                      <label>Swing Points Lookback (candles)</label>
                      <input 
                        type="number" 
                        className="input-control"
                        value={config.vwap_pullback?.lookback_swings || 20}
                        onChange={(e) => setConfig({
                          ...config,
                          vwap_pullback: { ...config.vwap_pullback, lookback_swings: parseInt(e.target.value) }
                        })}
                      />
                    </div>
                  </>
                )}
              </div>
              
              {/* Risk Settings */}
              <div className="form-section">
                <h4 className="form-section-title">Risk & Capital Settings</h4>
                
                <div className="form-group">
                  <label>Account Sizing Capital (₹)</label>
                  <input 
                    type="number"
                    className="input-control"
                    value={config.risk.capital}
                    onChange={(e) => setConfig({
                      ...config,
                      risk: { ...config.risk, capital: parseFloat(e.target.value) }
                    })}
                  />
                </div>
                
                <div className="form-group">
                  <label>Risk Per Trade (%): {(config.risk.risk_per_trade * 100).toFixed(1)}%</label>
                  <input 
                    type="range"
                    min="0.1"
                    max="5.0"
                    step="0.1"
                    value={config.risk.risk_per_trade * 100}
                    onChange={(e) => setConfig({
                      ...config,
                      risk: { ...config.risk, risk_per_trade: parseFloat(e.target.value) / 100.0 }
                    })}
                  />
                </div>
                
                <div className="form-group">
                  <label>Max Daily Loss (%): {(config.risk.max_daily_loss * 100).toFixed(1)}%</label>
                  <input 
                    type="range"
                    min="0.5"
                    max="10.0"
                    step="0.5"
                    value={config.risk.max_daily_loss * 100}
                    onChange={(e) => setConfig({
                      ...config,
                      risk: { ...config.risk, max_daily_loss: parseFloat(e.target.value) / 100.0 }
                    })}
                  />
                </div>
                
                <div className="form-group">
                  <label>Max Consecutive Losses: {config.risk.max_consecutive_losses}</label>
                  <input 
                    type="range"
                    min="1"
                    max="10"
                    step="1"
                    value={config.risk.max_consecutive_losses}
                    onChange={(e) => setConfig({
                      ...config,
                      risk: { ...config.risk, max_consecutive_losses: parseInt(e.target.value) }
                    })}
                  />
                </div>
                
                <div className="form-group">
                  <label>Max Daily Trade Entries: {config.risk.max_daily_trades}</label>
                  <input 
                    type="range"
                    min="1"
                    max="30"
                    step="1"
                    value={config.risk.max_daily_trades}
                    onChange={(e) => setConfig({
                      ...config,
                      risk: { ...config.risk, max_daily_trades: parseInt(e.target.value) }
                    })}
                  />
                </div>
                
                <div className="form-group">
                  <label>Min Risk-Reward Ratio (x): {config.risk.min_risk_reward}</label>
                  <input 
                    type="range"
                    min="1.0"
                    max="5.0"
                    step="0.1"
                    value={config.risk.min_risk_reward}
                    onChange={(e) => setConfig({
                      ...config,
                      risk: { ...config.risk, min_risk_reward: parseFloat(e.target.value) }
                    })}
                  />
                </div>
                
                <div className="form-group">
                  <label>Market Session Open Time (IST)</label>
                  <input 
                    type="text"
                    className="input-control"
                    value={config.risk.market_open}
                    onChange={(e) => setConfig({
                      ...config,
                      risk: { ...config.risk, market_open: e.target.value }
                    })}
                  />
                </div>
                
                <div className="form-group">
                  <label>Auto Position Squareoff Time (IST)</label>
                  <input 
                    type="text"
                    className="input-control"
                    value={config.risk.squareoff_time}
                    onChange={(e) => setConfig({
                      ...config,
                      risk: { ...config.risk, squareoff_time: e.target.value }
                    })}
                  />
                </div>
              </div>
            </div>
          </form>
        )}

        {/* TAB 4: Angel One Auth Session */}
        {activeTab === 'auth' && (
          <div className="card-panel">
            <h3 className="panel-title" style={{ marginBottom: '10px' }}>
              <Key size={18} style={{ color: '#ff9100' }} />
              Angel One SmartAPI Session Validation
            </h3>
            
            <p style={{ color: '#8a90a6', fontSize: '14px', marginBottom: '24px', maxWidth: '650px' }}>
              Configure and test your Angel One developer credentials to establish connection to OpenAPI servers. Once validated, credentials will be persisted to your system `.env` configuration.
            </p>
            
            <form onSubmit={generateAuthToken} style={{ maxWidth: '500px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div className="form-group">
                <label>SmartAPI API Key</label>
                <input 
                  type="password"
                  className="input-control"
                  placeholder="Enter Angel API Key"
                  value={authData.api_key}
                  onChange={(e) => setAuthData({ ...authData, api_key: e.target.value })}
                  required
                />
              </div>
              
              <div className="form-group">
                <label>Client ID (e.g. AB123456)</label>
                <input 
                  type="text"
                  className="input-control"
                  placeholder="Enter Angel Client ID"
                  value={authData.client_id}
                  onChange={(e) => setAuthData({ ...authData, client_id: e.target.value })}
                  required
                />
              </div>

              <div className="form-group">
                <label>4-Digit PIN</label>
                <input 
                  type="password"
                  className="input-control"
                  placeholder="Enter 4-Digit Login PIN"
                  value={authData.pin}
                  onChange={(e) => setAuthData({ ...authData, pin: e.target.value })}
                  maxLength={4}
                  required
                />
              </div>

              <div className="form-group">
                <label>TOTP Secret Key</label>
                <input 
                  type="password"
                  className="input-control"
                  placeholder="Enter TOTP Secret Key (from SmartAPI portal)"
                  value={authData.totp_secret}
                  onChange={(e) => setAuthData({ ...authData, totp_secret: e.target.value })}
                  required
                />
              </div>
              
              <button type="submit" className="btn btn-primary" style={{ marginTop: '10px' }}>
                Validate & Save Credentials
              </button>
            </form>

            <div style={{ marginTop: '40px', borderTop: '1px solid #1a2035', paddingTop: '30px' }}>
              <h4 style={{ color: '#ffffff', marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', fontWeight: 600 }}>
                <Activity size={18} style={{ color: '#00e676' }} />
                Real-Time API Optimization Diagnostics
              </h4>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '15px' }}>
                <div style={{ background: '#121824', padding: '15px', borderRadius: '6px', border: '1px solid #1a2035' }}>
                  <div style={{ color: '#8a90a6', fontSize: '12px' }}>Total API Calls</div>
                  <div style={{ color: '#ffffff', fontSize: '20px', fontWeight: 600 }}>{diagnostics.total_api_calls}</div>
                </div>
                <div style={{ background: '#121824', padding: '15px', borderRadius: '6px', border: '1px solid #1a2035' }}>
                  <div style={{ color: '#8a90a6', fontSize: '12px' }}>Cache Hit Ratio</div>
                  <div style={{ color: '#00e676', fontSize: '20px', fontWeight: 600 }}>{diagnostics.hit_ratio_pct}%</div>
                </div>
                <div style={{ background: '#121824', padding: '15px', borderRadius: '6px', border: '1px solid #1a2035' }}>
                  <div style={{ color: '#8a90a6', fontSize: '12px' }}>Cache Hits / Misses</div>
                  <div style={{ color: '#ffffff', fontSize: '16px', fontWeight: 600, marginTop: '4px' }}>
                    <span style={{ color: '#00e676' }}>{diagnostics.cache_hits}</span> / <span style={{ color: '#ff1744' }}>{diagnostics.cache_misses}</span>
                  </div>
                </div>
                <div style={{ background: '#121824', padding: '15px', borderRadius: '6px', border: '1px solid #1a2035' }}>
                  <div style={{ color: '#8a90a6', fontSize: '12px' }}>Throttled API Calls Saved</div>
                  <div style={{ color: '#29b6f6', fontSize: '20px', fontWeight: 600 }}>{diagnostics.rate_limit_waits}</div>
                </div>
                <div style={{ background: '#121824', padding: '15px', borderRadius: '6px', border: '1px solid #1a2035' }}>
                  <div style={{ color: '#8a90a6', fontSize: '12px' }}>Circuit Breaker Trips</div>
                  <div style={{ color: '#ff9100', fontSize: '20px', fontWeight: 600 }}>{diagnostics.circuit_breaker_trips}</div>
                </div>
                <div style={{ background: '#121824', padding: '15px', borderRadius: '6px', border: '1px solid #1a2035' }}>
                  <div style={{ color: '#8a90a6', fontSize: '12px' }}>Active Session</div>
                  <div style={{ color: diagnostics.session_active ? '#00e676' : '#ff1744', fontSize: '16px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px' }}>
                    <span className={`dot ${diagnostics.session_active ? 'green' : 'red'}`}></span>
                    {diagnostics.session_active ? "Connected" : "Disconnected"}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 5: Data Analysis Dashboard */}
        {activeTab === 'analysis' && (
          <AnalysisDashboard />
        )}
      </main>
    </div>
  );
}
