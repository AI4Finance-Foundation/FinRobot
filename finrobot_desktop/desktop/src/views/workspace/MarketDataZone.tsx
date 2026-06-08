// Left column of the workspace dashboard. Surfaces live market data
// that exists independently of any AI research run — quote snapshot,
// price trend, financials, catalyst calendar, earnings calls, news.
//
// Lives at /stocks/:ticker. Everything here keeps refreshing from
// yfinance / SEC / FMP regardless of whether the user has ever run a
// research pipeline on this ticker.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  useTickerPrice,
  useTickerFinancials,
  useTickerCatalysts,
  type FinancialsData,
  type Technicals,
} from '../../hooks/useTickerData'
import { useTickerSentiment, type SentimentSnapshot } from '../../hooks/useTickerSentiment'
import { useI18n, tSync } from '../../i18n'
import { degradedLabel } from './degradedLabel'
import { PriceTrendChart } from '../../components/charts/PriceTrendChart'

interface MarketDataZoneProps {
  ticker: string
}

export function MarketDataZone({ ticker }: MarketDataZoneProps): React.ReactElement {
  const {
    data: price,
    isError: priceError,
    error: priceErr,
    refetch: refetchPrice,
  } = useTickerPrice(ticker)
  const {
    data: fin,
    isError: finError,
    error: finErr,
    refetch: refetchFin,
  } = useTickerFinancials(ticker)
  const {
    data: catalysts,
    isError: catalystsError,
    error: catalystsErr,
    refetch: refetchCatalysts,
  } = useTickerCatalysts(ticker)
  const { data: sentiment } = useTickerSentiment(ticker)
  const { t } = useI18n()

  return (
    <section data-testid="market-data-zone">
      <ZoneHeader />
      <p style={zoneDesc}>{t('workspace.market.zoneDesc')}</p>

      {/* 行情快照 */}
      <MktCard title={t('workspace.market.snapshot')} liveTag={providerTag(fin?.data_source)}>
        {finError ? (
          <CardError status={finErr?.status} onRetry={() => void refetchFin()} />
        ) : (
          <>
            <Kv4
              cells={[
                { label: t('workspace.market.marketCap'), value: fmtMc(fin?.market?.market_cap) },
                { label: 'P/E (TTM)', value: fmt(fin?.market?.pe_ratio, 1) },
                {
                  label: 'EV/EBITDA',
                  value: fmt(fin?.valuation?.ev_ebitda, 1),
                  sub:
                    typeof fin?.valuation?.ev_ebitda_reported === 'number'
                      ? t('workspace.market.streetCaliber', {
                          v: fin.valuation.ev_ebitda_reported.toFixed(1),
                        })
                      : undefined,
                  subTitle: t('workspace.market.evEbitdaCaliber'),
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
          </>
        )}
      </MktCard>

      {/* Price chart */}
      <MktCard title={t('workspace.market.priceTrend')} liveTag={providerTag(price?.data_source)}>
        {priceError ? (
          <CardError status={priceErr?.status} onRetry={() => void refetchPrice()} />
        ) : (
          <>
            <PriceTrendChart points={price?.history ?? null} />
            <TechnicalsStrip tech={price?.technicals} />
          </>
        )}
      </MktCard>

      {/* Financial TTM */}
      <MktCard title={t('workspace.market.financialsTtm')} liveTag={providerTag(fin?.data_source)}>
        {finError ? (
          <CardError status={finErr?.status} onRetry={() => void refetchFin()} />
        ) : (
          <>
            <Kv4
              cells={[
                { label: t('workspace.market.revenueTtm'), value: fmtMc(fin?.income?.revenue) },
                {
                  label: 'EBITDA',
                  value: fmtMc(fin?.income?.ebitda),
                  sub:
                    typeof fin?.valuation?.ebitda_reported === 'number'
                      ? t('workspace.market.streetCaliber', {
                          v: fmtMc(fin.valuation.ebitda_reported),
                        })
                      : undefined,
                  subTitle: t('workspace.market.ebitdaCaliber'),
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
          </>
        )}
      </MktCard>

      {/* Catalyst calendar */}
      <MktCard title={t('workspace.market.catalystCalendar')}>
        {catalystsError ? (
          <CardError
            message={t('workspace.market.catalystError')}
            status={catalystsErr?.status}
            onRetry={() => void refetchCatalysts()}
          />
        ) : catalysts && catalysts.length > 0 ? (
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
                  {c.headline ?? t('workspace.market.unnamedEvent')}
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
          <Empty>{t('workspace.market.noCatalysts')}</Empty>
        )}
      </MktCard>

      {/* Retail sentiment (Adanos: Reddit / X.com / Polymarket) */}
      <MktCard title={t('workspace.market.sentiment')}>
        <SentimentCard snapshot={sentiment} />
      </MktCard>
    </section>
  )
}

// Renders the Adanos retail-sentiment aggregate. Three states:
//   • loading (snapshot undefined) → muted placeholder
//   • available=false → "未配置 Adanos · 去设置 →" CTA to /settings (matches the
//     route's documented cold-start empty state in sentiment.py)
//   • available=true → coverage + bull/bear split (涨绿跌红) + buzz + per-source rows
const ALIGNMENT_KEYS = new Set(['aligned', 'split', 'no_data'])

function SentimentCard({ snapshot }: { snapshot?: SentimentSnapshot }): React.ReactElement {
  const { t } = useI18n()

  if (!snapshot) {
    return <Empty>{tSync('common.loading')}</Empty>
  }

  if (!snapshot.available) {
    return (
      <div
        data-testid="sentiment-unconfigured"
        style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            color: 'var(--text-secondary)',
          }}
        >
          {t('workspace.market.sentimentUnconfigured')}
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            color: 'var(--text-muted)',
            lineHeight: 1.55,
          }}
        >
          {t('workspace.market.sentimentUnconfiguredHint')}
        </span>
        <Link
          to="/settings"
          data-testid="sentiment-settings-cta"
          style={{
            alignSelf: 'flex-start',
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            color: 'var(--accent-cyan)',
            border: '1px solid var(--border-cyan-soft)',
            borderRadius: 4,
            padding: '4px 12px',
            letterSpacing: '0.04em',
            textDecoration: 'none',
          }}
        >
          {t('workspace.market.sentimentGoSettings')}
        </Link>
      </div>
    )
  }

  const bull = snapshot.bullish_pct
  const bear = snapshot.bearish_pct
  const alignment =
    snapshot.source_alignment && ALIGNMENT_KEYS.has(snapshot.source_alignment)
      ? t(`workspace.market.sentimentAlignment.${snapshot.source_alignment}`)
      : null

  return (
    <div
      data-testid="sentiment-available"
      style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
    >
      <p style={{ ...zoneDesc, margin: 0 }}>{t('workspace.market.sentimentDesc')}</p>

      {/* coverage + alignment line */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-muted)',
        }}
      >
        {snapshot.coverage && (
          <span>{t('workspace.market.sentimentCoverage', { coverage: snapshot.coverage })}</span>
        )}
        {alignment && (
          <span
            style={{
              color: 'var(--accent-amber)',
              border: '1px solid var(--border-amber-soft)',
              borderRadius: 3,
              padding: '1px 6px',
              fontSize: 9.5,
            }}
          >
            {alignment}
          </span>
        )}
      </div>

      {/* bull / bear split bar — 涨绿跌红 */}
      {typeof bull === 'number' && (
        <div>
          <div
            style={{
              display: 'flex',
              height: 8,
              borderRadius: 999,
              overflow: 'hidden',
              background: 'var(--bg-card-50)',
            }}
          >
            <span style={{ width: `${bull}%`, background: 'var(--success)' }} />
            <span
              style={{
                width: `${typeof bear === 'number' ? bear : 100 - bull}%`,
                background: 'var(--danger)',
              }}
            />
          </div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginTop: 5,
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
            }}
          >
            <span style={{ color: 'var(--success)' }}>
              {t('workspace.market.sentimentBullish')} {bull.toFixed(0)}%
            </span>
            {typeof bear === 'number' && (
              <span style={{ color: 'var(--danger)' }}>
                {t('workspace.market.sentimentBearish')} {bear.toFixed(0)}%
              </span>
            )}
          </div>
        </div>
      )}

      {/* average buzz */}
      {typeof snapshot.average_buzz === 'number' && (
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 8,
            fontFamily: 'var(--font-mono)',
          }}
        >
          <span style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: '0.04em' }}>
            {t('workspace.market.sentimentBuzz')}
          </span>
          <span
            style={{
              fontSize: 14,
              color: 'var(--text-primary)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {snapshot.average_buzz.toFixed(0)}
          </span>
        </div>
      )}

      {/* per-platform rows (Reddit / X.com / Polymarket) */}
      {snapshot.sources.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {snapshot.sources.map((s) => (
            <div
              key={s.platform}
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr auto auto',
                gap: 10,
                alignItems: 'center',
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                padding: '6px 10px',
                background: 'var(--bg-card-50)',
                borderRadius: 6,
                opacity: s.has_data ? 1 : 0.5,
              }}
            >
              <span style={{ color: 'var(--text-secondary)' }}>{s.platform}</span>
              <span
                style={{
                  color:
                    typeof s.bullish_pct === 'number'
                      ? s.bullish_pct >= 50
                        ? 'var(--success)'
                        : 'var(--danger)'
                      : 'var(--text-muted)',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {typeof s.bullish_pct === 'number' ? `${s.bullish_pct.toFixed(0)}%` : '—'}
              </span>
              <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                {typeof s.activity_value === 'number'
                  ? `${s.activity_value} ${s.activity_label}`
                  : s.activity_label}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <Empty>{t('workspace.market.sentimentNoSources')}</Empty>
      )}

      {snapshot.warnings.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {snapshot.warnings.map((w, i) => (
            <span
              key={i}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9.5,
                color: 'var(--accent-amber)',
                lineHeight: 1.5,
              }}
            >
              ⚠ {w}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function ZoneHeader(): React.ReactElement {
  const { t } = useI18n()
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
        {t('workspace.market.zoneTitle')}
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
        boxShadow: hover ? '0 8px 32px var(--primary-soft)' : 'none',
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

// Shown when an upstream data fetch fails (5xx / network). Critical for analyst
// trust: a backend outage must NOT silently degrade to "—" / "无催化剂", which
// reads as "this stock has no data" rather than "the source is down". Mirrors
// AIZone's error state; the retry button re-runs the failed query.
function CardError({
  message,
  status,
  onRetry,
}: {
  message?: string
  status?: number
  onRetry: () => void
}): React.ReactElement {
  const { t } = useI18n()
  return (
    <div
      data-testid="market-card-error"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        gap: 8,
        padding: '12px 4px',
        fontFamily: 'var(--font-mono)',
      }}
    >
      <span style={{ fontSize: 11.5, color: 'var(--danger)' }}>
        ⚠ {message ?? t('workspace.market.dataUnavailable')}
      </span>
      <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>
        {t('workspace.market.dataUnavailableHint', { status: status ?? '5xx' })}
      </span>
      <button
        type="button"
        onClick={onRetry}
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--danger)',
          background: 'var(--negative-bg)',
          border: '1px solid var(--danger)',
          borderRadius: 4,
          padding: '4px 12px',
          cursor: 'pointer',
          letterSpacing: '0.04em',
        }}
      >
        {t('workspace.market.retry')}
      </button>
    </div>
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

function ProvenanceFootnote({
  provenance,
  showPeriodEnd,
}: {
  provenance?: FinancialsData['provenance']
  showPeriodEnd?: boolean
}): React.ReactElement | null {
  const { t } = useI18n()
  if (!provenance) return null
  const provider = provenance.provider
  const periodEnd = provenance.as_of
  const degraded = provenance.degraded ?? []
  const parts: string[] = []
  if (provider) parts.push(t('workspace.market.source', { provider }))
  if (showPeriodEnd && periodEnd) parts.push(t('workspace.market.ttmAsOf', { date: periodEnd }))
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
          title={degradedLabel(t, d)}
          style={{
            color: 'var(--accent-amber)',
            border: '1px solid var(--border-amber-soft)',
            borderRadius: 3,
            padding: '1px 5px',
            fontSize: 9,
          }}
        >
          ⚠ {degradedLabel(t, d)}
        </span>
      ))}
    </div>
  )
}

// Trend snapshot under the price line: 多/空头排列 (SMA stack) + the SMA values
// + a 52-week range bar with the current-price marker. Numbers come straight
// from the deterministic technical_payload (SMA close-based, 52w intraday) — no
// client-side recompute, so what's shown matches the engine and the chart.
const TREND_META: Record<string, { labelKey: string; color: string }> = {
  uptrend: { labelKey: 'workspace.market.trend.uptrend', color: 'var(--success)' },
  downtrend: { labelKey: 'workspace.market.trend.downtrend', color: 'var(--danger)' },
  sideways: { labelKey: 'workspace.market.trend.sideways', color: 'var(--text-muted)' },
}

export function TechnicalsStrip({ tech }: { tech?: Technicals }): React.ReactElement | null {
  const { t } = useI18n()
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
          ? t('workspace.market.trendInsufficient')
          : t('workspace.market.trendUnavailable')}
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
          {t(meta.labelKey)}
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
              title={t('workspace.market.rangeMarker', {
                price: fmtPrice(tech.current_price),
                pct: (pos * 100).toFixed(0),
              })}
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
            <span>{t('workspace.market.low52w', { v: fmtPrice(tech.low_52w) })}</span>
            <span style={{ color: 'var(--accent-cyan)' }}>
              {t('workspace.market.range', { pct: (pos * 100).toFixed(0) })}
            </span>
            <span>{t('workspace.market.high52w', { v: fmtPrice(tech.high_52w) })}</span>
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
