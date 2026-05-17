/**
 * Sidebar — 200px left nav replacing the old ActivityBar.
 *
 * Sections:
 *   1. NAVIGATE — 6 nav items with icon + label, accent active state
 *   2. WATCHLIST — live ticker list from stocksStore + add-ticker input
 */

import { useState, useRef, useEffect, useMemo } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useQueries } from '@tanstack/react-query'
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
import { BASE_URL } from '../api/client'

interface PriceData {
  current_price: number
  change_pct: number
  prev_close?: number
}

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
  { label: '工作台',   path: '/dashboard',   Icon: IconHome },
  { label: '个股分析', path: '/stocks',       Icon: IconTrendingUp },
  { label: '估值推演', path: '/playground',   Icon: IconPlayground },
  { label: '决策日记', path: '/journal',      Icon: IconJournal },
  { label: '报告库',   path: '/library',      Icon: IconFileText },
  { label: '设置',     path: '/settings',     Icon: IconSettings },
] as const

// ── WatchlistItem — renders one ticker row with live price ────────────────────

function WatchlistItem({ ticker, active }: { ticker: string; active: boolean }) {
  const navigate = useNavigate()
  const { data, isLoading } = useTickerPrice(ticker)
  const toggleWatchlist = useStocksStore((s) => s.toggleWatchlist)
  const [hover, setHover] = useState(false)

  const price = data?.current_price
  const changePct = data?.change_pct
  const isPositive = changePct !== undefined && changePct >= 0

  const itemStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '6px 12px',
    margin: '1px 8px',
    cursor: 'pointer',
    background: active ? 'var(--accent-dim)' : hover ? 'var(--bg-3)' : 'transparent',
    borderRadius: 'var(--r-sm)',
    transition: 'all 0.15s',
    minHeight: 30,
    gap: 6,
  }

  const tickerStyle: React.CSSProperties = {
    fontFamily: 'var(--font-mono)',
    fontWeight: 700,
    fontSize: 12,
    color: active ? 'var(--accent)' : 'var(--text-secondary)',
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

  function priceLabel(): React.ReactNode {
    if (isLoading) {
      return (
        <span style={{ width: 38, height: 8, borderRadius: 2, background: 'var(--bg-3)', display: 'inline-block', animation: 'skeleton-pulse 1.5s ease infinite' }} />
      )
    }
    if (price === undefined) return '—'
    return `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  }

  return (
    <div
      style={itemStyle}
      onClick={() => navigate(`/stocks/${ticker}`)}
      onKeyDown={(e) => e.key === 'Enter' && navigate(`/stocks/${ticker}`)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      role="button"
      tabIndex={0}
      aria-label={`View ${ticker}`}
    >
      <span style={tickerStyle}>{ticker}</span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 0 }}>
        <span style={priceStyle}>{priceLabel()}</span>
        {hover && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              toggleWatchlist(ticker)
            }}
            aria-label={`从自选股移除 ${ticker}`}
            title="从自选股移除"
            style={{
              border: 'none',
              background: 'transparent',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              padding: '0 2px',
              fontSize: 13,
              lineHeight: 1,
              display: 'flex',
              alignItems: 'center',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--negative)')}
            onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
          >
            ×
          </button>
        )}
      </span>
    </div>
  )
}

// ── AddTickerInput ────────────────────────────────────────────────────────────

function AddTickerInput() {
  const [value, setValue] = useState('')
  const [errMsg, setErrMsg] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const toggleWatchlist = useStocksStore((s) => s.toggleWatchlist)
  const watchlist = useStocksStore((s) => s.watchlist)

  function handleSubmit() {
    const upper = value.trim().toUpperCase()
    if (!upper) return
    if (!isValidTicker(upper)) {
      setErrMsg('代码格式无效（A-Z / 0-9，1-12 位）')
      return
    }
    if (watchlist.has(upper)) {
      setErrMsg(`${upper} 已在自选股中`)
      return
    }
    toggleWatchlist(upper)
    setValue('')
    setErrMsg(null)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.nativeEvent.isComposing) return
    if (e.key === 'Enter') {
      handleSubmit()
    } else if (e.key === 'Escape') {
      setValue('')
      setErrMsg(null)
      inputRef.current?.blur()
    } else {
      setErrMsg(null)
    }
  }

  const error = errMsg !== null

  const wrapStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
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
    <div style={{ margin: '4px 8px 0' }}>
      <div style={wrapStyle}>
        <input
          ref={inputRef}
          style={inputStyle}
          placeholder="+ NVDA / TSLA"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          maxLength={12}
          aria-label="添加自选股代码"
        />
        <button
          style={addBtnStyle}
          onClick={handleSubmit}
          onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--accent)')}
          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
          aria-label="添加自选股"
          tabIndex={-1}
        >
          <IconPlus size={12} />
        </button>
      </div>
      {errMsg && (
        <div
          role="alert"
          style={{
            fontFamily: 'var(--font-ui)',
            fontSize: 10,
            color: 'var(--negative)',
            padding: '3px 4px 0',
            lineHeight: 1.4,
          }}
        >
          {errMsg}
        </div>
      )}
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
    width: 220,
    minWidth: 220,
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
    fontSize: 10,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.10em',
    color: 'var(--text-muted)',
    padding: '16px 16px 8px',
    userSelect: 'none',
  }

  // ── Watchlist: fetch all prices in parallel + sort by |change_pct| DESC ──
  // Each query uses the same key as WatchlistItem.useTickerPrice → cache shared,
  // no double fetch. We just need the data here to drive sort order.
  const tickerList = useMemo(() => Array.from(watchlist), [watchlist])
  const priceQueries = useQueries({
    queries: tickerList.map((ticker) => ({
      queryKey: ['ticker-price', ticker],
      queryFn: async ({ signal }: { signal?: AbortSignal }): Promise<PriceData> => {
        const r = await fetch(`${BASE_URL}/api/data/${ticker}/price`, { signal })
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json() as Promise<PriceData>
      },
      enabled: !!ticker,
      staleTime: 60_000,
      refetchInterval: 60_000,
      retry: 2,
    })),
  })

  const watchlistItems = useMemo(() => {
    // Build [ticker, |change_pct|] then sort DESC. Tickers without data go last
    // (stable order by name).
    const withChange = tickerList.map((ticker, i) => ({
      ticker,
      abs: Math.abs(priceQueries[i]?.data?.change_pct ?? -Infinity),
      hasData: priceQueries[i]?.data != null,
    }))
    return withChange
      .sort((a, b) => {
        if (a.hasData !== b.hasData) return a.hasData ? -1 : 1
        if (a.abs !== b.abs) return b.abs - a.abs
        return a.ticker.localeCompare(b.ticker)
      })
      .map((x) => x.ticker)
  }, [tickerList, priceQueries])

  return (
    <aside className="sidebar" style={sidebarStyle} data-testid="sidebar">
      {/* ── NAVIGATE section ── */}
      <div>
        <div style={sectionHeaderStyle}>导航</div>
        {NAV_ITEMS.map(({ label, path, Icon }) => {
          const active = isNavActive(path)
          const itemStyle: React.CSSProperties = {
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '8px 16px',
            margin: '1px 8px',
            cursor: 'pointer',
            background: active ? 'var(--accent-dim)' : 'transparent',
            color: active ? 'var(--accent)' : 'var(--text-secondary)',
            fontSize: 13,
            fontWeight: active ? 600 : 400,
            transition: 'all 0.15s',
            userSelect: 'none',
            border: 'none',
            width: 'calc(100% - 16px)',
            textAlign: 'left',
            fontFamily: 'var(--font-ui)',
            boxSizing: 'border-box',
            borderRadius: 'var(--r-sm)',
            position: 'relative',
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
              <Icon size={15} />
              <span>{label}</span>
            </button>
          )
        })}
      </div>

      {/* ── Divider ── */}
      <div style={{ height: 1, background: 'var(--border)', margin: '10px 16px' }} />

      {/* ── WATCHLIST section ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={sectionHeaderStyle}>自选股</div>

        {watchlistItems.length === 0 ? (
          <div style={{
            fontFamily: 'var(--font-ui)',
            fontSize: 12,
            color: 'var(--text-muted)',
            padding: '4px 16px 8px',
            fontStyle: 'italic',
          }}>
            暂无自选股
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

    </aside>
  )
}
