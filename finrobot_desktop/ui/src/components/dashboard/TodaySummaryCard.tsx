/**
 * TodaySummaryCard — Dashboard hero.
 *
 * One paragraph of LLM-written narrative summarizing today's market + the
 * user's watchlist, plus a launch input that hands off to RightChatPanel.
 *
 * Backend: POST /api/dashboard/today-summary { watchlist }
 *   → { summary, model, generated_at, market }
 *
 * The card is HONEST: if the LLM call fails, backend returns a deterministic
 * fallback built from real numbers — we never show invented text.
 */

import { useState, useRef, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../../api/client'
import { useStocksStore } from '../../stores/stocksStore'
import { useUiStore } from '../../stores/uiStore'
import { IconSparkle, IconRefresh } from '../../lib/icons'

interface IndexQuote {
  symbol: string
  name: string
  change_pct: number
}

interface WatchlistPrice {
  ticker: string
  price: number
  change_pct: number | null
}

interface UpcomingEarning {
  ticker: string
  date: string
  time?: string
}

interface MarketSnapshot {
  indices: IndexQuote[]
  watchlist_prices: WatchlistPrice[]
  watchlist_avg_change_pct: number | null
  upcoming_earnings: UpcomingEarning[]
}

interface TodaySummary {
  summary: string
  model: string
  generated_at: number
  market: MarketSnapshot
}

async function fetchSummary(watchlist: string[]): Promise<TodaySummary> {
  const r = await fetch(`${BASE_URL}/api/dashboard/today-summary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ watchlist }),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<TodaySummary>
}

function fmtPct(v: number | null | undefined, dp = 2): string {
  if (v == null || isNaN(v)) return '—'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(dp)}%`
}

function relativeTimestamp(unix: number): string {
  const ms = Date.now() - unix * 1000
  const mins = Math.floor(ms / 60_000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  return new Date(unix * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

/** Dynamic suggestion chips derived from the market snapshot — never hard-coded. */
function suggestionChips(market: MarketSnapshot | undefined): string[] {
  if (!market) return ['今天哪些股票便宜？', '解释 VIX 怎么用']
  const chips: string[] = []
  // Suggest the nearest earnings ticker
  const nextEarnings = market.upcoming_earnings?.[0]
  if (nextEarnings) chips.push(`分析 ${nextEarnings.ticker} 财报预期`)
  // Suggest the biggest mover in the watchlist
  if (market.watchlist_prices?.length) {
    const sorted = [...market.watchlist_prices].sort(
      (a, b) => Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0),
    )
    const top = sorted[0]
    if (top && top.change_pct != null) {
      const verb = top.change_pct >= 0 ? '涨' : '跌'
      chips.push(`${top.ticker} ${verb} ${Math.abs(top.change_pct).toFixed(1)}% 的原因？`)
    }
  }
  chips.push('对比同业估值')
  return chips.slice(0, 3)
}

export function TodaySummaryCard(): React.ReactElement {
  const watchlist = useStocksStore((s) => s.watchlist)
  const sendChatPrompt = useUiStore((s) => s.sendChatPrompt)
  const watchlistArr = useMemo(() => Array.from(watchlist).sort(), [watchlist])

  const { data, isLoading, isError, refetch, isFetching } = useQuery<TodaySummary>({
    queryKey: ['dashboard-today-summary', watchlistArr.join(',')],
    queryFn: () => fetchSummary(watchlistArr),
    staleTime: 15 * 60_000, // 15 min — mirrors backend cache
    retry: 1,
  })

  const [input, setInput] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Auto-grow textarea
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 96)}px`
  }, [input])

  function submit(text: string): void {
    const trimmed = text.trim()
    if (!trimmed) return
    sendChatPrompt(trimmed, true)
    setInput('')
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>): void {
    if (e.key !== 'Enter') return
    if (e.nativeEvent.isComposing || e.keyCode === 229) return
    if (e.shiftKey) return
    e.preventDefault()
    submit(input)
  }

  const chips = suggestionChips(data?.market)
  const market = data?.market

  return (
    <section
      style={{
        background: 'var(--bg-1)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)',
        padding: '20px 22px',
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
      }}
      data-testid="today-summary-card"
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              width: 24,
              height: 24,
              borderRadius: 6,
              background: 'var(--accent-dim)',
              color: 'var(--accent)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <IconSparkle size={14} />
          </span>
          <span
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-ui)',
            }}
          >
            今日要点
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {data && (
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--text-muted)',
              }}
            >
              {data.model.split(':').pop()} · {relativeTimestamp(data.generated_at)}
            </span>
          )}
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            title="重新生成"
            aria-label="重新生成今日摘要"
            style={{
              background: 'transparent',
              border: 'none',
              padding: 4,
              cursor: isFetching ? 'wait' : 'pointer',
              color: 'var(--text-muted)',
              display: 'flex',
              alignItems: 'center',
              opacity: isFetching ? 0.4 : 1,
              transition: 'color 0.15s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--accent)')}
            onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
            type="button"
          >
            <IconRefresh size={13} />
          </button>
        </div>
      </div>

      {/* Narrative */}
      {isLoading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              style={{
                height: 14,
                background: 'var(--bg-3)',
                borderRadius: 4,
                width: i === 2 ? '60%' : '100%',
                animation: 'skeleton-pulse 1.5s ease infinite',
              }}
            />
          ))}
        </div>
      )}

      {isError && (
        <div
          style={{
            padding: '10px 12px',
            background: 'var(--bg-2)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--r-sm)',
            fontSize: 12,
            color: 'var(--text-muted)',
          }}
        >
          AI 摘要暂时不可用 — 后端服务是否已启动？
        </div>
      )}

      {data && (
        <p
          style={{
            margin: 0,
            fontSize: 14,
            lineHeight: 1.65,
            color: 'var(--text-primary)',
            fontFamily: 'var(--font-ui)',
            letterSpacing: '0.005em',
          }}
        >
          {data.summary}
        </p>
      )}

      {/* Number badges (real data alongside narrative) */}
      {market && (market.indices.length > 0 || market.watchlist_prices.length > 0) && (
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center' }}>
          {market.indices.slice(0, 3).map((idx) => (
            <span
              key={idx.symbol}
              style={{
                fontSize: 11,
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-muted)',
                whiteSpace: 'nowrap',
              }}
            >
              {idx.name}{' '}
              <span
                style={{
                  color: idx.change_pct >= 0 ? 'var(--positive)' : 'var(--negative)',
                  fontWeight: 600,
                }}
              >
                {fmtPct(idx.change_pct)}
              </span>
            </span>
          ))}
          {market.watchlist_avg_change_pct != null && (
            <span
              style={{
                fontSize: 11,
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-muted)',
                whiteSpace: 'nowrap',
              }}
            >
              自选股均值{' '}
              <span
                style={{
                  color:
                    market.watchlist_avg_change_pct >= 0
                      ? 'var(--positive)'
                      : 'var(--negative)',
                  fontWeight: 600,
                }}
              >
                {fmtPct(market.watchlist_avg_change_pct)}
              </span>
            </span>
          )}
        </div>
      )}

      {/* Input — hands prompt to RightChatPanel */}
      <div
        style={{
          marginTop: 4,
          display: 'flex',
          alignItems: 'flex-end',
          gap: 8,
          padding: '10px 12px',
          background: 'var(--bg-0)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--r-md)',
          transition: 'border-color 0.15s',
        }}
        onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--accent)')}
        onBlur={(e) => (e.currentTarget.style.borderColor = 'var(--border)')}
      >
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="问 FinAgent 任何事... ↵ 发送"
          rows={1}
          style={{
            flex: 1,
            border: 'none',
            outline: 'none',
            background: 'transparent',
            resize: 'none',
            fontSize: 13,
            lineHeight: 1.5,
            fontFamily: 'var(--font-ui)',
            color: 'var(--text-primary)',
            minHeight: 22,
            maxHeight: 96,
          }}
          aria-label="向 FinAgent 提问"
        />
        <button
          onClick={() => submit(input)}
          disabled={input.trim().length === 0}
          style={{
            background: 'var(--accent)',
            color: 'white',
            border: 'none',
            borderRadius: 4,
            padding: '4px 12px',
            fontSize: 12,
            fontWeight: 600,
            cursor: input.trim().length === 0 ? 'not-allowed' : 'pointer',
            opacity: input.trim().length === 0 ? 0.4 : 1,
            fontFamily: 'var(--font-ui)',
            transition: 'opacity 0.15s',
          }}
          type="button"
          title="发送 (↵)"
        >
          发送 ↵
        </button>
      </div>

      {/* Suggestion chips (dynamic from market snapshot) */}
      {chips.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {chips.map((c) => (
            <button
              key={c}
              onClick={() => submit(c)}
              style={{
                background: 'var(--bg-2)',
                border: '1px solid var(--border)',
                borderRadius: 999,
                padding: '4px 11px',
                fontSize: 11,
                fontFamily: 'var(--font-ui)',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                transition: 'all 0.15s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--accent)'
                e.currentTarget.style.color = 'var(--accent)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--border)'
                e.currentTarget.style.color = 'var(--text-secondary)'
              }}
              type="button"
            >
              {c}
            </button>
          ))}
        </div>
      )}
    </section>
  )
}
