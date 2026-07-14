import React, { useState } from 'react';
import { Check, Info, TrendingUp, DollarSign, Wallet } from 'lucide-react';

const STRATEGIES_DATA = [
  {
    id: 'bullish',
    name: 'Index Performer: Bullish',
    capital: 750000,
    monthlyProfits: {
      Mar: 22000,
      Apr: 15000,
      May: 12000,
      Jun: 35000,
      Jul: 18000,
      Aug: 13000
    }
  },
  {
    id: 'bearish',
    name: 'Index Performer: Bearish',
    capital: 750000,
    monthlyProfits: {
      Mar: 16100,
      Apr: 11800,
      May: 9200,
      Jun: 20500,
      Jul: 11600,
      Aug: 8500
    }
  },
  {
    id: 'risk_manager',
    name: 'BankNIFTY Risk Manager',
    capital: 500000,
    monthlyProfits: {
      Mar: 10000,
      Apr: 8000,
      May: 9000,
      Jun: 15000,
      Jul: 8000,
      Aug: 7000
    }
  }
];

const MONTHS = ['Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug'];

export default function AnalysisDashboard() {
  const [selectedStrats, setSelectedStrats] = useState({
    bullish: true,
    bearish: true,
    risk_manager: true
  });

  const [hoveredBarIndex, setHoveredBarIndex] = useState(null);
  const [hoveredLineIndex, setHoveredLineIndex] = useState(null);

  const toggleStrategy = (id) => {
    setSelectedStrats(prev => {
      const next = { ...prev, [id]: !prev[id] };
      // Keep at least one strategy selected to avoid division by zero or blank screens
      const selectedCount = Object.values(next).filter(Boolean).length;
      return selectedCount > 0 ? next : prev;
    });
  };

  // 1. Calculate Capitals
  const totalCapital = STRATEGIES_DATA.reduce((sum, s) => sum + s.capital, 0);
  const selectedCapital = STRATEGIES_DATA.reduce((sum, s) => {
    return sum + (selectedStrats[s.id] ? s.capital : 0);
  }, 0);

  // 2. Calculate Monthly Profits based on selection
  const monthlyTotals = MONTHS.map(month => {
    const profit = STRATEGIES_DATA.reduce((sum, s) => {
      return sum + (selectedStrats[s.id] ? s.monthlyProfits[month] : 0);
    }, 0);
    return { month, profit };
  });

  // 3. Calculate Cumulative Profits
  let runningSum = 0;
  const cumulativeTotals = monthlyTotals.map(item => {
    runningSum += item.profit;
    return { month: item.month, cumulative: runningSum };
  });

  const totalCumulativeProfit = runningSum;

  // Format currency in Indian Style (Lakhs / Crores)
  const formatINR = (val) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0
    }).format(val);
  };

  // Format labels like 48K, 1.1L
  const formatLabel = (val) => {
    if (val === 0) return '0';
    if (val >= 100000) {
      return (val / 100000).toFixed(1) + 'L';
    }
    if (val >= 1000) {
      return Math.round(val / 1000) + 'K';
    }
    return val.toString();
  };

  // SVG dimensions & grid setup
  const width = 500;
  const height = 300;
  const paddingLeft = 55;
  const paddingRight = 20;
  const paddingTop = 30;
  const paddingBottom = 40;
  const plotWidth = width - paddingLeft - paddingRight;
  const plotHeight = height - paddingTop - paddingBottom;

  // ── BAR CHART CALCULATIONS ──────────────────────────────────────────────────
  const barYMax = 80000;
  const barYGridTicks = [0, 10000, 20000, 30000, 40000, 50000, 60000, 70000, 80000];
  
  const getBarCoords = (index, val) => {
    const colWidth = plotWidth / MONTHS.length;
    const x = paddingLeft + colWidth * index + colWidth / 2;
    const barH = (val / barYMax) * plotHeight;
    const y = paddingTop + plotHeight - barH;
    return { x, y, h: barH };
  };

  // ── LINE CHART CALCULATIONS ─────────────────────────────────────────────────
  const lineYMax = 250000;
  const lineYGridTicks = [0, 50000, 100000, 150000, 200000, 250000];

  const getLineCoords = (index, val) => {
    const colWidth = plotWidth / MONTHS.length;
    const x = paddingLeft + colWidth * index + colWidth / 2;
    const y = paddingTop + plotHeight - (val / lineYMax) * plotHeight;
    return { x, y };
  };

  const linePoints = cumulativeTotals.map((item, idx) => getLineCoords(idx, item.cumulative));
  const linePathD = linePoints.reduce((path, pt, idx) => {
    return idx === 0 ? `M ${pt.x} ${pt.y}` : `${path} L ${pt.x} ${pt.y}`;
  }, '');

  return (
    <div className="analysis-container">
      <style>{`
        .analysis-container {
          padding: 24px;
          display: flex;
          flex-direction: column;
          gap: 28px;
          overflow-y: auto;
          height: calc(100vh - 60px);
        }

        .header-title {
          font-size: 22px;
          font-weight: 700;
          color: #ffffff;
          margin-bottom: 4px;
        }

        .header-desc {
          font-size: 13px;
          color: var(--text-secondary);
        }

        /* Checkboxes styling */
        .strategies-selector {
          display: flex;
          gap: 20px;
          flex-wrap: wrap;
          margin-top: 10px;
        }

        .strategy-checkbox-card {
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 16px 20px;
          border-radius: 14px;
          background: rgba(255, 255, 255, 0.02);
          border: 1px solid rgba(255, 255, 255, 0.04);
          cursor: pointer;
          transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
          min-width: 250px;
          flex: 1;
        }

        .strategy-checkbox-card:hover {
          background: rgba(0, 229, 255, 0.02);
          border-color: rgba(0, 229, 255, 0.15);
          transform: translateY(-2px);
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }

        .strategy-checkbox-card.active {
          border-color: rgba(0, 229, 255, 0.35);
          background: rgba(0, 229, 255, 0.04);
          box-shadow: 0 0 15px rgba(0, 229, 255, 0.05);
        }

        .chk-circle {
          width: 22px;
          height: 22px;
          border-radius: 50%;
          border: 2px solid rgba(255, 255, 255, 0.25);
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.2s ease;
          flex-shrink: 0;
        }

        .strategy-checkbox-card.active .chk-circle {
          background: #00d2ff;
          border-color: #00d2ff;
          color: #0c0c0f;
          box-shadow: 0 0 8px rgba(0, 210, 255, 0.4);
        }

        .strat-details {
          display: flex;
          flex-direction: column;
        }

        .strat-name {
          font-size: 15px;
          font-weight: 600;
          color: #ffffff;
        }

        .strat-cap {
          font-size: 13px;
          color: var(--text-secondary);
          margin-top: 3px;
        }

        /* KPI panel */
        .kpi-row {
          display: flex;
          gap: 40px;
          padding: 20px 24px;
          background: rgba(16, 15, 22, 0.6);
          border-radius: 16px;
          border: 1px solid rgba(255, 255, 255, 0.03);
          flex-wrap: wrap;
          backdrop-filter: blur(10px);
        }

        .kpi-card {
          display: flex;
          align-items: center;
          gap: 14px;
          flex: 1;
          min-width: 180px;
        }

        .kpi-icon-box {
          width: 44px;
          height: 44px;
          border-radius: 12px;
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.05);
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--text-secondary);
        }

        .kpi-icon-box.green {
          color: var(--color-green);
          background: rgba(0, 230, 118, 0.05);
          border-color: rgba(0, 230, 118, 0.1);
        }

        .kpi-icon-box.cyan {
          color: #00d2ff;
          background: rgba(0, 210, 255, 0.05);
          border-color: rgba(0, 210, 255, 0.1);
        }

        .kpi-text {
          display: flex;
          flex-direction: column;
        }

        .kpi-label {
          font-size: 12px;
          color: var(--text-secondary);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          font-weight: 600;
        }

        .kpi-val {
          font-size: 20px;
          font-weight: 700;
          color: #ffffff;
          margin-top: 2px;
        }

        .kpi-val.green {
          color: var(--color-green);
          text-shadow: 0 0 10px rgba(0, 230, 118, 0.15);
        }

        /* Charts grid */
        .charts-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 24px;
        }

        @media (max-width: 1000px) {
          .charts-grid {
            grid-template-columns: 1fr;
          }
        }

        .chart-card {
          background: var(--bg-card);
          border: 1px solid var(--border-color);
          border-radius: 20px;
          padding: 24px;
          display: flex;
          flex-direction: column;
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
          backdrop-filter: blur(16px);
        }

        .chart-title {
          font-size: 17px;
          font-weight: 700;
          color: #ffffff;
          margin-bottom: 20px;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .chart-svg-container {
          position: relative;
          width: 100%;
          height: auto;
          aspect-ratio: 5 / 3;
        }

        /* SVG Styles */
        .grid-line {
          stroke: rgba(255, 255, 255, 0.035);
          stroke-width: 1;
        }

        .chart-axis-text {
          fill: #8f8c96;
          font-size: 11px;
          font-weight: 500;
        }

        .bar-hover-rect {
          fill: rgba(0, 229, 255, 0.02);
          opacity: 0;
          transition: opacity 0.2s ease;
        }

        .bar-hover-rect.active {
          opacity: 1;
        }

        .bar-rect {
          transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
          cursor: pointer;
        }

        .bar-rect:hover {
          filter: drop-shadow(0px 0px 8px rgba(0, 210, 255, 0.6));
        }

        .chart-label-text {
          fill: #ffffff;
          font-size: 11px;
          font-weight: 600;
          text-anchor: middle;
        }

        .line-path {
          stroke-dasharray: 1000;
          stroke-dashoffset: 0;
          animation: drawLine 1.5s ease-out forwards;
        }

        .point-circle {
          transition: r 0.2s ease, stroke-width 0.2s ease;
          cursor: pointer;
        }

        .point-circle:hover {
          r: 7;
          stroke-width: 3;
          fill: #00d2ff;
          stroke: #ffffff;
        }

        .guideline {
          stroke: rgba(0, 210, 255, 0.2);
          stroke-width: 1;
          stroke-dasharray: 4 4;
        }

        /* Custom tooltip inside HTML */
        .chart-tooltip {
          position: absolute;
          background: rgba(18, 17, 24, 0.95);
          border: 1px solid rgba(0, 210, 255, 0.3);
          border-radius: 8px;
          padding: 8px 12px;
          pointer-events: none;
          font-size: 12px;
          box-shadow: 0 4px 15px rgba(0, 0, 0, 0.5);
          z-index: 10;
          color: #fff;
          transform: translate(-50%, -100%);
          margin-top: -12px;
          transition: opacity 0.15s ease, left 0.15s ease, top 0.15s ease;
          opacity: 0;
        }

        .chart-tooltip.visible {
          opacity: 1;
        }

        @keyframes drawLine {
          from {
            stroke-dashoffset: 1000;
          }
          to {
            stroke-dashoffset: 0;
          }
        }
      `}</style>

      {/* Title */}
      <div>
        <h1 className="header-title">Compare Strategies</h1>
        <div className="header-desc">Analyze and benchmark performance configurations across strategies</div>
      </div>

      {/* Strategies Checkboxes Selector */}
      <div className="strategies-selector">
        {STRATEGIES_DATA.map(strat => {
          const isActive = selectedStrats[strat.id];
          return (
            <div 
              key={strat.id} 
              className={`strategy-checkbox-card ${isActive ? 'active' : ''}`}
              onClick={() => toggleStrategy(strat.id)}
            >
              <div className="chk-circle">
                {isActive && <Check size={12} strokeWidth={4} />}
              </div>
              <div className="strat-details">
                <span className="strat-name">{strat.name}</span>
                <span className="strat-cap">{formatINR(strat.capital)}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* KPI Metrics */}
      <div className="kpi-row">
        <div className="kpi-card">
          <div className="kpi-icon-box">
            <Wallet size={20} />
          </div>
          <div className="kpi-text">
            <span className="kpi-label">Total Capital</span>
            <span className="kpi-val">{formatINR(totalCapital)}</span>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-icon-box cyan">
            <DollarSign size={20} />
          </div>
          <div className="kpi-text">
            <span className="kpi-label">Selected Capital</span>
            <span className="kpi-val">{formatINR(selectedCapital)}</span>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-icon-box green">
            <TrendingUp size={20} />
          </div>
          <div className="kpi-text">
            <span className="kpi-label">Cumulative Profit</span>
            <span className="kpi-val green">{formatINR(totalCumulativeProfit)}</span>
          </div>
        </div>
      </div>

      {/* Charts Grid */}
      <div className="charts-grid">
        {/* Monthly Profit Bar Chart */}
        <div className="chart-card">
          <h2 className="chart-title">Monthly Profit</h2>
          <div className="chart-svg-container">
            <svg viewBox={`0 0 ${width} ${height}`} width="100%" height="100%">
              <defs>
                <linearGradient id="bar-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#00d2ff" />
                  <stop offset="100%" stopColor="rgba(0, 210, 255, 0.25)" />
                </linearGradient>
              </defs>

              {/* Grid Lines */}
              {barYGridTicks.map((tick, i) => {
                const y = paddingTop + plotHeight - (tick / barYMax) * plotHeight;
                return (
                  <g key={i}>
                    <line 
                      x1={paddingLeft} 
                      y1={y} 
                      x2={width - paddingRight} 
                      y2={y} 
                      className="grid-line" 
                    />
                    <text 
                      x={paddingLeft - 8} 
                      y={y + 4} 
                      textAnchor="end" 
                      className="chart-axis-text"
                    >
                      {tick === 0 ? '0' : formatLabel(tick)}
                    </text>
                  </g>
                );
              })}

              {/* Bar Elements */}
              {monthlyTotals.map((item, idx) => {
                const { x, y, h } = getBarCoords(idx, item.profit);
                const barWidth = 36;
                const isHovered = hoveredBarIndex === idx;

                return (
                  <g 
                    key={idx}
                    onMouseEnter={() => setHoveredBarIndex(idx)}
                    onMouseLeave={() => setHoveredBarIndex(null)}
                  >
                    {/* Background Column Highlight */}
                    <rect
                      x={x - barWidth}
                      y={paddingTop}
                      width={barWidth * 2}
                      height={plotHeight}
                      className={`bar-hover-rect ${isHovered ? 'active' : ''}`}
                      rx={8}
                    />

                    {/* Actual Bar */}
                    {item.profit > 0 && (
                      <rect
                        x={x - barWidth / 2}
                        y={y}
                        width={barWidth}
                        height={Math.max(2, h)}
                        fill="url(#bar-grad)"
                        className="bar-rect"
                        rx={4}
                      />
                    )}

                    {/* Value Label */}
                    {item.profit > 0 && (
                      <text
                        x={x}
                        y={y - 8}
                        className="chart-label-text"
                      >
                        {item.profit}
                      </text>
                    )}
                  </g>
                );
              })}

              {/* X Axis Labels */}
              {MONTHS.map((month, idx) => {
                const colWidth = plotWidth / MONTHS.length;
                const x = paddingLeft + colWidth * idx + colWidth / 2;
                return (
                  <text
                    key={idx}
                    x={x}
                    y={height - paddingBottom + 20}
                    textAnchor="middle"
                    className="chart-axis-text"
                    style={{ fontWeight: 600 }}
                  >
                    {month}
                  </text>
                );
              })}
              
              {/* Bottom border line */}
              <line 
                x1={paddingLeft} 
                y1={paddingTop + plotHeight} 
                x2={width - paddingRight} 
                y2={paddingTop + plotHeight} 
                stroke="rgba(255,255,255,0.06)" 
                strokeWidth={1} 
              />
            </svg>
            
            {/* HTML Tooltip on hover */}
            {hoveredBarIndex !== null && (
              <div 
                className="chart-tooltip visible"
                style={{
                  left: `${((getBarCoords(hoveredBarIndex, monthlyTotals[hoveredBarIndex].profit).x) / width) * 100}%`,
                  top: `${((getBarCoords(hoveredBarIndex, monthlyTotals[hoveredBarIndex].profit).y) / height) * 100}%`
                }}
              >
                <strong>{MONTHS[hoveredBarIndex]} Profit:</strong> {formatINR(monthlyTotals[hoveredBarIndex].profit)}
              </div>
            )}
          </div>
        </div>

        {/* Cumulative Profit Line Chart */}
        <div className="chart-card">
          <h2 className="chart-title">Cumulative Profit</h2>
          <div className="chart-svg-container">
            <svg viewBox={`0 0 ${width} ${height}`} width="100%" height="100%">
              {/* Grid Lines */}
              {lineYGridTicks.map((tick, i) => {
                const y = paddingTop + plotHeight - (tick / lineYMax) * plotHeight;
                return (
                  <g key={i}>
                    <line 
                      x1={paddingLeft} 
                      y1={y} 
                      x2={width - paddingRight} 
                      y2={y} 
                      className="grid-line" 
                    />
                    <text 
                      x={paddingLeft - 8} 
                      y={y + 4} 
                      textAnchor="end" 
                      className="chart-axis-text"
                    >
                      {tick === 0 ? '0' : formatLabel(tick)}
                    </text>
                  </g>
                );
              })}

              {/* Vertical guideline on hover */}
              {hoveredLineIndex !== null && (
                <line
                  x1={linePoints[hoveredLineIndex].x}
                  y1={paddingTop}
                  x2={linePoints[hoveredLineIndex].x}
                  y2={paddingTop + plotHeight}
                  className="guideline"
                />
              )}

              {/* Line Path */}
              {totalCumulativeProfit > 0 && (
                <path
                  d={linePathD}
                  fill="none"
                  stroke="#00d2ff"
                  strokeWidth={3}
                  className="line-path"
                />
              )}

              {/* Data points (circles) & labels */}
              {cumulativeTotals.map((item, idx) => {
                const pt = linePoints[idx];
                const isHovered = hoveredLineIndex === idx;

                return (
                  <g key={idx}>
                    {/* Circle Point */}
                    <circle
                      cx={pt.x}
                      cy={pt.y}
                      r={isHovered ? 7 : 4}
                      fill={isHovered ? '#00d2ff' : '#ffffff'}
                      stroke="#00d2ff"
                      strokeWidth={isHovered ? 3 : 2}
                      className="point-circle"
                      onMouseEnter={() => setHoveredLineIndex(idx)}
                      onMouseLeave={() => setHoveredLineIndex(null)}
                    />

                    {/* Value Label */}
                    <text
                      x={pt.x}
                      y={pt.y - 12}
                      className="chart-label-text"
                    >
                      {formatLabel(item.cumulative)}
                    </text>
                  </g>
                );
              })}

              {/* X Axis Labels */}
              {MONTHS.map((month, idx) => {
                const colWidth = plotWidth / MONTHS.length;
                const x = paddingLeft + colWidth * idx + colWidth / 2;
                return (
                  <text
                    key={idx}
                    x={x}
                    y={height - paddingBottom + 20}
                    textAnchor="middle"
                    className="chart-axis-text"
                    style={{ fontWeight: 600 }}
                  >
                    {month}
                  </text>
                );
              })}

              {/* Bottom border line */}
              <line 
                x1={paddingLeft} 
                y1={paddingTop + plotHeight} 
                x2={width - paddingRight} 
                y2={paddingTop + plotHeight} 
                stroke="rgba(255,255,255,0.06)" 
                strokeWidth={1} 
              />
            </svg>

            {/* HTML Tooltip on hover */}
            {hoveredLineIndex !== null && (
              <div 
                className="chart-tooltip visible"
                style={{
                  left: `${(linePoints[hoveredLineIndex].x / width) * 100}%`,
                  top: `${(linePoints[hoveredLineIndex].y / height) * 100}%`
                }}
              >
                <strong>Cumulative:</strong> {formatINR(cumulativeTotals[hoveredLineIndex].cumulative)}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
