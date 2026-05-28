// Left column of the workspace dashboard. Surfaces live market data
// that exists independently of any AI research run — quote snapshot,
// price trend, financials, catalyst calendar, earnings calls, news.
//
// Lives at /stocks/:ticker. Everything here keeps refreshing from
// yfinance / SEC / FMP regardless of whether the user has ever run a
// research pipeline on this ticker.

import { useState } from 'react'
import {
  useTickerPrice,
  useTickerFinancials,
  useTickerCatalysts,
  type FinancialsData,
} from '../../hooks/useTickerData'
import { tSync } from '../../i18n'

interface MarketDataZoneProps {
  ticker: string
}

export function MarketDataZone({ ticker }: MarketDataZoneProps): React.ReactElement {
  const { data: price } = useTickerPrice(ticker)
  const { data: fin } = useTickerFinancials(ticker)
  const { data: catalysts } = useTickerCatalysts(ticker)

  return (
    <section data-testid="market-data-zone">
      <ZoneHeader />
      <p style={zoneDesc}>来源 yfinance / SEC EDGAR / FMP · 实时拉，跟 AI 研报互不依赖。</p>

      {/* 行情快照 */}
      <MktCard title="📊 行情快照" liveTag={providerTag(fin?.data_source)}>
        <Kv4
          cells={[
            { label: '市值', value: fmtMc(fin?.market?.market_cap) },
            { label: 'P/E (TTM)', value: fmt(fin?.market?.pe_ratio, 1) },
            {
              label: 'EV/EBITDA',
              value: fmt(fin?.valuation?.ev_ebitda, 1),
              sub:
                typeof fin?.valuation?.ev_ebitda_reported === 'number'
                  ? `街口径 ${fin.valuation.ev_ebitda_reported.toFixed(1)}`
                  : undefined,
              subTitle:
                '主显=营业口径 EV/EBITDA（EBITDA=EBIT+D&A）。EV 已扣现金，故不计利息收入。' +
                '街口径=净利+税+利息+D&A，含利息收入，多数零售源用这个。',
            },
            {
              label: 'Beta (5Y)',
              value: fmt(fin?.market?.beta, 2),
            },
            { label: '52W Low', value: fmtPrice(fin?.market?.price_52w_low) },
            { label: '52W High', value: fmtPrice(fin?.market?.price_52w_high) },
          ]}
        />
        <ProvenanceFootnote provenance={fin?.provenance} />
      </MktCard>

      {/* Price chart */}
      <MktCard title="📈 价格趋势" liveTag={providerTag(price?.data_source)}>
        <PriceSparkline points={price?.history ?? null} />
      </MktCard>

      {/* Financial TTM */}
      <MktCard title="💰 财务指标 · TTM" liveTag={providerTag(fin?.data_source)}>
        <Kv4
          cells={[
            { label: '营收 TTM', value: fmtMc(fin?.income?.revenue) },
            {
              label: 'EBITDA',
              value: fmtMc(fin?.income?.ebitda),
              sub:
                typeof fin?.valuation?.ebitda_reported === 'number'
                  ? `街口径 ${fmtMc(fin.valuation.ebitda_reported)}`
                  : undefined,
              subTitle:
                '主显=营业口径 EBITDA（EBIT+D&A）。街口径=净利+税+利息+D&A，含利息收入。',
            },
            {
              label: 'Net Income',
              value: fmtMc(fin?.income?.net_income),
            },
            {
              label: 'Gross Margin',
              value:
                typeof fin?.income?.gross_margin === 'number'
                  ? `${(fin.income.gross_margin * 100).toFixed(1)}%`
                  : '—',
            },
          ]}
        />
        <ProvenanceFootnote provenance={fin?.provenance} showPeriodEnd />
      </MktCard>

      {/* Catalyst calendar */}
      <MktCard title="📅 催化剂日历">
        {catalysts && catalysts.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {catalysts.slice(0, 5).map((c, i) => (
              <div
                key={`${i}-${c.headline ?? 'event'}`}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr auto auto',
                  gap: 10,
                  alignItems: 'center',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11.5,
                  padding: '7px 10px',
                  background: 'var(--bg-card-50)',
                  borderRadius: 6,
                }}
              >
                <span
                  style={{
                    color: 'var(--text-secondary)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {c.headline ?? '(未命名事件)'}
                </span>
                <span
                  style={{
                    color:
                      c.sentiment === 'positive'
                        ? 'var(--success)'
                        : c.sentiment === 'negative'
                          ? 'var(--danger)'
                          : 'var(--text-muted)',
                    fontSize: 10.5,
                  }}
                >
                  {c.category ?? '—'}
                </span>
                <span style={{ color: 'var(--accent-amber)', fontSize: 10.5 }}>
                  {typeof c.impact_score === 'number' ? `★ ${c.impact_score}` : ''}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <Empty>暂无近期事件 · 财报 / 产品发布 / 监管</Empty>
        )}
      </MktCard>
    </section>
  )
}

function ZoneHeader(): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'baseline',
        gap: 12,
        marginBottom: 14,
        paddingBottom: 8,
        borderBottom: '1px solid var(--border-amber-soft)',
      }}
    >
      <span
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 16,
          letterSpacing: '2px',
          color: 'var(--accent-amber)',
          textShadow: '0 0 12px var(--glow-amber-soft)',
        }}
      >
        📊 市场数据
      </span>
      <span
        style={{
          marginLeft: 'auto',
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-muted)',
          letterSpacing: '0.08em',
        }}
      >
        {tSync('marketdata.zoneHeader')}
      </span>
    </div>
  )
}

const zoneDesc: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  color: 'var(--text-muted)',
  marginBottom: 14,
  lineHeight: 1.55,
}

function MktCard({
  title,
  liveTag,
  children,
}: {
  title: string
  liveTag?: string
  children: React.ReactNode
}): React.ReactElement {
  const [hover, setHover] = useState(false)
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        background: 'var(--bg-card)',
        border: hover ? '1px solid var(--border-glow)' : '1px solid var(--border-faint)',
        borderRadius: 'var(--radius-md)',
        padding: '14px 16px',
        marginBottom: 12,
        boxShadow: hover ? '0 8px 32px rgba(59,130,246,0.12)' : 'none',
        transition: 'border-color 0.2s, box-shadow 0.2s',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-muted)',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
          }}
        >
          {title}
        </span>
        {liveTag && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              color: 'var(--accent-cyan)',
              padding: '1px 6px',
              border: '1px solid var(--border-cyan-soft)',
              borderRadius: 3,
              letterSpacing: '0.08em',
            }}
          >
            {liveTag}
          </span>
        )}
      </div>
      {children}
    </div>
  )
}

interface KvCell {
  label: string
  value: string
  /** Secondary caliber line shown muted under the value (e.g. street EV/EBITDA). */
  sub?: string
  /** Hover explanation for the sub line — the caliber definition. */
  subTitle?: string
}

function Kv4({ cells }: { cells: KvCell[] }): React.ReactElement {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(2, 1fr)',
        gap: 1,
        background: 'var(--border-faint)',
        borderRadius: 6,
        overflow: 'hidden',
      }}
    >
      {cells.map((c, i) => (
        <div key={i} style={{ background: 'var(--bg-card)', padding: '10px 12px' }}>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--text-muted)',
              letterSpacing: '0.04em',
              marginBottom: 3,
              textTransform: 'uppercase',
            }}
          >
            {c.label}
          </div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 16,
              color: 'var(--text-primary)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {c.value}
          </div>
          {c.sub && (
            <div
              title={c.subTitle}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9.5,
                color: 'var(--text-muted)',
                letterSpacing: '0.02em',
                marginTop: 2,
                cursor: c.subTitle ? 'help' : 'default',
              }}
            >
              {c.sub}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function PriceSparkline({
  points,
}: {
  points: { date: string; close: number }[] | null
}): React.ReactElement {
  if (!points || points.length < 2) {
    return (
      <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
        加载中…
      </p>
    )
  }
  const closes = points.map((p) => p.close)
  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const range = max - min || 1
  const w = 400
  const h = 70
  const path = closes
    .map((c, i) => {
      const x = (i / (closes.length - 1)) * w
      const y = h - ((c - min) / range) * h
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  // 1-year return must anchor to the close ~365 calendar days before the last
  // bar, not points[0]. Providers can hand back more than a year (FMP's
  // historical window carries a cushion), and using points[0] then measured
  // from ~17 months ago — TSLA read +9.8% instead of the real ~+21%.
  const lastDate = new Date(points[points.length - 1].date)
  const cutoff = new Date(lastDate)
  cutoff.setDate(cutoff.getDate() - 365)
  const baseIdx = Math.max(
    0,
    points.findIndex((p) => new Date(p.date) >= cutoff),
  )
  const first = closes[baseIdx]
  const last = closes[closes.length - 1]
  const pct = ((last - first) / first) * 100
  const spanDays = Math.round((lastDate.getTime() - new Date(points[baseIdx].date).getTime()) / 86_400_000)
  const spanLabel = spanDays >= 350 ? '1Y' : `${spanDays}D`

  return (
    <div>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        style={{ width: '100%', height: 70 }}
      >
        <defs>
          <linearGradient id="sp-grad-mkt" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--accent-cyan)" stopOpacity="0.5" />
            <stop offset="100%" stopColor="var(--accent-cyan)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={path} fill="none" stroke="var(--accent-cyan)" strokeWidth={1.5} />
        <path d={`${path} L${w},${h} L0,${h} Z`} fill="url(#sp-grad-mkt)" />
      </svg>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-muted)',
          marginTop: 4,
        }}
      >
        <span>{spanLabel} 走势</span>
        <span style={{ color: pct >= 0 ? 'var(--success)' : 'var(--danger)' }}>
          {pct >= 0 ? '+' : ''}
          {pct.toFixed(1)}%
        </span>
      </div>
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <p
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--text-muted)',
        lineHeight: 1.6,
      }}
    >
      {children}
    </p>
  )
}

// Honest provenance: show the provider that actually served the payload.
// The chain is FMP → Finnhub → yfinance, so this card is usually "fmp" even
// though it was hardcoded "yfinance" before. Strips the ":provider-cache"
// suffix; returns undefined while loading so no stale tag flashes.
function providerTag(src: string | null | undefined): string | undefined {
  if (!src) return undefined
  return src.split(':')[0]
}

// Degradation flags from the backend normalization layer (ADR-0004). Surfaced
// so a fallback (close-only history, stale TTM, inferred currency) is visible.
const DEGRADED_LABELS: Record<string, string> = {
  close_only: '仅收盘价 · 52周高低用收盘价',
  ttm_lag: 'TTM 落后 · 分母非最新季',
  ccy_inferred: '币种推断 · 非财报直接标注',
}

function ProvenanceFootnote({
  provenance,
  showPeriodEnd,
}: {
  provenance?: FinancialsData['provenance']
  showPeriodEnd?: boolean
}): React.ReactElement | null {
  if (!provenance) return null
  const provider = provenance.provider
  const periodEnd = provenance.as_of
  const degraded = provenance.degraded ?? []
  const parts: string[] = []
  if (provider) parts.push(`来源 ${provider}`)
  if (showPeriodEnd && periodEnd) parts.push(`TTM 截至 ${periodEnd}`)
  if (parts.length === 0 && degraded.length === 0) return null
  return (
    <div
      style={{
        marginTop: 8,
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 6,
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        color: 'var(--text-muted)',
        letterSpacing: '0.04em',
      }}
    >
      {parts.length > 0 && <span>{parts.join(' · ')}</span>}
      {degraded.map((d) => (
        <span
          key={d}
          title={DEGRADED_LABELS[d] ?? d}
          style={{
            color: 'var(--accent-amber)',
            border: '1px solid var(--border-amber-soft)',
            borderRadius: 3,
            padding: '1px 5px',
            fontSize: 9,
          }}
        >
          ⚠ {DEGRADED_LABELS[d] ?? d}
        </span>
      ))}
    </div>
  )
}

function fmt(v: number | null | undefined, digits = 2): string {
  return typeof v === 'number' ? v.toFixed(digits) : '—'
}
function fmtPrice(v: number | null | undefined): string {
  return typeof v === 'number' ? `$${v.toFixed(2)}` : '—'
}
function fmtMc(v: number | null | undefined): string {
  if (typeof v !== 'number') return '—'
  if (Math.abs(v) >= 1e12) return `$${(v / 1e12).toFixed(2)}T`
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  return `$${v.toFixed(0)}`
}
