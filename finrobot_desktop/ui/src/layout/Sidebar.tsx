/**
 * Sidebar — 200px left nav replacing the old ActivityBar.
 *
 * Sections:
 *   1. NAVIGATE — 6 nav items with icon + label, gold active state
 *   2. WATCHLIST — live ticker list from stocksStore + add-ticker input
 */

import { useState, useRef, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  IconHome,
  IconTrendingUp,
  IconFileText,
  IconSettings,
  IconActivity,
  IconDatabase,
  IconPlus,
} from '../lib/icons'
import { useStocksStore, isValidTicker } from '../stores/stocksStore'
import { useTickerPrice } from '../hooks/useTickerData'

// ── Inline SVG icons for routes not in icons.tsx ────────────────────────────

function IconPlayground({ size = 16 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2V9M9 21H5a2 2 0 0 1-2-2V9m0 0h18" />
    </svg>
  )
}

function IconJournal({ size = 16 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
      <line x1="8" y1="7" x2="15" y2="7" />
      <line x1="8" y1="11" x2="15" y2="11" />
    </svg>
  )
}

// ── Nav items config ──────────────────────────────────────────────────────────

const NAV_ITEMS = [
  { label: 'Dashboard',   path: '/dashboard',   Icon: IconHome },
  { label: 'Stocks',      path: '/stocks',       Icon: IconTrendingUp },
  { label: 'Playground',  path: '/playground',   Icon: IconPlayground },
  { label: 'Journal',     path: '/journal',      Icon: IconJournal },
  { label: 'Library',     path: '/library',      Icon: IconFileText },
  { label: 'Settings',    path: '/settings',     Icon: IconSettings },
] as const

// ── WatchlistItem — renders one ticker row with live price ────────────────────

function WatchlistItem({ ticker, active }: { ticker: string; active: boolean }) {
  const navigate = useNavigate()
  const { data } = useTickerPrice(ticker)

  const price = data?.current_price
  const changePct = data?.change_pct
  const isPositive = changePct !== undefined && changePct >= 0

  const itemStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '5px 12px',
    cursor: 'pointer',
    borderLeft: active ? '2px solid var(--gold)' : '2px solid transparent',
    background: active ? 'var(--gold-dim)' : 'transparent',
    transition: 'all 0.12s',
    minHeight: 28,
  }

  const tickerStyle: React.CSSProperties = {
    fontFamily: 'var(--font-mono)',
    fontWeight: 700,
    fontSize: 12,
    color: active ? 'var(--gold)' : 'var(--text-secondary)',
    letterSpacing: '0.04em',
  }

  const priceStyle: React.CSSProperties = {
    fontFamily: 'var(--font-mono)',
    fontSize: 11,
    color: price !== undefined
      ? (isPositive ? 'var(--positive)' : 'var(--negative)')
      : 'var(--text-muted)',
    fontVariantNumeric: 'tabular-nums',
  }

  return (
    <div
      style={itemStyle}
      onClick={() => navigate(`/stocks/${ticker}`)}
      onKeyDown={(e) => e.key === 'Enter' && navigate(`/stocks/${ticker}`)}
      role="button"
      tabIndex={0}
      aria-label={`View ${ticker}`}
    >
      <span style={tickerStyle}>{ticker}</span>
      <span style={priceStyle}>
        {price !== undefined
          ? `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
          : '—'}
      </span>
    </div>
  )
}

// ── AddTickerInput ────────────────────────────────────────────────────────────

function AddTickerInput() {
  const [value, setValue] = useState('')
  const [error, setError] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const toggleWatchlist = useStocksStore((s) => s.toggleWatchlist)
  const watchlist = useStocksStore((s) => s.watchlist)

  function handleSubmit() {
    const upper = value.trim().toUpperCase()
    if (!upper) return
    if (!isValidTicker(upper)) {
      setError(true)
      return
    }
    if (!watchlist.has(upper)) {
      toggleWatchlist(upper)
    }
    setValue('')
    setError(false)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      handleSubmit()
    } else if (e.key === 'Escape') {
      setValue('')
      setError(false)
      inputRef.current?.blur()
    } else {
      setError(false)
    }
  }

  const wrapStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    margin: '4px 8px 0',
    borderRadius: 4,
    border: `1px solid ${error ? 'var(--negative)' : 'var(--border-hover)'}`,
    background: 'var(--bg-2)',
    overflow: 'hidden',
    transition: 'border-color 0.12s',
  }

  const inputStyle: React.CSSProperties = {
    flex: 1,
    fontFamily: 'var(--font-mono)',
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--text-primary)',
    background: 'transparent',
    border: 'none',
    outline: 'none',
    padding: '5px 8px',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
  }

  const addBtnStyle: React.CSSProperties = {
    background: 'transparent',
    border: 'none',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    padding: '5px 7px',
    display: 'flex',
    alignItems: 'center',
    transition: 'color 0.12s',
  }

  return (
    <div style={wrapStyle}>
      <input
        ref={inputRef}
        style={inputStyle}
        placeholder="+ ADD"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        maxLength={12}
        aria-label="Add ticker to watchlist"
      />
      <button
        style={addBtnStyle}
        onClick={handleSubmit}
        onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--gold)')}
        onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
        aria-label="Add ticker"
        tabIndex={-1}
      >
        <IconPlus size={12} />
      </button>
    </div>
  )
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

export function Sidebar(): React.ReactElement {
  const navigate = useNavigate()
  const location = useLocation()
  const watchlist = useStocksStore((s) => s.watchlist)

  const isNavActive = (path: string) => location.pathname.startsWith(path)

  // Extract active ticker from URL (e.g. /stocks/NVDA)
  const tickerMatch = location.pathname.match(/^\/stocks\/([A-Z0-9.\-]{1,12})/)
  const activeTicker = tickerMatch ? tickerMatch[1] : null

  // ── Styles ──────────────────────────────────────────────────────────────────

  const sidebarStyle: React.CSSProperties = {
    width: 200,
    minWidth: 200,
    height: '100%',
    background: 'var(--sidebar-bg)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    overflowY: 'auto',
    flexShrink: 0,
  }

  const sectionHeaderStyle: React.CSSProperties = {
    fontFamily: 'var(--font-mono)',
    fontSize: 9,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.12em',
    color: 'var(--text-muted)',
    padding: '14px 12px 6px',
    userSelect: 'none',
  }

  const footerStyle: React.CSSProperties = {
    fontFamily: 'var(--font-mono)',
    fontSize: 8,
    color: 'var(--text-muted)',
    padding: '8px 12px 12px',
    letterSpacing: '0.04em',
    marginTop: 'auto',
    flexShrink: 0,
  }

  const watchlistItems = Array.from(watchlist)

  return (
    <aside className="sidebar" style={sidebarStyle} data-testid="sidebar">
      {/* ── NAVIGATE section ── */}
      <div>
        <div style={sectionHeaderStyle}>Navigate</div>
        {NAV_ITEMS.map(({ label, path, Icon }) => {
          const active = isNavActive(path)
          const itemStyle: React.CSSProperties = {
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '6px 12px',
            cursor: 'pointer',
            borderLeft: active ? '2px solid var(--gold)' : '2px solid transparent',
            background: active ? 'var(--gold-dim)' : 'transparent',
            color: active ? 'var(--gold)' : 'var(--text-secondary)',
            fontSize: 13,
            fontWeight: active ? 500 : 400,
            transition: 'all 0.12s',
            userSelect: 'none',
            border: 'none',
            width: '100%',
            textAlign: 'left',
            fontFamily: 'var(--font-ui)',
            boxSizing: 'border-box',
            borderLeftWidth: 2,
            borderLeftStyle: 'solid',
            borderLeftColor: active ? 'var(--gold)' : 'transparent',
          }

          return (
            <button
              key={path}
              style={itemStyle}
              onClick={() => navigate(path)}
              onMouseEnter={(e) => {
                if (!active) {
                  e.currentTarget.style.background = 'var(--bg-3)'
                  e.currentTarget.style.color = 'var(--text-primary)'
                }
              }}
              onMouseLeave={(e) => {
                if (!active) {
                  e.currentTarget.style.background = 'transparent'
                  e.currentTarget.style.color = 'var(--text-secondary)'
                }
              }}
              aria-label={label}
              aria-current={active ? 'page' : undefined}
            >
              <Icon size={14} />
              <span>{label}</span>
            </button>
          )
        })}
      </div>

      {/* ── Divider ── */}
      <div style={{ height: 1, background: 'var(--border)', margin: '8px 0' }} />

      {/* ── WATCHLIST section ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={sectionHeaderStyle}>Watchlist</div>

        {watchlistItems.length === 0 ? (
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--text-muted)',
            padding: '4px 12px 8px',
            fontStyle: 'italic',
          }}>
            no tickers added
          </div>
        ) : (
          <div style={{ overflowY: 'auto', flex: 1 }}>
            {watchlistItems.map((ticker) => (
              <WatchlistItem
                key={ticker}
                ticker={ticker}
                active={activeTicker === ticker}
              />
            ))}
          </div>
        )}

        <AddTickerInput />
      </div>

      {/* ── Footer ── */}
      <div style={footerStyle}>
        DELAYED 15M · YFINANCE+FMP
      </div>
    </aside>
  )
}
