// Reverse-DCF withheld-target headline (the "verdict", not a probe).
//
// Rendered under the cover verdict badge whenever the POINT target is withheld
// (price_target===null && market_implied!=null) — the directional verdict still
// stands. It turns a blank "target withheld" into the analyst's real question —
// "what is the market actually pricing in, and can a cash-flow model defend
// it?" — using the reverse-DCF figures already frozen into the artifact
// (market_implied + the dcf method range), never an LLM restatement.
//
// Two regimes, from MarketImpliedCheck:
//   • reachable  (implied_growth present): the price implies an annual growth
//     the cash-flow model can still reach — shown as the "market is pricing in
//     ~X%/yr" tension lede + a defensible cash-flow fair-value band.
//   • unreachable (growth_unreachable): even the solver's max growth tops out
//     below the market — an option-value stock; the lede states the ceiling.
//
// Editorial composition (Micron design, 2026-06): a restrained tension lede +
// a uniform metric-card row + a slim horizontal value bar. Flat — no glow, no
// log-scale ruler (the old vertical ruler was the cover's clutter). Numbers are
// --font-display tabular-nums; cyan is reserved for the LIVE market price.

import { useI18n } from '../../../i18n'
import { formatCurrency } from '../../../utils/format'
import type { DcfShape, ValuationMethodShape } from './types'

interface ReverseDcfHeadlineProps {
  marketImplied: NonNullable<DcfShape['market_implied']>
  /** The dcf method range from valuation_synthesis.methods (name==='dcf'). When
   * the target is withheld financial_modeling.implied_price is null, so the
   * "cash-flow model ceiling" MUST come from this method mid, not implied_price. */
  dcfMethod: ValuationMethodShape | null
  /** valuation_synthesis.current_price — the live pricing anchor (cyan-eligible). */
  currentPrice: number | null
  quoteCurrency: string
}

export function ReverseDcfHeadline({
  marketImplied: mi,
  dcfMethod,
  currentPrice,
  quoteCurrency,
}: ReverseDcfHeadlineProps): React.ReactElement | null {
  const { t, locale } = useI18n()
  const cur = (n: number): string => formatCurrency(n, quoteCurrency, locale, 2)

  const unreachable = mi.growth_unreachable
  // The cash-flow ceiling the headline contrasts against the market:
  //   reachable  → the DCF method mid (the most the model stands on)
  //   unreachable→ ceiling_price (the most the model reaches at growth_ceiling)
  const dcfMid = dcfMethod?.mid ?? null
  const ceilingValue = unreachable ? (mi.ceiling_price ?? null) : dcfMid
  const market = currentPrice

  // Both regimes need a ceiling + a market price to draw the contrast.
  if (ceilingValue == null || market == null || ceilingValue <= 0 || market <= 0) return null

  const multiple = market / ceilingValue
  const multipleLabel = multiple >= 9.5 ? `${Math.round(multiple)}×` : `${multiple.toFixed(1)}×`
  const growthPct =
    !unreachable && mi.implied_growth != null ? `${(mi.implied_growth * 100).toFixed(1)}%` : null
  const ceilingGrowthPct =
    mi.growth_ceiling != null ? `${(mi.growth_ceiling * 100).toFixed(0)}%` : null
  const horizon = `${mi.horizon_years}y`

  // The cash-flow fair-value band = the DCF method's OWN low/high — a true
  // cash-flow range bracketing the dcf mid. NOT valuation_synthesis.target_*,
  // whose high bound can be a non-cash-flow method (e.g. comps P/B on a
  // method-divergent name: MU target_high === peer_median_pb mid), which would
  // both mislabel a price/book figure as "cash-flow" and pin the mid marker to
  // the band's left edge.
  const fvLow = dcfMethod?.low ?? null
  const fvHigh = dcfMethod?.high ?? null
  const fvMid = dcfMid ?? (fvLow != null && fvHigh != null ? (fvLow + fvHigh) / 2 : null)
  // Reachable regime only: in the unreachable (option-value) regime the ceiling
  // is ceiling_price (a different solve) the dcf-method band could sit above, so
  // the lede reframes on the ceiling alone.
  const showFvBand = !unreachable && fvLow != null && fvHigh != null && fvHigh > fvLow

  const impliedCardValue = unreachable ? (ceilingGrowthPct ?? '—') : (growthPct ?? '—')

  return (
    <section
      data-testid="reverse-dcf-headline"
      data-regime={unreachable ? 'unreachable' : 'reachable'}
      style={{ margin: '22px 0 0' }}
    >
      {/* ── the tension lede (conclusion-first verdict, never an LLM probe) ── */}
      {unreachable ? (
        <p style={ledeStyle}>
          {t('chapter.cover.reverseDcf.ledeB.pre')} <Accent>{ceilingGrowthPct ?? '—'}</Accent>{' '}
          {t('chapter.cover.reverseDcf.ledeB.mid')} <Strong>{horizon}</Strong>{' '}
          {t('chapter.cover.reverseDcf.ledeB.impliesOnly')} <Strong>{cur(ceilingValue)}</Strong>{' '}
          {t('chapter.cover.reverseDcf.ledeB.marketAt')}{' '}
          <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>{cur(market)}</span>.
        </p>
      ) : (
        <p style={ledeStyle}>
          {t('chapter.cover.reverseDcf.ledeA.pre')} <Accent>~{growthPct}/yr</Accent>{' '}
          {t('chapter.cover.reverseDcf.ledeA.mid')} <Strong>{horizon}</Strong>.
        </p>
      )}

      {/* ── uniform metric-card row ── */}
      <div style={metricsGrid}>
        <CoverMetric
          label={t('chapter.cover.reverseDcf.marketLive')}
          value={cur(market)}
          color="var(--accent-cyan)"
        />
        <CoverMetric
          label={
            // Reachable regime: ceilingValue is the DCF *mid* (central cash-flow
            // value), NOT a ceiling — the fair-value band brackets it above and the
            // reframe below calls it the cash-flow "floor". Labelling the same number
            // "ceiling" here contradicted that. Only the unreachable (option-value)
            // regime has a true ceiling (ceiling_price = the most the model reaches).
            unreachable
              ? t('chapter.cover.reverseDcf.anchor.ceiling')
              : t('chapter.cover.reverseDcf.anchor.value')
          }
          value={cur(ceilingValue)}
          color="var(--secondary)"
        />
        <CoverMetric
          label={t('chapter.cover.reverseDcf.anchor.implied')}
          value={impliedCardValue}
          unit={unreachable ? `/${horizon}` : '/yr'}
        />
        <CoverMetric
          label={t('chapter.cover.reverseDcf.fairValueBand')}
          value={
            showFvBand && fvLow != null && fvHigh != null ? `${cur(fvLow)}–${cur(fvHigh)}` : '—'
          }
        />
      </div>

      {/* ── slim horizontal value bar: the defensible band vs the live market ── */}
      {showFvBand && fvLow != null && fvHigh != null && (
        <ValueBar low={fvLow} high={fvHigh} mid={fvMid} market={market} cur={cur} />
      )}

      {/* ── one-line reframing (the multiple insight; full reasoning lives in the
           audit callout below) ── */}
      <div style={reframeStyle}>
        {unreachable ? (
          <span>
            <b style={{ color: 'var(--secondary)', fontWeight: 600 }}>
              {t('chapter.cover.reverseDcf.optionalityTitle')}
            </b>{' '}
            {t('chapter.cover.reverseDcf.optionalityBody')}
          </span>
        ) : (
          // Direction-aware: the old single sentence claimed the price "sits
          // {x}× above the cash-flow floor … not a value entry" with x =
          // market / DCF MID — at 0.9× the premium narrative was arithmetically
          // upside-down and contradicted the cover's margin-of-safety line
          // (external audit 2026-07-07). Branch on market vs central value.
          <span>
            <b style={{ color: 'var(--secondary)', fontWeight: 600 }}>
              {multiple >= 1.05
                ? t('chapter.cover.reverseDcf.withheldTitle')
                : multiple <= 0.95
                  ? t('chapter.cover.reverseDcf.belowValueTitle')
                  : t('chapter.cover.reverseDcf.atValueTitle')}
            </b>{' '}
            —{' '}
            {multiple >= 1.05
              ? t('chapter.cover.reverseDcf.withheldBody', { multiple: multipleLabel })
              : multiple <= 0.95
                ? t('chapter.cover.reverseDcf.belowValueBody', { multiple: multipleLabel })
                : t('chapter.cover.reverseDcf.atValueBody')}
          </span>
        )}
      </div>
    </section>
  )
}

function Accent({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <span style={{ color: 'var(--secondary)', fontWeight: 600, whiteSpace: 'nowrap' }}>
      {children}
    </span>
  )
}
function Strong({ children }: { children: React.ReactNode }): React.ReactElement {
  return <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{children}</span>
}

function CoverMetric({
  label,
  value,
  unit,
  color = 'var(--text-primary)',
}: {
  label: string
  value: string
  unit?: string
  color?: string
}): React.ReactElement {
  return (
    <div style={{ background: 'var(--bg-card)', padding: '15px 17px' }}>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          fontWeight: 600,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: 'var(--text-muted)',
          marginBottom: 10,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 23,
          fontWeight: 600,
          letterSpacing: '-0.4px',
          color,
          fontVariantNumeric: 'tabular-nums',
          display: 'flex',
          alignItems: 'baseline',
          gap: 3,
        }}
      >
        {value}
        {unit && <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{unit}</span>}
      </div>
    </div>
  )
}

function ValueBar({
  low,
  high,
  mid,
  market,
  cur,
}: {
  low: number
  high: number
  mid: number | null
  market: number
  cur: (n: number) => string
}): React.ReactElement {
  // Scale spans the defensible band AND the live market (which sits far to the
  // right of the band on a withheld report), so the gap reads at a glance.
  const vMin = Math.min(low, market) * 0.96
  const vMax = Math.max(high, market) * 1.04
  const span = vMax - vMin || 1
  const pct = (v: number): number => ((v - vMin) / span) * 100
  return (
    <div style={{ margin: '20px 0 0' }}>
      <div
        style={{
          position: 'relative',
          height: 6,
          borderRadius: 3,
          background: 'var(--bg-elevated)',
          margin: '14px 0 9px',
        }}
      >
        {/* defensible band */}
        <span
          data-testid="reverse-dcf-band"
          data-band-low={low}
          data-band-high={high}
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: `${pct(low)}%`,
            width: `${Math.max(1.5, pct(high) - pct(low))}%`,
            borderRadius: 3,
            background: 'color-mix(in srgb, var(--secondary) 38%, transparent)',
          }}
        />
        {/* dcf mid marker */}
        {mid != null && (
          <span
            data-testid="reverse-dcf-mid"
            data-mid-pct={pct(mid)}
            style={{
              position: 'absolute',
              top: '50%',
              left: `${pct(mid)}%`,
              width: 10,
              height: 10,
              borderRadius: '50%',
              transform: 'translate(-50%, -50%)',
              background: 'var(--bg-deep)',
              border: '2px solid var(--secondary)',
            }}
          />
        )}
        {/* live market marker */}
        <span
          style={{
            position: 'absolute',
            top: '50%',
            left: `${pct(market)}%`,
            width: 11,
            height: 11,
            borderRadius: '50%',
            transform: 'translate(-50%, -50%)',
            background: 'var(--accent-cyan)',
            boxShadow: '0 0 8px var(--accent-cyan)',
          }}
        />
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-dim)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        <span style={{ color: 'var(--secondary)' }}>
          ◦ {cur(low)}–{cur(high)}
        </span>
        <span style={{ color: 'var(--accent-cyan)' }}>● {cur(market)}</span>
      </div>
    </div>
  )
}

const ledeStyle: React.CSSProperties = {
  fontFamily: 'var(--font-display)',
  fontWeight: 500,
  fontSize: 'clamp(21px, 2.6vw, 29px)',
  lineHeight: 1.32,
  letterSpacing: '-0.3px',
  color: 'var(--text-primary)',
  margin: 0,
  maxWidth: 760,
}

const metricsGrid: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
  gap: 1,
  background: 'var(--border-soft)',
  border: '1px solid var(--border-soft)',
  borderRadius: 'var(--radius-md)',
  overflow: 'hidden',
  margin: '24px 0 0',
}

const reframeStyle: React.CSSProperties = {
  marginTop: 20,
  paddingLeft: 15,
  borderLeft: '2px solid color-mix(in srgb, var(--secondary) 55%, transparent)',
  fontFamily: 'var(--font-body)',
  fontSize: 13,
  lineHeight: 1.6,
  color: 'var(--text-secondary)',
}
