// WatchlistTab — the live watchlist that used to live inside Sidebar.tsx.
//
// Owns: WatchlistItem rows (live price + 7d sparkline + 💡 why-moving + ×
// remove), aggregate banner (avg / win / loss + LLM summary CTA),
// AddTickerInput, EmptyWatchlistHint.
//
// Mounted by RightChatPanel/index.tsx as the top-half tab content. Watch-
// list state is in `useStocksStore`; per-ticker price comes from the same
// `useTickerPrice` hook the rest of the app uses, so the data is shared
// with the ticker workspace via react-query cache.

import { useMemo, useRef, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useQueries } from '@tanstack/react-query'
import { useStocksStore, isValidTicker } from '../../stores/stocksStore'
import { useUiStore } from '../../stores/uiStore'
import { useTickerPrice } from '../../hooks/useTickerData'
import { BASE_URL } from '../../api/client'
import { WhyMovingPopover } from '../../components/WhyMovingPopover'
import { Sparkline } from '../../components/Sparkline'
import { IconPlus } from '../../lib/icons'

interface PriceData {
  current_price: number
  change_pct: number
  prev_close?: number
}

// ── WatchlistItem ─────────────────────────────────────────────────────────
function WatchlistItem({ ticker, active }: { ticker: string; active: boolean }) {
  const navigate = useNavigate()
  const { data, isLoading } = useTickerPrice(ticker)
  const toggleWatchlist = useStocksStore((s) => s.toggleWatchlist)
  const [hover, setHover] = useState(false)

  const price = data?.current_price ?? undefined
  const changePct = data?.change_pct ?? undefined
  const isPositive = changePct !== undefined && changePct >= 0

  const sparkValues = useMemo(() => {
    const history = data?.history
    if (!history || history.length === 0) return []
    return history.slice(-7).map((p) => p.close)
  }, [data?.history])

  const itemStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '8px 12px',
    margin: '2px 8px',
    cursor: 'pointer',
    background: active
      ? 'var(--primary-soft)'
      : hover
        ? 'rgba(255,255,255,0.03)'
        : 'transparent',
    borderRadius: 'var(--radius-sm)',
    border: `1px solid ${active ? 'var(--border-glow)' : 'transparent'}`,
    transition: 'all 0.15s',
    minHeight: 34,
    gap: 8,
  }

  function priceLabel(): React.ReactNode {
    if (isLoading) {
      return (
        <span
          style={{
            width: 38,
            height: 8,
            borderRadius: 2,
            background: 'var(--bg-card)',
            display: 'inline-block',
            animation: 'skeleton-pulse 1.5s ease infinite',
          }}
        />
      )
    }
    if (price === undefined || price === null) return '—'
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
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontWeight: 700,
          fontSize: 12,
          color: active ? 'var(--primary)' : 'var(--text-secondary)',
          letterSpacing: '0.04em',
        }}
      >
        {ticker}
      </span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
        {sparkValues.length >= 2 && (
          <Sparkline values={sparkValues} width={34} height={11} />
        )}
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: price !== undefined
              ? (isPositive ? 'var(--success)' : 'var(--danger)')
              : 'var(--text-muted)',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {priceLabel()}
        </span>
        {hover && (
          <>
            <WhyMovingPopover ticker={ticker}>
              {({ onClick, ariaExpanded }) => (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onClick(e)
                  }}
                  aria-label={`查看 ${ticker} 今日动向`}
                  aria-expanded={ariaExpanded}
                  title="为啥动？"
                  style={iconBtnStyle}
                >
                  💡
                </button>
              )}
            </WhyMovingPopover>
            <button
              onClick={(e) => {
                e.stopPropagation()
                toggleWatchlist(ticker)
              }}
              aria-label={`从自选股移除 ${ticker}`}
              title="从自选股移除"
              style={iconBtnStyle}
            >
              ×
            </button>
          </>
        )}
      </span>
    </div>
  )
}

const iconBtnStyle: React.CSSProperties = {
  border: 'none',
  background: 'transparent',
  color: 'var(--text-muted)',
  cursor: 'pointer',
  padding: '0 2px',
  fontSize: 12,
  lineHeight: 1,
  display: 'flex',
  alignItems: 'center',
}

// ── EmptyWatchlistHint ─────────────────────────────────────────────────────
const SUGGESTED_TICKERS = ['AAPL', 'NVDA', 'TSLA', 'MSFT'] as const

function EmptyWatchlistHint(): React.ReactElement {
  const toggleWatchlist = useStocksStore((s) => s.toggleWatchlist)
  return (
    <div style={{ padding: '8px 14px' }}>
      <div
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: 11,
          color: 'var(--text-muted)',
          lineHeight: 1.5,
          marginBottom: 8,
        }}
      >
        试试加几只熟悉的：
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {SUGGESTED_TICKERS.map((ticker) => (
          <button
            key={ticker}
            onClick={() => toggleWatchlist(ticker)}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              fontWeight: 600,
              color: 'var(--primary)',
              background: 'var(--primary-soft)',
              border: '1px solid transparent',
              borderRadius: 4,
              padding: '3px 9px',
              cursor: 'pointer',
              letterSpacing: '0.04em',
              transition: 'border-color 0.12s',
            }}
            title={`添加 ${ticker} 到自选股`}
            type="button"
          >
            + {ticker}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── AddTickerInput ─────────────────────────────────────────────────────────
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
    if (e.key === 'Enter') handleSubmit()
    else if (e.key === 'Escape') {
      setValue('')
      setErrMsg(null)
      inputRef.current?.blur()
    } else {
      setErrMsg(null)
    }
  }

  const error = errMsg !== null
  return (
    <div style={{ margin: '6px 8px 10px' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          borderRadius: 6,
          border: `1px solid ${error ? 'var(--danger)' : 'var(--border-soft)'}`,
          background: 'var(--bg-card)',
          overflow: 'hidden',
        }}
      >
        <input
          ref={inputRef}
          placeholder="+ NVDA / TSLA"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          maxLength={12}
          aria-label="添加自选股代码"
          style={{
            flex: 1,
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            fontWeight: 600,
            color: 'var(--text-primary)',
            background: 'transparent',
            border: 'none',
            outline: 'none',
            padding: '6px 9px',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
          }}
        />
        <button
          onClick={handleSubmit}
          aria-label="添加自选股"
          tabIndex={-1}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            padding: '6px 8px',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <IconPlus size={12} />
        </button>
      </div>
      {errMsg && (
        <div
          role="alert"
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 10,
            color: 'var(--danger)',
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

// ── WatchlistTab ───────────────────────────────────────────────────────────
export function WatchlistTab(): React.ReactElement {
  const location = useLocation()
  const watchlist = useStocksStore((s) => s.watchlist)
  const sendChatPrompt = useUiStore((s) => s.sendChatPrompt)
  const tickerList = useMemo(() => Array.from(watchlist), [watchlist])

  const tickerMatch = location.pathname.match(/^\/stocks\/([A-Z0-9.\-]{1,12})/)
  const activeTicker = tickerMatch ? tickerMatch[1] : null

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

  const ordered = useMemo(() => {
    const enriched = tickerList.map((ticker, i) => ({
      ticker,
      abs: Math.abs(priceQueries[i]?.data?.change_pct ?? -Infinity),
      hasData: priceQueries[i]?.data != null,
    }))
    return enriched
      .sort((a, b) => {
        if (a.hasData !== b.hasData) return a.hasData ? -1 : 1
        if (a.abs !== b.abs) return b.abs - a.abs
        return a.ticker.localeCompare(b.ticker)
      })
      .map((x) => x.ticker)
  }, [tickerList, priceQueries])

  const aggregate = useMemo(() => {
    const changes = priceQueries
      .map((q) => q.data?.change_pct)
      .filter((c): c is number => typeof c === 'number')
    if (changes.length === 0) return null
    const avg = changes.reduce((a, b) => a + b, 0) / changes.length
    const ups = changes.filter((c) => c > 0).length
    const downs = changes.filter((c) => c < 0).length
    return { avg, ups, downs, total: changes.length }
  }, [priceQueries])

  function handleAggregateClick(): void {
    if (!aggregate) return
    const sample = tickerList.slice(0, 8).join(', ')
    sendChatPrompt(
      `点评一下我的自选股今天的整体表现：${aggregate.total} 只均涨幅 ${aggregate.avg.toFixed(2)}% (${aggregate.ups} 涨 ${aggregate.downs} 跌)，包括 ${sample}。中文 2-3 句，指出最值得关注的 1 只。`,
      true,
    )
  }

  return (
    <div
      data-testid="watchlist-tab"
      style={{ display: 'flex', flexDirection: 'column', minHeight: 0, flex: 1 }}
    >
      {aggregate && ordered.length > 0 && (
        <button
          type="button"
          onClick={handleAggregateClick}
          title="点击让 FinAgent 点评今日自选股表现"
          aria-label="点击让 FinAgent 点评今日自选股"
          style={{
            margin: '10px 8px 6px',
            padding: '8px 12px',
            background: 'rgba(15,15,34,0.6)',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-sm)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-secondary)',
            textAlign: 'left',
          }}
        >
          <span
            style={{
              color: aggregate.avg >= 0 ? 'var(--success)' : 'var(--danger)',
              fontWeight: 700,
            }}
          >
            {aggregate.avg >= 0 ? '+' : ''}
            {aggregate.avg.toFixed(2)}%
          </span>
          <span style={{ color: 'var(--text-muted)' }}>
            {aggregate.ups}↑ {aggregate.downs}↓
          </span>
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 11, color: 'var(--primary)' }}>💬</span>
        </button>
      )}

      {ordered.length === 0 ? (
        <EmptyWatchlistHint />
      ) : (
        <div style={{ overflowY: 'auto', flex: 1 }}>
          {ordered.map((ticker) => (
            <WatchlistItem key={ticker} ticker={ticker} active={activeTicker === ticker} />
          ))}
        </div>
      )}

      <AddTickerInput />
    </div>
  )
}
