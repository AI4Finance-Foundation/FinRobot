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
 * Design: dark terminal (#0C0C0C bg), gold accent (#E2B93D), JetBrains Mono
 * for numbers, Inter for text, 6px radius, no shadows — zero placeholders.
 */

import { useNavigate, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useStocksStore } from '../stores/stocksStore'
import { useUiStore } from '../stores/uiStore'
import { BASE_URL } from '../api/client'
import {
  IconTrendingUp,
  IconFileText,
  IconZap,
  IconSparkle,
  IconClock,
  IconActivity,
} from '../lib/icons'

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
        marginBottom: 10,
      }}
    >
      <span
        style={{
          fontSize: 9,
          fontFamily: 'var(--font-mono)',
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.10em',
          color: 'var(--text-muted)',
        }}
      >
        {title}
      </span>
      {action}
    </div>
  )
}

// ── 1. Market Ticker Bar ───────────────────────────────────────────────────────

function MarketTickerBar() {
  const { data, isLoading, isError } = useQuery<MarketIndex[]>({
    queryKey: ['market-indices'],
    queryFn: fetchIndices,
    staleTime: 60_000,
    retry: 1,
  })

  if (isError) {
    return (
      <div
        style={{
          padding: '10px 16px',
          background: 'var(--bg-2)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--r-sm)',
          fontSize: 11,
          color: 'var(--text-muted)',
          textAlign: 'center',
          fontFamily: 'var(--font-mono)',
        }}
      >
        Market data unavailable
      </div>
    )
  }

  if (isLoading || !data) {
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8 }}>
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Skeleton key={i} width="100%" height={60} />
        ))}
      </div>
    )
  }

  const indices = data.slice(0, 6)

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8 }}>
      {indices.map((idx) => {
        const isPositive = idx.change_pct >= 0
        return (
          <div
            key={idx.symbol}
            style={{
              background: 'var(--bg-2)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--r-sm)',
              padding: '10px 12px',
              minWidth: 0,
            }}
          >
            <div
              style={{
                fontSize: 9,
                fontFamily: 'var(--font-mono)',
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'var(--text-muted)',
                marginBottom: 4,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {idx.name}
            </div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 15,
                fontWeight: 700,
                color: 'var(--text-primary)',
                letterSpacing: '-0.02em',
                marginBottom: 2,
              }}
            >
              {fmtPrice(idx.price)}
            </div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                fontWeight: 600,
                color: isPositive ? 'var(--positive)' : 'var(--negative)',
              }}
            >
              {fmtPct(idx.change_pct)}
            </div>
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
          ? `rgba(38,166,154,${0.06 + intensity * 0.18})`
          : `rgba(239,83,80,${0.06 + intensity * 0.18})`

        return (
          <div
            key={sector.symbol}
            title={sector.name}
            style={{
              background: bg,
              border: `1px solid ${isPositive ? 'rgba(38,166,154,0.25)' : 'rgba(239,83,80,0.25)'}`,
              borderRadius: 'var(--r-sm)',
              padding: '6px 10px',
              flexShrink: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 2,
              minWidth: 56,
              cursor: 'default',
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

// ── 3a. Quick Actions ──────────────────────────────────────────────────────────

interface QuickActionCardProps {
  icon: React.ReactElement
  title: string
  description: string
  onClick: () => void
}

function QuickActionCard({ icon, title, description, onClick }: QuickActionCardProps) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        gap: 8,
        padding: '12px 14px',
        background: 'var(--bg-2)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-sm)',
        cursor: 'pointer',
        textAlign: 'left',
        transition: 'border-color 0.12s',
        minWidth: 0,
      }}
      onMouseEnter={(e) => {
        ;(e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--gold)'
      }}
      onMouseLeave={(e) => {
        ;(e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--border)'
      }}
    >
      <span
        style={{
          width: 28,
          height: 28,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: 'var(--r-sm)',
          background: 'var(--gold-dim)',
          color: 'var(--gold)',
          flexShrink: 0,
        }}
      >
        {icon}
      </span>
      <div>
        <div
          style={{
            fontSize: 13,
            fontWeight: 700,
            color: 'var(--text-primary)',
            marginBottom: 3,
            fontFamily: 'var(--font-ui)',
          }}
        >
          {title}
        </div>
        <div
          style={{
            fontSize: 10,
            color: 'var(--text-muted)',
            lineHeight: 1.4,
            fontFamily: 'var(--font-ui)',
          }}
        >
          {description}
        </div>
      </div>
    </button>
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
        title="EARNINGS THIS WEEK"
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
          Earnings data unavailable
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
          Configure FMP key in{' '}
          <button
            onClick={() => navigate('/settings')}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--gold)',
              cursor: 'pointer',
              fontSize: 11,
              padding: 0,
              fontFamily: 'inherit',
            }}
          >
            Settings
          </button>{' '}
          for earnings data
        </div>
      )}

      {data && data.length > 0 && (
        <div
          style={{
            background: 'var(--bg-2)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--r-sm)',
            overflow: 'hidden',
          }}
        >
          {data.map((ev, idx) => (
            <div
              key={`${ev.ticker}-${ev.date}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '7px 10px',
                borderBottom: idx < data.length - 1 ? '1px solid var(--border)' : 'none',
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
                  color: 'var(--gold)',
                  width: 40,
                  flexShrink: 0,
                }}
              >
                {ev.ticker}
              </span>
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
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 9,
                  fontWeight: 600,
                  color: ev.time === 'BMO' ? 'var(--positive)' : 'var(--warning)',
                  background:
                    ev.time === 'BMO' ? 'var(--positive-bg)' : 'rgba(226,185,61,0.10)',
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
      )}
    </div>
  )
}

// ── 4. Signals & Alerts ────────────────────────────────────────────────────────

function SignalRow({ ticker }: { ticker: string }) {
  const { data, isLoading } = useQuery<CatalystEvent[]>({
    queryKey: ['catalysts', ticker],
    queryFn: () => fetchCatalysts(ticker),
    staleTime: 120_000,
    retry: 1,
  })

  if (isLoading) {
    return <Skeleton width="100%" height={34} />
  }

  if (!data || data.length === 0) return null

  const top = data[0]
  const impact = (top.impact ?? '').toLowerCase()
  const dotColor =
    impact === 'positive' ? 'var(--positive)' :
    impact === 'negative' ? 'var(--negative)' :
    'var(--warning)'

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '7px 10px',
        background: 'var(--bg-2)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-sm)',
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: dotColor,
          flexShrink: 0,
        }}
      />
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          fontWeight: 700,
          color: 'var(--gold)',
          flexShrink: 0,
          width: 44,
        }}
      >
        {ticker}
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
        {top.title}
      </span>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9,
          color: 'var(--text-muted)',
          flexShrink: 0,
        }}
      >
        {relativeTime(top.date)}
      </span>
    </div>
  )
}

function SignalsSection() {
  const watchlist = useStocksStore((s) => s.watchlist)
  const tickers = Array.from(watchlist).slice(0, 3)

  return (
    <div>
      <SectionHeader
        title="SIGNALS & ALERTS"
        action={
          tickers.length > 0 ? (
            <Link
              to="/stocks"
              style={{
                fontSize: 10,
                color: 'var(--gold)',
                textDecoration: 'none',
                fontFamily: 'var(--font-mono)',
              }}
            >
              Manage watchlist
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
          Add tickers to your watchlist to see signals
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {tickers.map((ticker) => (
            <SignalRow key={ticker} ticker={ticker} />
          ))}
          {/* Channel tags */}
          <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9,
                color: 'var(--positive)',
                background: 'var(--positive-bg)',
                padding: '2px 7px',
                borderRadius: 3,
                border: '1px solid rgba(38,166,154,0.2)',
              }}
            >
              Desktop ✓
            </span>
          </div>
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
        title="RECENT ANALYSES"
        action={
          <Link
            to="/library"
            style={{
              fontSize: 10,
              color: 'var(--gold)',
              textDecoration: 'none',
              fontFamily: 'var(--font-mono)',
            }}
          >
            View all
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
          Could not load analyses — is the backend running?
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
          No analyses yet — run a DCF from the Stocks page
        </div>
      )}

      {data && data.length > 0 && (
        <div
          style={{
            background: 'var(--bg-2)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--r-sm)',
            overflow: 'hidden',
          }}
        >
          {data.map((artifact, idx) => (
            <button
              key={artifact.id}
              onClick={() =>
                navigate(artifact.ticker ? `/library/${artifact.ticker}` : '/library')
              }
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                width: '100%',
                padding: '8px 10px',
                background: 'transparent',
                border: 'none',
                borderBottom: idx < data.length - 1 ? '1px solid var(--border)' : 'none',
                cursor: 'pointer',
                textAlign: 'left',
                transition: 'background 0.1s',
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
                  color: 'var(--gold)',
                  background: 'var(--gold-dim)',
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
          ))}
        </div>
      )}
    </div>
  )
}

// ── DashboardPage ──────────────────────────────────────────────────────────────

export function DashboardPage() {
  const navigate = useNavigate()
  const setAiPanelOpen = useUiStore((s) => s.setAiPanelOpen)

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
          maxWidth: 960,
          margin: '0 auto',
          padding: '20px 20px 32px',
          display: 'flex',
          flexDirection: 'column',
          gap: 20,
        }}
      >
        {/* ── 1. Market Ticker Bar ─────────────────────────────────────────── */}
        <MarketTickerBar />

        {/* ── 2. Sector ETF Strip ──────────────────────────────────────────── */}
        <SectorStrip />

        {/* ── 3. Two-column: Quick Actions | Earnings Calendar ─────────────── */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 16,
            alignItems: 'start',
          }}
        >
          {/* Quick Actions */}
          <div>
            <SectionHeader title="QUICK ACTIONS" />
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: 8,
              }}
            >
              <QuickActionCard
                icon={<IconTrendingUp size={14} />}
                title="Full Report"
                description="DCF, LBO & Comps on any ticker"
                onClick={() => navigate('/stocks')}
              />
              <QuickActionCard
                icon={<IconActivity size={14} />}
                title="Compare"
                description="Side-by-side peer comparison"
                onClick={() => navigate('/stocks')}
              />
              <QuickActionCard
                icon={<IconZap size={14} />}
                title="What-If"
                description="Scenario analysis & sensitivity"
                onClick={() => navigate('/playground')}
              />
              <QuickActionCard
                icon={<IconFileText size={14} />}
                title="Backtest"
                description="Historical signal backtesting"
                onClick={() => navigate('/journal')}
              />
            </div>
          </div>

          {/* Earnings Calendar */}
          <EarningsCalendar />
        </div>

        {/* ── 4. Signals & Alerts ──────────────────────────────────────────── */}
        <SignalsSection />

        {/* ── 5. Recent Analyses ───────────────────────────────────────────── */}
        <RecentAnalysesSection />
      </div>
    </div>
  )
}
