// StatusBar — terminal-style: connected indicator + data source + version.

import { useLocation } from 'react-router-dom'

export default function StatusBar(): React.ReactElement {
  const location = useLocation()

  const tickerMatch = location.pathname.match(/\/stocks\/([A-Z0-9.]+)/i)
  const ticker = tickerMatch ? tickerMatch[1].toUpperCase() : null

  return (
    <div className="statusbar" data-testid="statusbar">
      {/* Left: connection status */}
      <div className="sb-section sb-left">
        <span className="sb-pulse-dot" />
        <span className="sb-text">已连接</span>
      </div>

      {/* Center: data source info */}
      <div className="sb-section sb-center">
        <span className="sb-text">YFINANCE + FMP · 延迟15分钟</span>
      </div>

      {/* Right: version + optional ticker */}
      <div className="sb-section sb-right">
        {ticker && (
          <>
            <span className="sb-text sb-ticker">{ticker}</span>
            <span className="sb-sep">·</span>
          </>
        )}
        <span className="sb-text">FINAGENT v0.1.0</span>
      </div>
    </div>
  )
}
