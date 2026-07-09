// Live market-data surfaces for the workspace dashboard (/stocks/:ticker),
// independent of any AI research run — kept refreshing from yfinance / SEC /
// FMP / Adanos whether or not a pipeline has run on this ticker.
//
// One export: MarketDataZone — the LEFT column of the workspace grid, carrying
// EVERY live (Non-AI) surface, ordered by analyst importance: price trend →
// valuation snapshot → market-implied expectations (reverse-DCF) → financials
// TTM → catalyst calendar → retail sentiment. The right column is the AI/report side
// (AIZone) — the semantic split is market vs report, full stop. (An earlier
// layout moved catalysts + sentiment to a full-width band below the grid for
// column-height symmetry; that read as "catalysts = market, sentiment = AI",
// crossing the semantic line. AIZone is sticky instead, so the shorter report
// column tracks the scroll rather than leaving trailing whitespace.)

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  useTickerPrice,
  useTickerFinancials,
  useTickerCatalysts,
  useTickerHistoricalBands,
  type FinancialsData,
  type HistoricalBand,
  type Technicals,
} from '../../hooks/useTickerData'
import { useTickerSentiment, type SentimentSnapshot } from '../../hooks/useTickerSentiment'
import { useI18n, tSync, type Locale } from '../../i18n'
import { formatCurrencyCompact } from '../../utils/format'
import { degradedLabel } from './degradedLabel'
import { PriceTrendChart } from '../../components/charts/PriceTrendChart'
import { MarketImpliedPanel } from '../../components/valuation/MarketImpliedPanel'
import { SkelBar } from '../../components/Skeleton'

interface MarketDataZoneProps {
  ticker: string
}

export function MarketDataZone({ ticker }: MarketDataZoneProps): React.ReactElement {
  const {
    data: price,
    isPending: pricePending,
    isError: priceError,
    error: priceErr,
    refetch: refetchPrice,
  } = useTickerPrice(ticker)
  const {
    data: fin,
    isPending: finPending,
    isError: finError,
    error: finErr,
    refetch: refetchFin,
  } = useTickerFinancials(ticker)
  const {
    data: catalysts,
    isError: catalystsError,
    error: catalystsErr,
    isPending: catalystsPending,
    refetch: refetchCatalysts,
  } = useTickerCatalysts(ticker)
  const {
    data: sentiment,
    isPending: sentimentPending,
    isError: sentimentError,
    refetch: refetchSentiment,
  } = useTickerSentiment(ticker)
  const { data: band, isError: bandError, refetch: refetchBand } = useTickerHistoricalBands(ticker)
  const { t, locale } = useI18n()

  return (
    <section data-testid="market-data-zone">
      <ZoneHeader />
      <p style={zoneDesc}>{t('workspace.market.zoneDesc')}</p>

      {/* Price chart — the visual anchor. Analysts orient on price action +
          52w range first, so the richest single surface leads the column. */}
      <MktCard title={t('workspace.market.priceTrend')} liveTag={providerTag(price?.data_source)}>
        {priceError ? (
          <CardError status={priceErr?.status} onRetry={() => void refetchPrice()} />
        ) : (
          <>
            <PriceTrendChart
              points={price?.history ?? null}
              loading={pricePending}
              currentPrice={price?.current_price}
              sessionState={price?.session_state}
            />
            <TechnicalsStrip
              tech={price?.technicals}
              canon52wLow={fin?.market?.price_52w_low}
              canon52wHigh={fin?.market?.price_52w_high}
            />
            <WarningLines warnings={price?.warnings} />
          </>
        )}
      </MktCard>

      {/* 行情快照 — valuation multiples + size at a glance (the "what's it
          worth" context the reverse-DCF probe below then interrogates). */}
      <MktCard title={t('workspace.market.snapshot')} liveTag={providerTag(fin?.data_source)}>
        {finError ? (
          <CardError status={finErr?.status} onRetry={() => void refetchFin()} />
        ) : finPending ? (
          <KvSkeleton count={6} />
        ) : (
          <>
            <Kv4
              cells={[
                {
                  label: t('workspace.market.marketCap'),
                  value: fmtMc(fin?.market?.market_cap, locale),
                },
                { label: 'P/E (TTM)', value: fmt(fin?.market?.pe_ratio, 1) },
                {
                  label: 'EV/EBITDA (op)',
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
                  // Reconcile against the DCF/WACC beta shown in the AI report
                  // (right column, same workspace): this is the vendor's raw
                  // 5Y regression beta. The valuation chapter's β is this same
                  // figure after an asymmetric Blume adjustment (β>1 shrinks
                  // toward 1.0 for a steadier forward estimate; β≤1 — genuine
                  // low-β defensives — is kept as-is), so the two numbers can
                  // legitimately differ side by side without one being wrong.
                  sub: t('workspace.market.betaCaliber'),
                  subTitle: t('workspace.market.betaCaliberDetail'),
                },
                { label: '52W Low', value: fmtPrice(fin?.market?.price_52w_low) },
                { label: '52W High', value: fmtPrice(fin?.market?.price_52w_high) },
              ]}
            />
            <ProvenanceFootnote provenance={fin?.provenance} />
          </>
        )}
      </MktCard>

      {/* Multiple vs own history — Koyfin's signature "is this cheap vs its own
          past", surfaced PRE-report, with our cheap/fair/rich classification +
          sample depth a static snapshot multiple can't convey. Hides itself when
          the band can't be computed (cold ticker / thin history). */}
      <ValuationBandCard band={band} isError={bandError} onRetry={() => void refetchBand()} t={t} />

      {/* Market-implied expectations — reverse-DCF probe that interrogates what
          today's price requires you to believe. Placed right after the multiples
          it reasons about; expanded by default (a primary valuation surface). */}
      <MarketImpliedPanel ticker={ticker} />

      {/* Financial TTM */}
      <MktCard title={t('workspace.market.financialsTtm')} liveTag={providerTag(fin?.data_source)}>
        {finError ? (
          <CardError status={finErr?.status} onRetry={() => void refetchFin()} />
        ) : finPending ? (
          <KvSkeleton count={4} />
        ) : (
          <>
            <Kv4
              cells={[
                {
                  label: t('workspace.market.revenueTtm'),
                  value: fmtMc(fin?.income?.revenue, locale),
                },
                {
                  label: 'EBITDA (op)',
                  value: fmtMc(fin?.income?.ebitda, locale),
                  sub:
                    typeof fin?.valuation?.ebitda_reported === 'number'
                      ? t('workspace.market.streetCaliber', {
                          v: fmtMc(fin.valuation.ebitda_reported, locale),
                        })
                      : undefined,
                  subTitle: t('workspace.market.ebitdaCaliber'),
                },
                {
                  label: 'Net Income',
                  value: fmtMc(fin?.income?.net_income, locale),
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

      {/* Catalyst calendar — event surface, but still market-side (Non-AI). */}
      <MktCard title={t('workspace.market.catalystCalendar')}>
        {catalystsError ? (
          <CardError
            message={t('workspace.market.catalystError')}
            status={catalystsErr?.status}
            onRetry={() => void refetchCatalysts()}
          />
        ) : catalystsPending ? (
          <CatalystSkeleton />
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
                  style={{ display: 'flex', alignItems: 'baseline', gap: 6, overflow: 'hidden' }}
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
                  {(c.source_count ?? 1) > 1 && (
                    <span
                      title={t('workspace.market.catalystSourceCount')}
                      style={{ flexShrink: 0, fontSize: 10, color: 'var(--text-muted)' }}
                    >
                      ·{c.source_count}×
                    </span>
                  )}
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
        <SentimentCard
          snapshot={sentiment}
          isPending={sentimentPending}
          isError={sentimentError}
          onRetry={() => void refetchSentiment()}
        />
      </MktCard>
    </section>
  )
}

// Renders the Adanos retail-sentiment aggregate. Distinct states that must NOT
// be conflated (the bug was a transient failure rendering as "not configured"):
//   • loading (fetch in flight)       → skeleton, never an empty verdict
//   • transport error / provider_error → "source unavailable · retry" (the key
//     IS configured — do NOT tell the user to go add one)
//   • available=false, unconfigured   → "未配置 Adanos · 去设置 →" CTA to /settings
//   • available=true                  → coverage + bull/bear split (涨绿跌红) + buzz + rows
// Mirrors the backend AlignmentToken Literal (adanos_provider.py) — every token
// the provider can emit has a key here AND an i18n entry, so the badge never
// silently drops a state the way the old free-phrase values did.
const ALIGNMENT_KEYS = new Set([
  'aligned',
  'partial_divergence',
  'split',
  'single_source',
  'no_data',
])

// Soft state for an upstream rate-limit (HTTP 429). Self-healing, so it must NOT
// read as a hard outage (no --danger red, no fabricated status). Muted copy + an
// immediate-retry button; useTickerSentiment also auto-refetches on this reason.
function SentimentRateLimited({ onRetry }: { onRetry: () => void }): React.ReactElement {
  const { t } = useI18n()
  return (
    <div
      data-testid="sentiment-rate-limited"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        gap: 8,
        padding: '12px 4px',
        fontFamily: 'var(--font-mono)',
      }}
    >
      <span style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
        {t('workspace.market.sentimentRateLimited')}
      </span>
      <span style={{ fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.55 }}>
        {t('workspace.market.sentimentRateLimitedHint')}
      </span>
      <button
        type="button"
        onClick={onRetry}
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--accent-cyan)',
          background: 'transparent',
          border: '1px solid var(--border-cyan-soft)',
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

function SentimentCard({
  snapshot,
  isPending,
  isError,
  onRetry,
}: {
  snapshot?: SentimentSnapshot
  isPending: boolean
  isError: boolean
  onRetry: () => void
}): React.ReactElement {
  const { t } = useI18n()

  if (isPending) {
    return <SentimentSkeleton />
  }

  // Upstream throttled us (HTTP 429). Transient and self-healing — show a SOFT
  // "rate-limited, auto-retrying" notice, NOT the red outage error and NOT a
  // fabricated "Upstream returned 5xx" (the call never reached a 5xx). The hook
  // auto-refetches on this reason; the button is an immediate manual retry.
  if (snapshot?.reason === 'rate_limited') {
    return <SentimentRateLimited onRetry={onRetry} />
  }

  // Transport failure (network/timeout/non-2xx) OR the backend reached Adanos
  // but the call genuinely failed (reason='provider_error'). The key is
  // configured — show a retry, never the "go configure" CTA, which would be a lie.
  if (isError || !snapshot || snapshot.reason === 'provider_error') {
    return <CardError onRetry={onRetry} />
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
            {/* Paint ONLY the known shares: green=bullish, red=bearish (when
                known). When bear is null the remainder is neutral+unknown, NOT
                bearish — leaving the track background show through avoids
                overstating bearishness (the numeric label already hides bear). */}
            <span style={{ width: `${bull}%`, background: 'var(--success)' }} />
            {typeof bear === 'number' && (
              <span style={{ width: `${bear}%`, background: 'var(--danger)' }} />
            )}
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

      <WarningLines warnings={snapshot.warnings} />
    </div>
  )
}

// Amber per-line degradation notices under a card body — the data still flows,
// but its caliber is reduced (stale graft, cross-source divergence, …) and a
// degraded surface must be visibly degraded (可溯源 red-line).
function WarningLines({ warnings }: { warnings?: string[] }): React.ReactElement | null {
  const items = (warnings ?? []).map((w) => w.trim()).filter((w) => w.length > 0)
  if (items.length === 0) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 8 }}>
      {items.map((w, i) => (
        <span
          key={i}
          data-testid="market-warning-line"
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

const BAND_METRIC_LABEL: Record<string, string> = { ev_ebitda: 'EV/EBITDA', p_fcf: 'P/FCF' }

// Workspace "multiple vs own history" card: where the current EV/EBITDA (or
// P/FCF) sits in the company's own multi-year P25–P75 band, plus a cheap / fair /
// rich classification — surfaced PRE-report (the report's football field carries
// the same band post-run). Multiple-space mini-rail; hides when the band can't be
// computed (cold ticker / thin history) so it never shows an empty shell. Backend
// band.warnings (Chinese prose) are deliberately NOT rendered.
function ValuationBandCard({
  band,
  isError,
  onRetry,
  t,
}: {
  band: HistoricalBand | undefined
  isError?: boolean
  onRetry?: () => void
  t: (key: string, params?: Record<string, string | number>) => string
}): React.ReactElement | null {
  const fin = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
  // A fetch error is NOT the same as "no band exists": silently hiding it would
  // read as "this ticker has no valuation band" (a cold/thin-history truth) when
  // really the request failed. Surface it with retry; only a genuine no-band hides.
  if (isError && (!band || !fin(band.current))) {
    return (
      <MktCard title={t('workspace.market.valuationBand')}>
        <CardError
          message={t('workspace.market.valuationBandError')}
          onRetry={onRetry ?? (() => {})}
        />
      </MktCard>
    )
  }
  if (!band || !fin(band.current) || !fin(band.p25) || !fin(band.p75)) return null
  const cur = band.current
  const p25 = band.p25
  const p75 = band.p75
  const med = band.median
  const p90 = band.p90
  const pts = [cur, p25, p75, med, p90].filter(fin)
  const lo = Math.min(...pts) * 0.94
  const hi = Math.max(...pts) * 1.04
  const span = hi - lo || 1
  const x = (v: number) => `${((v - lo) / span) * 100}%`
  const fx = (v: number) => `${v.toFixed(1)}×`
  const cls = band.classification ?? 'unknown'
  const clsColor =
    cls === 'cheap'
      ? 'var(--success)'
      : cls === 'expensive'
        ? 'var(--danger)'
        : cls === 'fair'
          ? 'var(--text-secondary)'
          : 'var(--text-muted)'
  const clsKey = cls === 'expensive' ? 'rich' : cls
  const metric = BAND_METRIC_LABEL[band.metric ?? ''] ?? (band.metric ?? '').toUpperCase()

  return (
    <MktCard title={t('workspace.market.valuationBand')}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 12,
          flexWrap: 'wrap',
        }}
      >
        <span
          style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)' }}
        >
          {metric}
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 9,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            padding: '1px 7px',
            borderRadius: 999,
            color: clsColor,
            border: `1px solid color-mix(in srgb, ${clsColor} 45%, transparent)`,
            background: `color-mix(in srgb, ${clsColor} 12%, transparent)`,
          }}
        >
          {t(`chart.footballField.history.${clsKey}`)}
        </span>
        {fin(band.sample_count) && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-dim)' }}>
            {t('chart.footballField.history.samples', { count: band.sample_count })}
          </span>
        )}
      </div>
      <div style={{ position: 'relative', height: 26 }}>
        <div
          style={{
            position: 'absolute',
            top: 13,
            left: 0,
            right: 0,
            height: 1,
            background: 'var(--border-grid)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            top: 7,
            left: x(p25),
            width: `calc(${x(p75)} - ${x(p25)})`,
            height: 12,
            borderRadius: 3,
            background:
              'linear-gradient(90deg, color-mix(in srgb, var(--primary) 18%, transparent), color-mix(in srgb, var(--secondary) 26%, transparent))',
            border: '1px solid color-mix(in srgb, var(--secondary) 35%, transparent)',
          }}
        />
        {fin(med) && (
          <div
            style={{
              position: 'absolute',
              top: 4,
              left: x(med),
              width: 1.5,
              height: 18,
              background: 'var(--text-secondary)',
            }}
          />
        )}
        {fin(p90) && (
          <div
            style={{
              position: 'absolute',
              top: 8,
              left: x(p90),
              width: 1,
              height: 10,
              background: 'var(--text-dim)',
            }}
          />
        )}
        <div
          style={{
            position: 'absolute',
            top: 2,
            bottom: 2,
            left: x(cur),
            width: 2,
            background: clsColor,
            boxShadow: `0 0 8px ${clsColor}`,
          }}
        />
        <div
          style={{
            position: 'absolute',
            top: -4,
            left: x(cur),
            transform: 'translateX(-50%)',
            width: 0,
            height: 0,
            borderLeft: '4px solid transparent',
            borderRight: '4px solid transparent',
            borderTop: `5px solid ${clsColor}`,
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
        <span style={{ color: clsColor }}>
          {t('chart.footballField.history.now')} {fx(cur)}
        </span>
        <span>
          P25 {fx(p25)} · {t('chart.footballField.history.median')} {fin(med) ? fx(med) : '—'} · P75{' '}
          {fx(p75)}
        </span>
      </div>
    </MktCard>
  )
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
        // auto-fit so a wide market column (≥1920 superwide) packs 3 cells per
        // row instead of leaving the 2-col snapshot half-empty; min 280px keeps
        // each value tile legible and falls back to 2 cols at the default 1440.
        gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
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

// Loading skeleton for the Kv4 metric grids (snapshot + financials TTM). Without
// it, an in-flight fin fetch rendered every cell as "—", which reads as "no data
// for this stock" rather than "loading" — the same confusion the catalyst
// skeleton fixed. Mirrors Kv4's 2-col grid + cell padding so the card doesn't
// reflow when the real values land. (Cold-start 503 is handled separately by
// CardError's calm state; this is the normal-fetch window only.)
function KvSkeleton({ count }: { count: number }): React.ReactElement {
  return (
    <div
      style={{
        display: 'grid',
        // Mirror Kv4's responsive auto-fit grid so the card doesn't reflow when
        // real values land (was a fixed 2-col, which jumped to 3 on wide screens).
        gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
        gap: 1,
        background: 'var(--border-faint)',
        borderRadius: 6,
        overflow: 'hidden',
      }}
    >
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} style={{ background: 'var(--bg-card)', padding: '10px 12px' }}>
          <SkelBar height={8} width="52%" />
          <div style={{ marginTop: 7 }}>
            <SkelBar height={14} width="74%" />
          </div>
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

// Delay (ms) before the "classifying news" hint surfaces. A cold catalyst
// fetch is ~12–18s of news → LLM classify, so a bare shimmer reads as broken to
// an analyst long before React Query's timeout flips it to an error. The hint
// converts that silent wait into "this is working, ~15s". It's gated behind a
// threshold so a warm-cache fetch that returns in 1–2s never flashes copy that
// would itself read as a stall.
const CATALYST_HINT_DELAY_MS = 6000

function CatalystSkeleton(): React.ReactElement {
  const { t } = useI18n()
  const [showHint, setShowHint] = useState(false)

  useEffect(() => {
    const id = window.setTimeout(() => setShowHint(true), CATALYST_HINT_DELAY_MS)
    return () => window.clearTimeout(id)
  }, [])

  return (
    <div
      data-testid="catalyst-skeleton"
      aria-busy="true"
      style={{ display: 'flex', flexDirection: 'column', gap: 6 }}
    >
      {[0, 1, 2, 3, 4].map((i) => (
        <div
          key={i}
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr auto auto',
            gap: 10,
            alignItems: 'center',
            padding: '7px 10px',
            background: 'var(--bg-card-50)',
            borderRadius: 6,
          }}
        >
          <SkelBar height={11} width={`${72 - i * 7}%`} />
          <SkelBar height={10} width={56} />
          <SkelBar height={10} width={18} />
        </div>
      ))}
      {showHint && (
        <div
          data-testid="catalyst-classify-hint"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginTop: 2,
            padding: '2px 2px',
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            color: 'var(--text-muted)',
            letterSpacing: '0.04em',
          }}
        >
          {/* Blue "active step" pulse (legal pulse-dot, §7): a working signal,
              not the green live-data dot — recolored to --primary inline. */}
          <span
            aria-hidden="true"
            className="cosmic-pulse-dot"
            style={{
              width: 6,
              height: 6,
              background: 'var(--primary)',
              boxShadow: '0 0 10px var(--primary-soft)',
            }}
          />
          <span>{t('workspace.market.catalystClassifying')}</span>
        </div>
      )}
    </div>
  )
}

// Loading skeleton for the retail-sentiment card — a split-bar placeholder + the
// three per-platform rows, so a slow Adanos round-trip shows "loading" instead
// of momentarily flashing the "not configured" CTA.
function SentimentSkeleton(): React.ReactElement {
  return (
    <div
      data-testid="sentiment-skeleton"
      aria-busy="true"
      style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
    >
      <SkelBar height={8} width="100%" radius={999} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {[0, 1, 2].map((i) => (
          <SkelBar key={i} height={28} width="100%" radius={6} />
        ))}
      </div>
    </div>
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
  // Cold-start 503 ("data engine starting"): the post-yield warmup is still wiring
  // the provider chain (~2s after boot). Transient + self-healing — the live-data
  // queries fast-refetch on 503 — so show a CALM starting state (muted, pulse dot),
  // NOT the --danger red outage, so a cold app open doesn't flash "data unavailable".
  if (status === 503) {
    return (
      <div
        data-testid="market-card-starting"
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-start',
          gap: 6,
          padding: '12px 4px',
          fontFamily: 'var(--font-mono)',
        }}
      >
        <span
          style={{
            fontSize: 11.5,
            color: 'var(--text-secondary)',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <span
            aria-hidden="true"
            className="cosmic-pulse-dot"
            style={{
              width: 6,
              height: 6,
              background: 'var(--primary)',
              boxShadow: '0 0 10px var(--primary-soft)',
            }}
          />
          {t('workspace.market.engineStarting')}
        </span>
        <span style={{ fontSize: 10, color: 'var(--text-dim)', lineHeight: 1.55 }}>
          {t('workspace.market.engineStartingHint')}
        </span>
      </div>
    )
  }
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
        {/* Never fabricate a status. Real HTTP errors (price/financials carry
            err.status) print the code; a 200-body failure (sentiment
            provider_error) has none → a status-free hint, not a made-up "5xx". */}
        {status != null
          ? t('workspace.market.dataUnavailableHint', { status })
          : t('workspace.market.dataUnavailableHintNoStatus')}
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

export function TechnicalsStrip({
  tech,
  canon52wLow,
  canon52wHigh,
}: {
  tech?: Technicals
  /** Canonical 52w low/high from the financials snapshot (`fin.market.price_52w_*`)
   *  — the SAME value the snapshot tile shows. The strip's range bar defers to it so
   *  the workspace's two 52w surfaces never disagree: the /price technicals compute
   *  their own 52w from a different price-bar window + count-cap, which can diverge
   *  ~1% from the /financials NormalizedPrice (JPM: 264.57 strip vs 262.69 tile).
   *  Falls back to the technicals' own value when financials haven't loaded. */
  canon52wLow?: number | null
  canon52wHigh?: number | null
}): React.ReactElement | null {
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
  // 52w band defers to the canonical financials value (snapshot-tile source) so the
  // two surfaces agree; fall back to the technicals' own window when absent.
  const low52w = typeof canon52wLow === 'number' ? canon52wLow : tech.low_52w
  const high52w = typeof canon52wHigh === 'number' ? canon52wHigh : tech.high_52w
  // Re-price the marker against whichever band is printed so it can never contradict
  // the shown low/high; clamp into [0,1] so a price past the band edge stays on rail.
  const pos =
    typeof low52w === 'number' &&
    typeof high52w === 'number' &&
    high52w > low52w &&
    typeof tech.current_price === 'number'
      ? Math.max(0, Math.min(1, (tech.current_price - low52w) / (high52w - low52w)))
      : typeof tech.range_position === 'number'
        ? Math.max(0, Math.min(1, tech.range_position))
        : null

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
            <span>{t('workspace.market.low52w', { v: fmtPrice(low52w) })}</span>
            <span style={{ color: 'var(--accent-cyan)' }}>
              {t('workspace.market.range', { pct: (pos * 100).toFixed(0) })}
            </span>
            <span>{t('workspace.market.high52w', { v: fmtPrice(high52w) })}</span>
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
// Compact USD via the format.ts throat — one negative-notation rule (-$5.00B,
// not the hand-rolled "$-5.00B") and one NaN guard for every money cell here.
function fmtMc(v: number | null | undefined, locale: Locale): string {
  return formatCurrencyCompact(v, 'USD', locale)
}
