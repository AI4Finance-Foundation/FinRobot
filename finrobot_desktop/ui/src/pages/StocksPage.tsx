/**
 * StocksPage — the main stock analysis workstation.
 *
 * Routes:
 *   /stocks           → empty state (no ticker)
 *   /stocks/:ticker   → full analysis view
 *
 * Layout (per UI_DESIGN.md §3.1):
 *   StockHeader  — ticker, price, change, market cap, watchlist button
 *   VerbToolbar  — 6 verb-action buttons (DCF / LBO / Comps / Catalysts / IC Memo / Ask AI)
 *   Tab bar      — 6 tabs: 估值 / 财务 / 同业 / 走势 / 新闻 / 历史
 *   Tab content  — existing view components reused unchanged
 *
 * Behaviour:
 *  - Switching ticker cancels inflight requests via AbortController
 *  - Empty state shows recent 10 tickers from localStorage
 *  - Invalid ticker format rejected client-side (no request sent)
 *  - Each tab's loading / error state is independent
 *  - 1-6 keyboard shortcuts switch tabs; Cmd+R refetches current ticker
 */

import {
  useEffect,
  useCallback,
  useRef,
  useMemo,
  useState,
} from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'

// Stores
import { useAppStore } from '../stores/appStore'
import { useStocksStore, isValidTicker, type StocksTab, type ToolName } from '../stores/stocksStore'

// Hooks
import { useTickerPrice } from '../hooks/useTickerData'

// Components
import { ErrorBoundary } from '../components/ErrorBoundary'
import VerbToolbar from '../components/VerbToolbar'
import WarningBanner from '../components/WarningBanner'
import ToastContainer from '../components/Toast'

// Tab views (existing — not rewritten)
import ValuationTab from '../views/ValuationTab'
import FinancialsTab from '../views/FinancialsTab'
import PeersTab from '../views/PeersTab'
import PerformanceTab from '../views/PerformanceTab'
import NewsTab from '../views/NewsTab'
import HistoryTab from '../views/HistoryTab'

// Utils
import { fmtPrice, fmtUsd } from '../utils/formatters'

// ── Tab configuration ─────────────────────────────────────────────────────────

interface TabConfig {
  key: StocksTab
  label: string
  shortcut: string  // 1-6
}

const TABS: TabConfig[] = [
  { key: 'valuation',   label: '估值',  shortcut: '1' },
  { key: 'financials',  label: '财务',  shortcut: '2' },
  { key: 'peers',       label: '同业',  shortcut: '3' },
  { key: 'performance', label: '走势',  shortcut: '4' },
  { key: 'news',        label: '新闻',  shortcut: '5' },
  { key: 'history',     label: '历史',  shortcut: '6' },
]

// Quick-access tickers for empty state
const QUICK_TICKERS = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'META', 'GOOGL', 'BRKB']

// ── StockHeader ───────────────────────────────────────────────────────────────

interface StockHeaderNewProps {
  ticker: string
}

function StockHeaderNew({ ticker }: StockHeaderNewProps) {
  const { data, isLoading } = useTickerPrice(ticker)
  const { watchlist, toggleWatchlist } = useStocksStore()
  const isWatched = watchlist.has(ticker)

  const change = data?.change ?? 0
  const changeColor = change >= 0 ? 'var(--positive)' : 'var(--negative)'
  const changePct = data?.change_pct ?? 0

  if (isLoading) {
    return (
      <div
        className="stock-header"
        aria-busy="true"
        aria-label="Loading stock data"
        style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 0' }}
      >
        <div className="skeleton" style={{ width: 80, height: 28, borderRadius: 4 }} />
        <div className="skeleton" style={{ width: 120, height: 20, borderRadius: 4 }} />
        <div className="skeleton" style={{ width: 80, height: 16, borderRadius: 4 }} />
      </div>
    )
  }

  const companyName = data?.company_name ?? ''
  const truncatedName =
    companyName.length > 40 ? companyName.slice(0, 40) + '…' : companyName

  return (
    <div
      className="stock-header"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '10px 0',
        flexWrap: 'wrap',
      }}
    >
      {/* Ticker */}
      <span
        className="stock-ticker"
        style={{
          fontFamily: 'var(--font-mono)',
          fontWeight: 700,
          fontSize: '1.4rem',
          color: 'var(--gold)',
          letterSpacing: '0.04em',
        }}
      >
        {ticker}
      </span>

      {/* Company name — truncated with full name in title */}
      {truncatedName && (
        <span
          style={{
            fontSize: '0.88rem',
            color: 'var(--text-secondary)',
            maxWidth: 260,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={companyName}
        >
          {truncatedName}
        </span>
      )}

      {/* Price */}
      {data?.current_price != null && (
        <span
          className="stock-price"
          style={{
            fontFamily: 'var(--font-mono)',
            fontWeight: 600,
            fontSize: '1.1rem',
            color: 'var(--text-primary)',
          }}
        >
          {fmtPrice(data.current_price)}
        </span>
      )}

      {/* Change */}
      {data?.change != null && (
        <span
          className="stock-change"
          style={{ color: changeColor, fontSize: '0.88rem', fontFamily: 'var(--font-mono)' }}
        >
          {change >= 0 ? '+' : ''}{change.toFixed(2)} ({changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%)
        </span>
      )}

      {/* Market cap */}
      {data?.market_cap != null && (
        <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
          Mkt cap {fmtUsd(data.market_cap)}
        </span>
      )}

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Watchlist button */}
      <button
        onClick={() => toggleWatchlist(ticker)}
        aria-label={isWatched ? 'Remove from watchlist' : 'Add to watchlist'}
        aria-pressed={isWatched}
        style={{
          padding: '4px 12px',
          fontSize: '0.75rem',
          fontWeight: 500,
          border: `1px solid ${isWatched ? 'var(--gold)' : 'var(--border)'}`,
          borderRadius: 4,
          background: isWatched ? 'var(--gold-dim)' : 'transparent',
          color: isWatched ? 'var(--gold)' : 'var(--text-muted)',
          cursor: 'pointer',
          transition: 'all 0.15s',
          whiteSpace: 'nowrap',
        }}
      >
        {isWatched ? '★ 已关注' : '☆ 加入关注'}
      </button>
    </div>
  )
}

// ── StocksTabBar ──────────────────────────────────────────────────────────────

interface StocksTabBarProps {
  activeTab: StocksTab
  onTabChange: (tab: StocksTab) => void
}

function StocksTabBar({ activeTab, onTabChange }: StocksTabBarProps) {
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLButtonElement>, tab: StocksTab) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onTabChange(tab)
      }
    },
    [onTabChange],
  )

  return (
    <div
      role="tablist"
      aria-label="Analysis sections"
      className="tab-bar"
      style={{ display: 'flex', gap: 2 }}
    >
      {TABS.map((tab) => (
        <button
          key={tab.key}
          role="tab"
          aria-selected={activeTab === tab.key}
          aria-controls={`tabpanel-${tab.key}`}
          id={`tab-${tab.key}`}
          className={`tab-btn${activeTab === tab.key ? ' active' : ''}`}
          onClick={() => onTabChange(tab.key)}
          onKeyDown={(e) => handleKeyDown(e, tab.key)}
          title={`${tab.label} (${tab.shortcut})`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

interface EmptyStateProps {
  onTickerSelect: (ticker: string) => void
}

function EmptyState({ onTickerSelect }: EmptyStateProps) {
  const recentTickers = useStocksStore((s) => s.recentTickers)
  const [inputValue, setInputValue] = useState('')
  const [inputError, setInputError] = useState('')
  const navigate = useNavigate()

  const handleInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.value.toUpperCase().replace(/[^A-Z0-9.\-]/g, '')
      setInputValue(val)
      setInputError('')
    },
    [],
  )

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      const t = inputValue.trim().toUpperCase()
      if (!t) return
      if (!isValidTicker(t)) {
        setInputError('Invalid ticker format (letters, digits, . and - only, max 12 chars)')
        return
      }
      navigate(`/stocks/${t}`)
    },
    [inputValue, navigate],
  )

  const tickers = recentTickers.length > 0 ? recentTickers : QUICK_TICKERS

  return (
    <div
      className="idle-right animate-in"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 'var(--sp-10)',
        gap: 'var(--sp-6)',
        minHeight: 400,
      }}
    >
      <div
        style={{
          fontSize: '1rem',
          color: 'var(--text-secondary)',
          textAlign: 'center',
        }}
      >
        输入 ticker 或从下方选择
      </div>

      {/* Ticker input */}
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 8 }}>
        <div style={{ position: 'relative' }}>
          <input
            type="text"
            value={inputValue}
            onChange={handleInput}
            placeholder="AAPL"
            maxLength={12}
            aria-label="Ticker symbol"
            aria-describedby={inputError ? 'ticker-error' : undefined}
            style={{
              padding: '7px 12px',
              fontSize: '0.9rem',
              fontFamily: 'var(--font-mono)',
              border: `1px solid ${inputError ? 'var(--negative)' : 'var(--border)'}`,
              borderRadius: 4,
              background: 'var(--surface)',
              color: 'var(--text-primary)',
              width: 140,
              outline: 'none',
            }}
          />
          {inputError && (
            <div
              id="ticker-error"
              role="alert"
              style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                marginTop: 4,
                fontSize: '0.72rem',
                color: 'var(--negative)',
                width: 240,
                zIndex: 10,
              }}
            >
              {inputError}
            </div>
          )}
        </div>
        <button
          type="submit"
          disabled={!inputValue.trim()}
          className="btn"
          aria-label="Load ticker"
        >
          分析
        </button>
      </form>

      {/* Recent / Quick tickers */}
      <div style={{ textAlign: 'center' }}>
        <div
          style={{
            fontSize: '0.72rem',
            color: 'var(--text-muted)',
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            marginBottom: 'var(--sp-3)',
          }}
        >
          {recentTickers.length > 0 ? '最近' : '快捷'}
        </div>
        <div
          className="idle-ticker-grid"
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 8,
            justifyContent: 'center',
            maxWidth: 400,
          }}
        >
          {tickers.slice(0, 10).map((t) => (
            <button
              key={t}
              className="idle-ticker-btn"
              onClick={() => onTickerSelect(t)}
              aria-label={`Load ${t}`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Main StocksPage ───────────────────────────────────────────────────────────

export function StocksPage() {
  const { ticker: rawTicker } = useParams<{ ticker?: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // Normalise ticker from URL
  const ticker = rawTicker?.toUpperCase() ?? ''

  // Local stores
  const { activeTab, setActiveTab, setCurrentTicker } = useStocksStore()
  const appStore = useAppStore()
  const warnings = appStore.warnings

  // AbortController ref — cancelled on ticker change
  const abortRef = useRef<AbortController | null>(null)

  // Sync URL ticker → stores
  useEffect(() => {
    // Cancel previous ticker's in-flight requests
    if (abortRef.current) {
      abortRef.current.abort()
    }
    abortRef.current = new AbortController()

    if (ticker) {
      setCurrentTicker(ticker)
      // Also sync to the legacy appStore so existing chart hooks keep working
      appStore.setTicker(ticker)
      appStore.setPhase('data_ready')
    } else {
      setCurrentTicker('')
    }

    return () => {
      abortRef.current?.abort()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker])

  // Navigate to a ticker
  const handleTickerSelect = useCallback(
    (t: string) => {
      if (!isValidTicker(t)) return
      navigate(`/stocks/${t.toUpperCase()}`)
    },
    [navigate],
  )

  // Cmd+R — refetch current ticker
  const handleGlobalKeyDown = useCallback(
    (e: globalThis.KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      // 1-6 switch tabs
      const tabIndex = parseInt(e.key, 10) - 1
      if (!e.metaKey && !e.ctrlKey && tabIndex >= 0 && tabIndex < TABS.length) {
        e.preventDefault()
        setActiveTab(TABS[tabIndex].key)
        return
      }

      // Cmd+R / Ctrl+R — refetch
      if ((e.metaKey || e.ctrlKey) && e.key === 'r') {
        e.preventDefault()
        if (ticker) {
          void queryClient.invalidateQueries({ queryKey: ['ticker-price', ticker] })
          void queryClient.invalidateQueries({ queryKey: ['ticker-financials', ticker] })
        }
      }
    },
    [ticker, setActiveTab, queryClient],
  )

  useEffect(() => {
    window.addEventListener('keydown', handleGlobalKeyDown)
    return () => window.removeEventListener('keydown', handleGlobalKeyDown)
  }, [handleGlobalKeyDown])

  // Tab content renderer
  const tabContent = useMemo(() => {
    if (!ticker) return null

    switch (activeTab) {
      case 'valuation':
        return <ValuationTab />
      case 'financials':
        return <FinancialsTab />
      case 'peers':
        return <PeersTab />
      case 'performance':
        return <PerformanceTab />
      case 'news':
        return <NewsTab />
      case 'history':
        return <HistoryTab ticker={ticker} />
      default:
        return null
    }
  }, [ticker, activeTab])

  // ── Render ──────────────────────────────────────────────────────────────────

  // No ticker selected — show empty state
  if (!ticker) {
    return (
      <div
        style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
      >
        <EmptyState onTickerSelect={handleTickerSelect} />
        <ToastContainer />
      </div>
    )
  }

  // Invalid ticker format — reject immediately
  if (!isValidTicker(ticker)) {
    return (
      <div
        style={{
          padding: 'var(--sp-8)',
          color: 'var(--negative)',
          fontSize: '0.9rem',
        }}
        role="alert"
      >
        Invalid ticker format: <strong>{ticker}</strong>
        <br />
        <button
          onClick={() => navigate('/stocks')}
          style={{
            marginTop: 'var(--sp-3)',
            background: 'none',
            border: 'none',
            color: 'var(--gold)',
            cursor: 'pointer',
            textDecoration: 'underline',
          }}
        >
          Back to search
        </button>
      </div>
    )
  }

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* ── Header section ── */}
      <div
        style={{
          padding: '0 var(--sp-5)',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}
      >
        {/* Stock header: ticker + price + change + market cap + watchlist */}
        <ErrorBoundary>
          <StockHeaderNew ticker={ticker} />
        </ErrorBoundary>

        {/* Warnings */}
        {warnings.length > 0 && (
          <ErrorBoundary>
            <WarningBanner warnings={warnings} />
          </ErrorBoundary>
        )}

        {/* Verb toolbar */}
        <ErrorBoundary>
          <VerbToolbar
            ticker={ticker}
            onToolComplete={(tool: ToolName) => {
              // Switch to relevant tab after tool completes
              const tabMap: Record<ToolName, StocksTab> = {
                dcf:        'valuation',
                lbo:        'valuation',
                comps:      'peers',
                catalysts:  'news',
                'ic-memo':  'history',
                'ask-ai':   activeTab,
              }
              setActiveTab(tabMap[tool])
            }}
          />
        </ErrorBoundary>

        {/* Tab bar */}
        <StocksTabBar activeTab={activeTab} onTabChange={setActiveTab} />
      </div>

      {/* ── Tab content ── */}
      <div
        id={`tabpanel-${activeTab}`}
        role="tabpanel"
        aria-labelledby={`tab-${activeTab}`}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: 'var(--sp-4) var(--sp-5)',
        }}
      >
        <ErrorBoundary>
          {tabContent}
        </ErrorBoundary>
      </div>

      <ToastContainer />
    </div>
  )
}
