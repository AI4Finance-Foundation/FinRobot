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
  type Technicals,
} from '../../hooks/useTickerData'
import { tSync } from '../../i18n'
import { PriceTrendChart } from '../../components/charts/PriceTrendChart'

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
        <PriceTrendChart points={price?.history ?? null} />
        <TechnicalsStrip tech={price?.technicals} />
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
              subTitle: '主显=营业口径 EBITDA（EBIT+D&A）。街口径=净利+税+利息+D&A，含利息收入。',
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

// Trend snapshot under the price line: 多/空头排列 (SMA stack) + the SMA values
// + a 52-week range bar with the current-price marker. Numbers come straight
// from the deterministic technical_payload (SMA close-based, 52w intraday) — no
// client-side recompute, so what's shown matches the engine and the chart.
const TREND_META: Record<string, { label: string; color: string }> = {
  uptrend: { label: '↑ 多头排列', color: 'var(--success)' },
  downtrend: { label: '↓ 空头排列', color: 'var(--danger)' },
  sideways: { label: '→ 盘整', color: 'var(--text-muted)' },
}

export function TechnicalsStrip({ tech }: { tech?: Technicals }): React.ReactElement | null {
  if (!tech) return null
  if (!tech.available) {
    return (
      <p
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--text-dim)',
          marginTop: 10,
        }}
      >
        {tech.reason === 'insufficient_history'
          ? '趋势数据不足（不足 20 个交易日）'
          : '趋势数据暂不可用'}
      </p>
    )
  }
  const meta = TREND_META[tech.trend ?? 'sideways'] ?? TREND_META.sideways
  // Clamp the marker into [0,1] so a current price poking past the rolling
  // window's extreme can't push the dot outside the track.
  const pos =
    typeof tech.range_position === 'number' ? Math.max(0, Math.min(1, tech.range_position)) : null

  return (
    <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* trend pill + SMA stack */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            color: meta.color,
            border: `1px solid ${meta.color}`,
            borderRadius: 999,
            padding: '2px 9px',
            letterSpacing: '0.04em',
          }}
        >
          {meta.label}
        </span>
        <span style={{ display: 'flex', gap: 12, marginLeft: 'auto' }}>
          {(['sma20', 'sma50', 'sma200'] as const).map((k) => (
            <span key={k} style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
              <span style={{ color: 'var(--text-muted)' }}>{k.toUpperCase()} </span>
              <span style={{ color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums' }}>
                {fmtPrice(tech[k])}
              </span>
            </span>
          ))}
        </span>
      </div>

      {/* 52-week range bar with current-price marker */}
      {pos !== null && (
        <div>
          <div
            style={{
              position: 'relative',
              height: 6,
              borderRadius: 999,
              background: 'linear-gradient(90deg, var(--danger-soft), var(--success-soft))',
            }}
          >
            <span
              title={`现价 ${fmtPrice(tech.current_price)} · 区间位置 ${(pos * 100).toFixed(0)}%`}
              style={{
                position: 'absolute',
                top: '50%',
                left: `${pos * 100}%`,
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: 'var(--accent-cyan)',
                boxShadow: 'var(--glow-cyan)',
                transform: 'translate(-50%, -50%)',
              }}
            />
          </div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginTop: 4,
              fontFamily: 'var(--font-mono)',
              fontSize: 9.5,
              color: 'var(--text-muted)',
            }}
          >
            <span>52W低 {fmtPrice(tech.low_52w)}</span>
            <span style={{ color: 'var(--accent-cyan)' }}>区间 {(pos * 100).toFixed(0)}%</span>
            <span>52W高 {fmtPrice(tech.high_52w)}</span>
          </div>
        </div>
      )}
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
