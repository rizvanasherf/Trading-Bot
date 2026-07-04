import React, { useEffect, useRef, useState } from 'react';
import { createChart, CandlestickSeries, LineSeries } from 'lightweight-charts';

export default function FibonacciChart({ chartData }) {
  const chartContainerRef = useRef();
  const wrapperRef = useRef();
  const [isFullscreen, setIsFullscreen] = useState(false);

  const chartRef = useRef(null);
  const candlestickSeriesRef = useRef(null);
  const comparisonSeriesRef = useRef([]);
  const priceLinesRef = useRef([]);
  const lastSymbolRef = useRef(null);
  const isComparisonModeRef = useRef(false);

  // Resize handler
  const handleResize = () => {
    if (chartRef.current && chartContainerRef.current) {
      const isFull = !!document.fullscreenElement;
      chartRef.current.applyOptions({ 
        width: chartContainerRef.current.clientWidth,
        height: isFull ? window.innerHeight - 40 : 350
      });
    }
  };

  // Fullscreen toggle handler
  const toggleFullscreen = () => {
    if (!wrapperRef.current) return;
    if (!document.fullscreenElement) {
      wrapperRef.current.requestFullscreen().then(() => {
        setIsFullscreen(true);
      }).catch(err => {
        console.error(`Error enabling fullscreen: ${err.message}`);
      });
    } else {
      document.exitFullscreen().then(() => {
        setIsFullscreen(false);
      });
    }
  };

  // Listen to fullscreen changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      const isFull = !!document.fullscreenElement;
      setIsFullscreen(isFull);
      setTimeout(handleResize, 100);
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
    };
  }, []);

  useEffect(() => {
    if (!chartData) return;

    const container = chartContainerRef.current;
    const isComp = !!chartData.isComparison;

    // Check if we need to completely recreate the chart
    const modeChanged = isComp !== isComparisonModeRef.current;
    const symbolChanged = !isComp && chartData.symbol !== lastSymbolRef.current;
    const needsRecreate = !chartRef.current || modeChanged || symbolChanged;

    if (needsRecreate) {
      // 1. Cleanup old chart
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
      priceLinesRef.current = [];
      comparisonSeriesRef.current = [];
      candlestickSeriesRef.current = null;

      // 2. Instantiate new chart
      const chart = createChart(container, {
        layout: {
          background: { color: '#131217' },
          textColor: '#8a90a6',
          fontFamily: 'Outfit, sans-serif'
        },
        grid: {
          vertLines: { color: 'rgba(255, 255, 255, 0.03)' },
          horzLines: { color: 'rgba(255, 255, 255, 0.03)' },
        },
        width: container.clientWidth,
        height: isFullscreen ? window.innerHeight - 40 : 350,
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
        },
      });

      chartRef.current = chart;
      isComparisonModeRef.current = isComp;
      lastSymbolRef.current = isComp ? "comparison" : chartData.symbol;

      window.addEventListener('resize', handleResize);

      // 3. Create relevant series type
      if (isComp) {
        // Multi-strategy line series
        const fibLine = chart.addSeries(LineSeries, {
          color: '#ffd54f', // Yellow/Gold
          lineWidth: 2,
          title: 'Fibonacci Pullback'
        });
        const orbLine = chart.addSeries(LineSeries, {
          color: '#6444e3', // Violet/Purple matching theme
          lineWidth: 2,
          title: 'ORB Breakout'
        });
        const vpLine = chart.addSeries(LineSeries, {
          color: '#00e676', // Green
          lineWidth: 2,
          title: 'VWAP Pullback'
        });

        comparisonSeriesRef.current = [
          { key: 'fibonacci', series: fibLine },
          { key: 'orb', series: orbLine },
          { key: 'vwap_pullback', series: vpLine }
        ];
      } else {
        // Normal Candlestick Series
        const candleSeries = chart.addSeries(CandlestickSeries, {
          upColor: '#00e676',
          downColor: '#ff1744',
          borderUpColor: '#00e676',
          borderDownColor: '#ff1744',
          wickUpColor: '#00e676',
          wickDownColor: '#ff1744',
        });
        candlestickSeriesRef.current = candleSeries;
      }
    }

    // 4. Update data on active series
    if (isComp) {
      comparisonSeriesRef.current.forEach(({ key, series }) => {
        const curve = chartData.comparison?.[key];
        if (curve) {
          series.setData(curve.map(p => ({
            time: p.time,
            value: p.equity
          })));
        }
      });
    } else {
      if (chartData.candles && candlestickSeriesRef.current) {
        candlestickSeriesRef.current.setData(chartData.candles);

        // Clear existing price lines
        priceLinesRef.current.forEach(line => {
          try {
            candlestickSeriesRef.current.removePriceLine(line);
          } catch (err) {
            // Ignored
          }
        });
        priceLinesRef.current = [];

        // Plot Fibonacci or ORB range levels
        if (chartData.fib_levels) {
          const colors = {
            '0.382': '#ffd54f',
            '0.5': '#81c784',
            '0.618': '#2979ff'
          };

          Object.entries(chartData.fib_levels).forEach(([ratio, price]) => {
            const line = candlestickSeriesRef.current.createPriceLine({
              price: price,
              color: colors[ratio] || '#8a90a6',
              lineWidth: 1,
              lineStyle: 1, // Dotted
              axisLabelVisible: true,
              title: ratio.startsWith('OR') ? `${ratio} (₹${price.toFixed(2)})` : `Fib ${ratio} (₹${price.toFixed(2)})`,
            });
            priceLinesRef.current.push(line);
          });
        }

        // Plot Extensions
        if (chartData.fib_extensions) {
          Object.entries(chartData.fib_extensions).forEach(([ratio, price]) => {
            const line = candlestickSeriesRef.current.createPriceLine({
              price: price,
              color: '#e91e63',
              lineWidth: 1,
              lineStyle: 2, // Dashed
              axisLabelVisible: true,
              title: ratio.startsWith('Target') ? `${ratio} (₹${price.toFixed(2)})` : `Ext ${ratio} (₹${price.toFixed(2)})`,
            });
            priceLinesRef.current.push(line);
          });
        }
      }
    }

  }, [chartData]);

  // Clean up on component unmount
  useEffect(() => {
    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
      candlestickSeriesRef.current = null;
      comparisonSeriesRef.current = [];
      priceLinesRef.current = [];
    };
  }, []);

  return (
    <div ref={wrapperRef} style={{ position: 'relative', width: '100%', background: '#131217', padding: isFullscreen ? '20px 10px 10px 10px' : '0' }}>
      <button 
        onClick={toggleFullscreen} 
        style={{
          position: 'absolute',
          top: isFullscreen ? '15px' : '10px',
          right: isFullscreen ? '15px' : '10px',
          zIndex: 100,
          background: 'rgba(25, 27, 43, 0.85)',
          border: '1px solid rgba(255, 255, 255, 0.12)',
          color: '#ffffff',
          borderRadius: '6px',
          padding: '6px 12px',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          fontSize: '11px',
          fontWeight: 600,
          boxShadow: '0 4px 12px rgba(0, 0, 0, 0.4)',
          transition: 'all 0.2s ease',
          backdropFilter: 'blur(4px)'
        }}
        title="Toggle Fullscreen"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          {isFullscreen ? (
            <path d="M4 14h6v6M20 10h-6V4M14 10l7-7M10 14l-7 7" />
          ) : (
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
          )}
        </svg>
        {isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
      </button>
      <div ref={chartContainerRef} style={{ width: '100%', height: isFullscreen ? 'calc(100vh - 40px)' : '350px' }} />
    </div>
  );
}
