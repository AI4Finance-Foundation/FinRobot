// Left column of the workspace dashboard. Surfaces live market data
// that exists independently of any AI research run — quote snapshot,
// price trend, financials, catalyst calendar, earnings calls, news.
//
// Lives at /stocks/:ticker. Everything here keeps refreshing from
// yfinance / SEC / FMP regardless of whether the user has ever run a
// research pipeline on this ticker.

import { useTickerPrice, useTickerFinancials, useTickerCatalysts } from '../../hooks/useTickerData'
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
      <MktCard title="📊 行情快照" liveTag="yfinance">
        <Kv4
          cells={[
            { label: '市值', value: fmtMc(fin?.market?.market_cap) },
            { label: 'P/E (TTM)', value: fmt(fin?.market?.pe_ratio, 1) },
            {
              label: 'EV/EBITDA',
              value: fmt(fin?.valuation?.ev_ebitda, 1),
            },
            {
              label: 'Beta (5Y)',
              value: fmt(fin?.market?.beta, 2),
            },
            { label: '52W Low', value: fmtPrice(fin?.market?.price_52w_low) },
            { label: '52W High', value: fmtPrice(fin?.market?.price_52w_high) },
          ]}
        />
      </MktCard>

      {/* Price chart */}
      <MktCard title="📈 价格趋势" liveTag="yfinance">
        <PriceSparkline points={price?.history ?? null} />
      </MktCard>

      {/* Financial TTM */}
      <MktCard title="💰 财务指标 · TTM" liveTag="SEC 10-K">
        <Kv4
          cells={[
            { label: '营收 TTM', value: fmtMc(fin?.income?.revenue) },
            { label: 'EBITDA', value: fmtMc(fin?.income?.ebitda) },
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
                  background: 'rgba(15, 15, 34, 0.5)',
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
        borderBottom: '1px solid rgba(245, 158, 11, 0.25)',
      }}
    >
      <span
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 16,
          letterSpacing: '2px',
          color: 'var(--accent-amber)',
          textShadow: '0 0 12px rgba(245, 158, 11, 0.35)',
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
  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        borderRadius: 'var(--radius-md)',
        padding: '14px 16px',
        marginBottom: 12,
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
              border: '1px solid rgba(34, 211, 238, 0.3)',
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

function Kv4({ cells }: { cells: { label: string; value: string }[] }): React.ReactElement {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(2, 1fr)',
        gap: 1,
        background: 'rgba(255, 255, 255, 0.08)',
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
  const first = closes[0]
  const last = closes[closes.length - 1]
  const pct = ((last - first) / first) * 100

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
        <span>{points.length}D 走势</span>
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
