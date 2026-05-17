/**
 * DashboardPage — terminal-style landing page for FinAgent.
 *
 * Sections (top to bottom):
 *   1. Market Ticker Bar  — 6-column grid, live from GET /api/market/indices
 *   2. Sector ETF Strip   — horizontal, sorted by performance, live from GET /api/market/sectors
 *   3. Two-column grid:
 *      Left:  Quick Actions (2x2 cards)
 *      Right: Earnings Calendar (live from GET /api/market/earnings-calendar)
 *   4. Signals & Alerts   — catalyst events for top-3 watchlist tickers
 *   5. Recent Analyses    — live from GET /api/artifacts?limit=5
 *
 * Design: navy premium (#0B1121 bg), blue accent (#3B82F6), JetBrains Mono
 * for numbers, Inter for text, graduated radius, subtle shadows.
 */

import { useMemo } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useStocksStore } from '../stores/stocksStore'
import { BASE_URL } from '../api/client'
import { useTickerPrice } from '../hooks/useTickerData'
import { TodaySummaryCard } from '../components/dashboard/TodaySummaryCard'
import { LearningCarousel } from '../components/dashboard/LearningCarousel'
import { ValuationOutliersCard } from '../components/dashboard/ValuationOutliersCard'
import { DiscoverChip } from '../components/dashboard/DiscoverChip'
import { Sparkline } from '../components/Sparkline'

// ── Types ──────────────────────────────────────────────────────────────────────

interface MarketIndex {
  symbol: string
  name: string
  price: number
  change: number
  change_pct: number
}

interface SectorETF {
  symbol: string
  name: string
  price: number
  change: number
  change_pct: number
}

interface EarningsEvent {
  date: string
  ticker: string
  company_name: string
  time: string
  eps_estimate: number | null
}

interface ArtifactSummary {
  id: string
  ticker: string | null
  type: string
  created_at: string
  headline: string
  source: string
  archived: boolean
}

interface CatalystEvent {
  title: string
  date: string
  impact: string
  importance: number
  category?: string
}

// ── Fetch helpers ──────────────────────────────────────────────────────────────

async function fetchIndices(): Promise<MarketIndex[]> {
  const r = await fetch(`${BASE_URL}/api/market/indices`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<MarketIndex[]>
}

async function fetchSectors(): Promise<SectorETF[]> {
  const r = await fetch(`${BASE_URL}/api/market/sectors`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<SectorETF[]>
}

async function fetchEarnings(): Promise<EarningsEvent[]> {
  const r = await fetch(`${BASE_URL}/api/market/earnings-calendar`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<EarningsEvent[]>
}

async function fetchArtifacts(): Promise<ArtifactSummary[]> {
  const r = await fetch(`${BASE_URL}/api/artifacts?limit=5`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<ArtifactSummary[]>
}

async function fetchCatalysts(ticker: string): Promise<CatalystEvent[]> {
  const r = await fetch(`${BASE_URL}/api/data/${ticker}/catalysts`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<CatalystEvent[]>
}

// ── Utility helpers ────────────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

function fmtPct(v: number): string {
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

function fmtPrice(v: number): string {
  if (v >= 1000) return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return v.toFixed(2)
}

function artifactTypeLabel(type: string): string {
  const map: Record<string, string> = {
    dcf: 'DCF', lbo: 'LBO', comps: 'Comps',
    ic_memo: 'IC Memo', earnings: 'Earnings', research: 'Research',
  }
  return map[type.toLowerCase()] ?? type.toUpperCase()
}

function dayLabel(dateStr: string): string {
  const d = new Date(dateStr)
  const today = new Date()
  const diff = Math.round((d.getTime() - today.getTime()) / 86_400_000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tmrw'
  return d.toLocaleDateString('en-US', { weekday: 'short' })
}

// ── Skeleton loader ────────────────────────────────────────────────────────────

function Skeleton({ width, height }: { width: string | number; height: string | number }) {
  return (
    <div
      style={{
        width,
        height,
        borderRadius: 'var(--r-sm)',
        background: 'var(--bg-3)',
        animation: 'skeleton-pulse 1.5s ease infinite',
        flexShrink: 0,
      }}
    />
  )
}

// ── Section header ─────────────────────────────────────────────────────────────

function SectionHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 12,
      }}
    >
      <span
        style={{
          fontSize: 11,
          fontFamily: 'var(--font-mono)',
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          color: 'var(--text-muted)',
        }}
      >
        {title}
      </span>
      {action}
    </div>
  )
}

// ── 1. Market Ticker Bar ─ single thin line, max info density ─────────────────

function MarketTickerBar() {
  const { data, isLoading, isError } = useQuery<MarketIndex[]>({
    queryKey: ['market-indices'],
    queryFn: fetchIndices,
    staleTime: 60_000,
    retry: 1,
  })

  if (isError) return null  // dashboard's TodaySummaryCard already surfaces this
  if (isLoading || !data) {
    return <Skeleton width="100%" height={32} />
  }

  const indices = data.slice(0, 6)

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 22,
        padding: '8px 14px',
        background: 'var(--bg-1)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-sm)',
        overflowX: 'auto',
        scrollbarWidth: 'none',
      }}
      className="hide-scrollbar"
      title="主要市场指数"
    >
      {indices.map((idx) => {
        const pos = idx.change_pct >= 0
        return (
          <div
            key={idx.symbol}
            style={{
              display: 'flex',
              alignItems: 'baseline',
              gap: 6,
              flexShrink: 0,
              whiteSpace: 'nowrap',
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                fontWeight: 600,
                color: 'var(--text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
              }}
            >
              {idx.name}
            </span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                fontWeight: 700,
                color: 'var(--text-primary)',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {fmtPrice(idx.price)}
            </span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                fontWeight: 600,
                color: pos ? 'var(--positive)' : 'var(--negative)',
              }}
            >
              {fmtPct(idx.change_pct)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── 2. Sector ETF Strip ────────────────────────────────────────────────────────

function SectorStrip() {
  const { data, isLoading, isError } = useQuery<SectorETF[]>({
    queryKey: ['market-sectors'],
    queryFn: fetchSectors,
    staleTime: 60_000,
    retry: 1,
  })

  if (isError) return null

  if (isLoading || !data) {
    return (
      <div style={{ display: 'flex', gap: 6, overflowX: 'auto' }}>
        {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((i) => (
          <Skeleton key={i} width={64} height={40} />
        ))}
      </div>
    )
  }

  const sorted = [...data].sort((a, b) => b.change_pct - a.change_pct)
  const max = Math.max(...sorted.map((s) => Math.abs(s.change_pct)), 1)

  return (
    <div style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 2 }}>
      {sorted.map((sector) => {
        const isPositive = sector.change_pct >= 0
        const intensity = Math.min(Math.abs(sector.change_pct) / max, 1)
        const bg = isPositive
          ? `rgba(16,185,129,${0.06 + intensity * 0.18})`
          : `rgba(239,68,68,${0.06 + intensity * 0.18})`

        return (
          <div
            key={sector.symbol}
            title={sector.name}
            style={{
              background: bg,
              border: `1px solid ${isPositive ? 'rgba(16,185,129,0.20)' : 'rgba(239,68,68,0.20)'}`,
              borderRadius: 'var(--r-md)',
              padding: '8px 12px',
              flexShrink: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 3,
              minWidth: 60,
              cursor: 'default',
              transition: 'transform 0.15s',
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9,
                fontWeight: 700,
                color: isPositive ? 'var(--positive)' : 'var(--negative)',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}
            >
              {sector.symbol}
            </span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                fontWeight: 700,
                color: isPositive ? 'var(--positive)' : 'var(--negative)',
              }}
            >
              {fmtPct(sector.change_pct)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── 3b. Earnings Calendar ──────────────────────────────────────────────────────

function EarningsCalendar() {
  const { data, isLoading, isError } = useQuery<EarningsEvent[]>({
    queryKey: ['earnings-calendar'],
    queryFn: fetchEarnings,
    staleTime: 300_000,
    retry: 1,
  })
  const navigate = useNavigate()

  return (
    <div>
      <SectionHeader
        title="本周财报"
        action={
          <span
            style={{
              fontSize: 9,
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
            }}
          >
            7 days
          </span>
        }
      />

      {isLoading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} width="100%" height={38} />
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
            fontSize: 11,
            color: 'var(--text-muted)',
          }}
        >
          财报数据暂不可用
        </div>
      )}

      {data && data.length === 0 && (
        <div
          style={{
            padding: '10px 12px',
            background: 'var(--bg-2)',
            border: '1px dashed var(--border)',
            borderRadius: 'var(--r-sm)',
            fontSize: 11,
            color: 'var(--text-muted)',
            lineHeight: 1.5,
          }}
        >
          请在{' '}
          <button
            onClick={() => navigate('/settings')}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--accent)',
              cursor: 'pointer',
              fontSize: 11,
              padding: 0,
              fontFamily: 'inherit',
            }}
          >
            设置
          </button>{' '}
          中配置 FMP 密钥
        </div>
      )}

      {data && data.length > 0 && (() => {
        // Dashboard widget = glance. Cap to next 10 events so it doesn't
        // dwarf the rest of the page; full list lives behind "查看全部".
        const visible = data.slice(0, 10)
        return (
        <div
          style={{
            background: 'var(--bg-1)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--r-md)',
            overflow: 'hidden',
          }}
        >
          {visible.map((ev, idx) => (
            <div
              key={`${ev.ticker}-${ev.date}-${idx}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '9px 14px',
                borderBottom: idx < visible.length - 1 ? '1px solid var(--border)' : 'none',
              }}
            >
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 9,
                  color: 'var(--text-muted)',
                  width: 30,
                  flexShrink: 0,
                  textTransform: 'uppercase',
                }}
              >
                {dayLabel(ev.date)}
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  fontWeight: 700,
                  color: 'var(--accent)',
                  minWidth: 70,
                  flexShrink: 0,
                  whiteSpace: 'nowrap',
                }}
              >
                {ev.ticker}
              </span>
              {ev.company_name && ev.company_name !== ev.ticker && (
                <span
                  style={{
                    fontSize: 10,
                    color: 'var(--text-secondary)',
                    flex: 1,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {ev.company_name}
                </span>
              )}
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 9,
                  fontWeight: 600,
                  color: ev.time === 'BMO' ? 'var(--positive)' : 'var(--warning)',
                  background:
                    ev.time === 'BMO' ? 'var(--positive-bg)' : 'rgba(245, 158, 11, 0.10)',
                  padding: '2px 5px',
                  borderRadius: 3,
                  flexShrink: 0,
                }}
              >
                {ev.time || 'TBD'}
              </span>
            </div>
          ))}
        </div>
        )
      })()}
    </div>
  )
}

// ── 4. Signals & Alerts ────────────────────────────────────────────────────────

interface CatalystWithTicker extends CatalystEvent {
  ticker: string
}

function impactColor(impact: string | undefined): string {
  const i = (impact ?? '').toLowerCase()
  if (i === 'positive') return 'var(--positive)'
  if (i === 'negative') return 'var(--negative)'
  return 'var(--warning)'
}

function SignalRow({ row, onClick }: { row: CatalystWithTicker; onClick: () => void }): React.ReactElement {
  const dot = impactColor(row.impact)
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '9px 14px',
        background: 'var(--bg-1)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-md)',
        transition: 'all 0.15s',
        cursor: 'pointer',
        textAlign: 'left',
        width: '100%',
      }}
      onMouseEnter={(e) => ((e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--accent)')}
      onMouseLeave={(e) => ((e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--border)')}
      type="button"
      aria-label={`查看 ${row.ticker} 详情`}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: dot, flexShrink: 0 }} />
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          fontWeight: 700,
          color: 'var(--accent)',
          flexShrink: 0,
          width: 44,
        }}
      >
        {row.ticker}
      </span>
      <span
        style={{
          fontSize: 11,
          color: 'var(--text-secondary)',
          flex: 1,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {row.title}
      </span>
      {row.category && (
        <span
          style={{
            fontSize: 9,
            color: 'var(--text-muted)',
            background: 'var(--bg-2)',
            padding: '1px 5px',
            borderRadius: 2,
            flexShrink: 0,
            fontFamily: 'var(--font-mono)',
            textTransform: 'lowercase',
          }}
        >
          {row.category}
        </span>
      )}
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)', flexShrink: 0 }}>
        {relativeTime(row.date)}
      </span>
    </button>
  )
}

function useAggregatedCatalysts(tickers: string[]): { rows: CatalystWithTicker[]; isLoading: boolean } {
  // Run one query per ticker; aggregate + sort once all settled.
  const queries = tickers.map((ticker) => ({
    ticker,
    result: useQuery<CatalystEvent[]>({
      queryKey: ['catalysts', ticker],
      queryFn: () => fetchCatalysts(ticker),
      staleTime: 120_000,
      retry: 1,
    }),
  }))

  const isLoading = queries.some((q) => q.result.isLoading)

  const rows: CatalystWithTicker[] = []
  for (const { ticker, result } of queries) {
    const data = result.data ?? []
    // Take top 2 per ticker (sorted by importance desc within each)
    const top2 = [...data]
      .sort((a, b) => (b.importance ?? 0) - (a.importance ?? 0))
      .slice(0, 2)
      .map((c) => ({ ...c, ticker }))
    rows.push(...top2)
  }

  // Global sort by importance so the loudest events bubble to top across tickers.
  rows.sort((a, b) => (b.importance ?? 0) - (a.importance ?? 0))
  return { rows, isLoading }
}

const MAX_VISIBLE_SIGNALS = 5
const MAX_WATCHED_FOR_SIGNALS = 5  // bound concurrent queries

function SignalsSection() {
  const navigate = useNavigate()
  const watchlist = useStocksStore((s) => s.watchlist)
  const tickers = Array.from(watchlist).slice(0, MAX_WATCHED_FOR_SIGNALS)
  const { rows, isLoading } = useAggregatedCatalysts(tickers)
  const visible = rows.slice(0, MAX_VISIBLE_SIGNALS)

  return (
    <div>
      <SectionHeader
        title="信号与预警"
        action={
          tickers.length > 0 ? (
            <Link
              to="/stocks"
              style={{
                fontSize: 10,
                color: 'var(--accent)',
                textDecoration: 'none',
                fontFamily: 'var(--font-mono)',
              }}
            >
              管理自选股
            </Link>
          ) : null
        }
      />

      {tickers.length === 0 ? (
        <div
          style={{
            padding: '10px 12px',
            background: 'var(--bg-2)',
            border: '1px dashed var(--border)',
            borderRadius: 'var(--r-sm)',
            fontSize: 11,
            color: 'var(--text-muted)',
          }}
        >
          添加自选股以查看信号
        </div>
      ) : isLoading && visible.length === 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} width="100%" height={34} />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <div
          style={{
            padding: '10px 12px',
            background: 'var(--bg-2)',
            border: '1px dashed var(--border)',
            borderRadius: 'var(--r-sm)',
            fontSize: 11,
            color: 'var(--text-muted)',
          }}
        >
          自选股近期暂无重要事件
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {visible.map((row, i) => (
            <SignalRow
              key={`${row.ticker}-${row.date}-${i}`}
              row={row}
              onClick={() => navigate(`/stocks/${row.ticker}`)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── 5. Recent Analyses ─────────────────────────────────────────────────────────

function RecentAnalysesSection() {
  const navigate = useNavigate()
  const { data, isLoading, isError } = useQuery<ArtifactSummary[]>({
    queryKey: ['recent-artifacts'],
    queryFn: fetchArtifacts,
    staleTime: 30_000,
    retry: 1,
  })

  return (
    <div>
      <SectionHeader
        title="最近分析"
        action={
          <Link
            to="/library"
            style={{
              fontSize: 10,
              color: 'var(--accent)',
              textDecoration: 'none',
              fontFamily: 'var(--font-mono)',
            }}
          >
            查看全部
          </Link>
        }
      />

      {isLoading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} width="100%" height={40} />
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
            fontSize: 11,
            color: 'var(--text-muted)',
          }}
        >
          无法加载分析记录 — 后端服务是否已启动？
        </div>
      )}

      {data && data.length === 0 && (
        <div
          style={{
            padding: '10px 12px',
            background: 'var(--bg-2)',
            border: '1px dashed var(--border)',
            borderRadius: 'var(--r-sm)',
            fontSize: 11,
            color: 'var(--text-muted)',
          }}
        >
          暂无分析记录 — 去个股分析页面跑一次
        </div>
      )}

      {data && data.length > 0 && (
        <div
          style={{
            background: 'var(--bg-1)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--r-md)',
            overflow: 'hidden',
          }}
        >
          {data.map((artifact, idx) => (
            <RecentAnalysisRow
              key={artifact.id}
              artifact={artifact}
              isLast={idx === data.length - 1}
              onClick={() =>
                navigate(artifact.ticker ? `/library/${artifact.ticker}` : '/library')
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}

function RecentAnalysisRow({
  artifact,
  isLast,
  onClick,
}: {
  artifact: ArtifactSummary
  isLast: boolean
  onClick: () => void
}): React.ReactElement {
  // 7-day sparkline — only meaningful for ticker-bound artifacts.
  // Shares react-query cache with Sidebar/ValuationOutliers; no extra request.
  const { data: priceData } = useTickerPrice(artifact.ticker ?? '')
  const sparkValues = useMemo(() => {
    const history = priceData?.history
    if (!history || history.length === 0) return []
    return history.slice(-7).map((p) => p.close)
  }, [priceData?.history])

  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        width: '100%',
        padding: '10px 14px',
        background: 'transparent',
        border: 'none',
        borderBottom: isLast ? 'none' : '1px solid var(--border)',
        cursor: 'pointer',
        textAlign: 'left',
        transition: 'background 0.15s',
      }}
      onMouseEnter={(e) => {
        ;(e.currentTarget as HTMLButtonElement).style.background = 'var(--bg-3)'
      }}
      onMouseLeave={(e) => {
        ;(e.currentTarget as HTMLButtonElement).style.background = 'transparent'
      }}
    >
      {/* Type badge */}
      <span
        style={{
          fontSize: 9,
          fontWeight: 700,
          fontFamily: 'var(--font-mono)',
          color: 'var(--accent)',
          background: 'var(--accent-dim)',
          padding: '2px 6px',
          borderRadius: 3,
          flexShrink: 0,
          minWidth: 36,
          textAlign: 'center',
        }}
      >
        {artifactTypeLabel(artifact.type)}
      </span>

      {/* Ticker + headline */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {artifact.ticker && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-primary)',
              marginRight: 6,
            }}
          >
            {artifact.ticker}
          </span>
        )}
        <span
          style={{
            fontSize: 11,
            color: 'var(--text-secondary)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            display: 'inline',
          }}
        >
          {artifact.headline}
        </span>
      </div>

      {/* 7-day sparkline (only when ticker-bound and history present) */}
      {artifact.ticker && sparkValues.length >= 2 && (
        <Sparkline values={sparkValues} width={44} height={12} />
      )}

      {/* Relative time */}
      <span
        style={{
          fontSize: 9,
          color: 'var(--text-muted)',
          flexShrink: 0,
          fontFamily: 'var(--font-mono)',
        }}
      >
        {relativeTime(artifact.created_at)}
      </span>
    </button>
  )
}

// ── DashboardPage ──────────────────────────────────────────────────────────────

export function DashboardPage() {
  return (
    <div
      style={{
        height: '100%',
        overflowY: 'auto',
        background: 'var(--bg-0)',
      }}
    >
      <div
        style={{
          maxWidth: 1040,
          margin: '0 auto',
          padding: '28px 32px 48px',
          display: 'flex',
          flexDirection: 'column',
          gap: 22,
        }}
      >
        {/* ── 1. Market Ticker Bar ─────────────────────────────────────────── */}
        <MarketTickerBar />

        {/* ── 2. Sector ETF Strip ──────────────────────────────────────────── */}
        <SectorStrip />

        {/* ── 3. AI Today Summary (hero) ───────────────────────────────────── */}
        <TodaySummaryCard />

        {/* ── 4. Two-column: Watchlist Events | Earnings Calendar ──────────── */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 16,
            alignItems: 'start',
          }}
        >
          <SignalsSection />
          <EarningsCalendar />
        </div>

        {/* ── 5. Valuation outliers (FinAgent 独有差异点) ──────────────────── */}
        <ValuationOutliersCard />

        {/* ── 6. Recent Analyses ───────────────────────────────────────────── */}
        <RecentAnalysesSection />

        {/* ── 7. Learning carousel + Discover chip ─────────────────────────── */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
            <DiscoverChip />
          </div>
          <LearningCarousel />
        </div>
      </div>
    </div>
  )
}
