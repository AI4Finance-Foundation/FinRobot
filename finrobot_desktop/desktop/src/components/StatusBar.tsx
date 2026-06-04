// StatusBar — terminal-style footer: REAL backend/data health + data source + version.
//
// BUG-20260602-025: this used to hardcode a green "已连接 / YFINANCE + FMP" dot
// regardless of backend or provider state. It now reflects useHealth():
//   offline    → backend unreachable / health probe errored (red dot)
//   degraded   → reachable but quotes not warmed, a boot config error, or no
//                data providers configured (amber dot)
//   connected  → backend up, quotes warmed, providers configured (green dot)
// The data-source label is honest: it lists only the providers the backend
// actually reports as configured (via /api/settings), instead of asserting
// "YFINANCE + FMP" unconditionally.

import { useLocation } from 'react-router-dom'
import { useI18n } from '../i18n'
import { useHealth, type HealthLevel } from '../hooks/useHealth'

// Maps provider ids (from /api/settings available_providers) to display labels.
// Only providers the backend reports are shown — keeps the footer honest.
const PROVIDER_LABELS: Record<string, string> = {
  yfinance: 'YFINANCE',
  fmp: 'FMP',
  finnhub: 'FINNHUB',
  alpha_vantage: 'ALPHA VANTAGE',
  sec_edgar: 'SEC EDGAR',
  adanos: 'ADANOS',
}

// Data-source label only counts market-data providers (drop news/edgar noise
// for the compact footer, but still honest about what's configured).
const DATA_SOURCE_ORDER = ['yfinance', 'fmp', 'finnhub', 'alpha_vantage']

const DOT_TOKEN: Record<HealthLevel, string> = {
  connected: 'var(--success)',
  degraded: 'var(--warning)',
  offline: 'var(--danger)',
}

export default function StatusBar(): React.ReactElement {
  const location = useLocation()
  const { t, locale } = useI18n()
  const { data: health } = useHealth()

  const level: HealthLevel = health?.level ?? 'offline'

  const tickerMatch = location.pathname.match(/\/stocks\/([A-Z0-9.]+)/i)
  const ticker = tickerMatch ? tickerMatch[1].toUpperCase() : null

  // ── Left: connection status text + colored dot ──
  const statusText =
    level === 'connected'
      ? t('shell.status.connected')
      : level === 'degraded'
        ? locale === 'zh'
          ? '数据降级'
          : 'Data degraded'
        : locale === 'zh'
          ? '后端离线'
          : 'Backend offline'

  // Detail tooltip — explains WHY degraded/offline so the dot isn't cryptic.
  const detail =
    health?.startupError ??
    (level === 'offline'
      ? locale === 'zh'
        ? '无法连接后端服务'
        : 'Cannot reach backend service'
      : level === 'degraded' && !health?.quotesWarmed
        ? locale === 'zh'
          ? '行情缓存预热中'
          : 'Warming quote cache'
        : level === 'degraded'
          ? locale === 'zh'
            ? '未配置数据源'
            : 'No data provider configured'
          : undefined)

  // ── Center: honest data-source label ──
  const configured = health?.availableProviders ?? []
  const sources = DATA_SOURCE_ORDER.filter((p) => configured.includes(p)).map(
    (p) => PROVIDER_LABELS[p],
  )
  const sourceLabel =
    sources.length > 0 ? sources.join(' + ') : locale === 'zh' ? '无数据源' : 'No data source'

  return (
    <div className="statusbar" data-testid="statusbar">
      {/* Left: connection status */}
      <div className="sb-section sb-left" title={detail}>
        <span
          className="sb-pulse-dot"
          style={{ background: DOT_TOKEN[level] }}
          data-level={level}
        />
        <span className="sb-text">{statusText}</span>
      </div>

      {/* Center: data source info */}
      <div className="sb-section sb-center">
        <span className="sb-text">
          {sourceLabel}
          {sources.length > 0 ? ` · ${t('shell.status.delay15min')}` : ''}
        </span>
      </div>

      {/* Right: version + optional ticker */}
      <div className="sb-section sb-right">
        {ticker && (
          <>
            <span className="sb-text sb-ticker">{ticker}</span>
            <span className="sb-sep">·</span>
          </>
        )}
        <span className="sb-text">FINROBOT v0.1.0</span>
      </div>
    </div>
  )
}
