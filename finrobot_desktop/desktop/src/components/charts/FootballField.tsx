import { useMemo } from 'react'
import { useI18n } from '../../i18n'
import type { HistoricalBandShape } from '../../pages/artifact-detail/chapters/types'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
  currentPrice?: number | null
  forwardFiscalPeriod?: string | null
  // Per-multiple historical band (e.g. EV/EBITDA) frozen in the artifact's
  // technical_analysis. When its `metric` matches a rendered method we draw a
  // provenance rail beneath the plot: where the CURRENT multiple sits vs the
  // stock's own 3-year P25–P75 — i.e. WHY that method's price target is what it
  // is. Multiple-space (its own mini-axis), never overlaid on the price plot
  // (the bars are price-space, the band is multiple-space — different units).
  historicalBand?: HistoricalBandShape | null
  // Calibrated synthesis target: the HEADLINE fair-value target (point) and its
  // target_low/target_high band. The point is the SAME number the cover / thesis
  // publish (anchor value when methods diverge, blend when they corroborate) — NOT
  // the raw weighted blend, which the confidence dial discards on divergence. BOTH
  // price-space, overlaid on the same axis as the method bars so methods -> synthesis
  // + band vs current price read in one glance (the traceable form of a fair-value
  // gauge; the band widens as the confidence dial drops). Parts render only when finite.
  targetBand?: { low?: number | null; high?: number | null; point?: number | null } | null
}

export const METHOD_LABEL: Record<string, string> = {
  dcf: 'DCF',
  comps_pe: 'Comps (P/E)',
  comps_pb: 'Comps (P/B)',
  comps_ev_ebitda: 'Comps (EV/EBITDA)',
  ev_ebitda: 'EV/EBITDA',
  p_fcf: 'P/FCF',
  ddm: 'DDM',
  residual_income: 'Residual Income',
  lbo: 'LBO',
}

interface Row {
  method: string
  label: string
  sublabel: string | null
  low: number
  mid: number
  high: number
}

function formatFiscalPeriod(period: string): string {
  const m = period.match(/^(\d{4})/)
  return m ? `FY${m[1]}E` : period
}

/**
 * Comps (P/E) is computed on TWO different earnings calibers depending on data
 * availability (see valuation_aggregator.py): the trailing path multiplies the
 * NOPAT *core* P/E median by core EPS, while the forward path multiplies the
 * *as-reported* peer median P/E by forward EPS. The Competitive table shows
 * both as-reported P/E and core P/E, so a bare "Comps (P/E)" label leaves the
 * analyst unable to tell which median produced the target. We read the backend
 * `source` string to label the caliber explicitly.
 */
export function compsPeLabel(
  source: string | null | undefined,
  forwardFiscalPeriod?: string | null,
): { label: string; sublabel: string | null } {
  const s = (source ?? '').toLowerCase()
  const fyTag = forwardFiscalPeriod ? ` · ${formatFiscalPeriod(forwardFiscalPeriod)}` : ''
  if (s.includes('core_pe') || s.includes('core_eps') || s.includes('核心')) {
    return { label: 'Comps (core P/E)', sublabel: 'NOPAT core · peer median' }
  }
  if (s.includes('forward')) {
    return { label: 'Comps (P/E)', sublabel: `forward EPS · as-reported median${fyTag}` }
  }
  if (s.includes('trailing') || s.includes('median_pe')) {
    return { label: 'Comps (P/E)', sublabel: 'trailing · as-reported median' }
  }
  return { label: METHOD_LABEL.comps_pe, sublabel: null }
}

// Methods whose bar is priced on a FORWARD profit number and so carries the
// `forward · FY…` tag. ev_ebitda left this set when its denominator moved to
// TTM operating EBITDA (批2, single-caliber re-rating anchor) — labelling it
// forward again would misstate the caliber the bar is actually computed on.
const FORWARD_METHODS = new Set(['p_fcf'])

export default function FootballField({
  data,
  title,
  currentPrice,
  forwardFiscalPeriod,
  historicalBand,
  targetBand,
}: ChartProps) {
  const { t } = useI18n()
  const rows: Row[] = useMemo(
    () =>
      (data ?? [])
        .map((d) => {
          const method = String(d.method)
          const source = typeof d.source === 'string' ? d.source : null
          const comps = method === 'comps_pe' ? compsPeLabel(source, forwardFiscalPeriod) : null
          const fyTag =
            FORWARD_METHODS.has(method) && forwardFiscalPeriod
              ? `forward · ${formatFiscalPeriod(forwardFiscalPeriod)}`
              : method === 'ev_ebitda'
                ? 'trailing band × TTM EBITDA'
                : null
          return {
            method,
            label: comps?.label ?? METHOD_LABEL[method] ?? method.toUpperCase(),
            sublabel: comps?.sublabel ?? fyTag,
            low: Number(d.low),
            mid: Number(d.mid),
            high: Number(d.high),
          }
        })
        .filter((r) => Number.isFinite(r.low) && Number.isFinite(r.mid) && Number.isFinite(r.high)),
    [data, forwardFiscalPeriod],
  )

  if (rows.length === 0) return null

  // Provenance rail: show the band only when its metric matches a rendered
  // method (so it reads as that bar's "why") and the core stats are finite.
  const band: HistoricalBandShape | null =
    historicalBand &&
    historicalBand.metric != null &&
    rows.some((r) => r.method === historicalBand.metric) &&
    [historicalBand.current, historicalBand.p25, historicalBand.p75].every(
      (v) => typeof v === 'number' && Number.isFinite(v),
    )
      ? historicalBand
      : null

  // Calibrated synthesis target (price-space). Each part guarded independently:
  // a point with no band still draws a marker; a band needs both ends + width.
  const finiteOrNull = (v: number | null | undefined) =>
    typeof v === 'number' && Number.isFinite(v) ? v : null
  const tgtPoint = finiteOrNull(targetBand?.point)
  const tgtLow = finiteOrNull(targetBand?.low)
  const tgtHigh = finiteOrNull(targetBand?.high)
  // Narrow to a non-null pair so the band render needs no non-null assertions.
  const targetSpan =
    tgtLow !== null && tgtHigh !== null && tgtHigh > tgtLow ? { low: tgtLow, high: tgtHigh } : null

  const dataMin = Math.min(...rows.map((r) => r.low))
  const dataMax = Math.max(...rows.map((r) => r.high))
  const dataMid = (dataMin + dataMax) / 2

  const cp = typeof currentPrice === 'number' && Number.isFinite(currentPrice) ? currentPrice : null

  // Decide whether to include current price in the axis domain.
  // If current is more than 1.4x the data range away from the data midpoint
  // we treat it as "off-scale" — clipping it would lose information so we
  // expand the domain but flag the disconnect explicitly so the chart still
  // reads at a glance.
  const dataSpan = dataMax - dataMin || dataMid * 0.2
  const isOffScale = cp !== null && (cp < dataMin - dataSpan * 0.7 || cp > dataMax + dataSpan * 0.7)

  const axisMin = cp !== null ? Math.min(dataMin, cp) : dataMin
  const axisMax = cp !== null ? Math.max(dataMax, cp) : dataMax
  const padding = (axisMax - axisMin) * 0.06 || 1
  const domainMin = Math.max(0, axisMin - padding)
  const domainMax = axisMax + padding
  const domainSpan = domainMax - domainMin || 1

  const PLOT_HEIGHT = Math.max(160, rows.length * 56 + 50)
  const ROW_HEIGHT = 44
  const BAR_THICKNESS = 18
  const LEFT_LABEL_W = 110
  const RIGHT_VALUE_W = 130
  const TOP_PAD = 16

  const tickStops = computeTickStops(domainMin, domainMax)

  function xPctFor(v: number): number {
    return ((v - domainMin) / domainSpan) * 100
  }

  // Axis ticks + per-method range labels round ≥$100 to whole dollars for a
  // legible scale. The CURRENT-price reference is the number the report
  // reconciles against (cover/narrative/technical all cite it to the cent), so
  // it always shows 2 decimals — otherwise "$307" here vs "$307.34" in the prose
  // reads as a discrepancy when it is the same value.
  function fmtPrice(v: number): string {
    if (Math.abs(v) >= 1000) return `$${Math.round(v).toLocaleString()}`
    if (Math.abs(v) >= 100) return `$${v.toFixed(0)}`
    return `$${v.toFixed(2)}`
  }

  function fmtCurrent(v: number): string {
    return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  }

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
        {cp !== null && (
          <span className="card-badge">
            {t('chart.footballField.current')} {fmtCurrent(cp)}
            {isOffScale && (
              <span style={{ marginLeft: 8, color: 'var(--warning)' }}>
                · {t('chart.footballField.offScaleBadge')}
              </span>
            )}
          </span>
        )}
      </div>

      {isOffScale && cp !== null && (
        <div
          style={{
            margin: '0 16px 8px',
            padding: '8px 12px',
            background: 'color-mix(in srgb, var(--warning) 8%, transparent)',
            border: '1px solid color-mix(in srgb, var(--warning) 35%, transparent)',
            borderRadius: 'var(--radius-sm)',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--warning)',
            lineHeight: 1.5,
          }}
        >
          {t('chart.footballField.offScalePrefix', {
            price: fmtPrice(cp),
            mid: fmtPrice(dataMid),
          })}{' '}
          <strong>{(((cp - dataMid) / dataMid) * 100).toFixed(0)}%</strong> —
          {cp > dataMid
            ? t('chart.footballField.overvalued')
            : t('chart.footballField.undervalued')}
          {t('chart.footballField.offScaleSuffix')}
        </div>
      )}

      <div className="card-body" style={{ padding: '8px 16px 18px' }}>
        <div
          style={{
            position: 'relative',
            height: PLOT_HEIGHT,
            display: 'grid',
            gridTemplateColumns: `${LEFT_LABEL_W}px 1fr ${RIGHT_VALUE_W}px`,
            gap: 10,
          }}
        >
          {/* Method labels */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              paddingTop: TOP_PAD,
              gap: ROW_HEIGHT - 18,
            }}
          >
            {rows.map((r) => (
              <div
                key={r.method}
                style={{
                  height: 18,
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11.5,
                  color: 'var(--text-primary)',
                  letterSpacing: '0.04em',
                }}
              >
                <span style={{ textTransform: 'uppercase' }}>{r.label}</span>
                {r.sublabel && (
                  <span
                    style={{
                      fontSize: 9,
                      color: 'var(--text-muted)',
                      textTransform: 'none',
                      letterSpacing: '0.02em',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {r.sublabel}
                  </span>
                )}
              </div>
            ))}
          </div>

          {/* Plot */}
          <div
            style={{
              position: 'relative',
              background: 'var(--bg-card-50)',
              border: '1px solid var(--border-soft)',
              borderRadius: 'var(--radius-sm)',
              overflow: 'hidden',
            }}
          >
            {/* Vertical grid + tick labels */}
            {tickStops.map((t) => (
              <div
                key={t}
                style={{
                  position: 'absolute',
                  top: 0,
                  bottom: 16,
                  left: `${xPctFor(t)}%`,
                  width: 1,
                  background: 'var(--border-grid)',
                }}
              />
            ))}

            {/* Calibrated synthesis target band (behind the bars; same price axis) */}
            {targetSpan && (
              <div
                style={{
                  position: 'absolute',
                  top: 0,
                  bottom: 16,
                  left: `${xPctFor(targetSpan.low)}%`,
                  width: `${Math.max(0.4, xPctFor(targetSpan.high) - xPctFor(targetSpan.low))}%`,
                  background: 'color-mix(in srgb, var(--primary) 9%, transparent)',
                  borderLeft: '1px dashed color-mix(in srgb, var(--primary) 40%, transparent)',
                  borderRight: '1px dashed color-mix(in srgb, var(--primary) 40%, transparent)',
                }}
                title={`${t('chart.footballField.target')} ${fmtPrice(targetSpan.low)}–${fmtPrice(targetSpan.high)}`}
              />
            )}

            {/* Bars */}
            {rows.map((r, i) => {
              const xLow = xPctFor(r.low)
              const xMid = xPctFor(r.mid)
              const xHigh = xPctFor(r.high)
              const topPx = TOP_PAD + i * ROW_HEIGHT
              return (
                <div key={r.method}>
                  <div
                    style={{
                      position: 'absolute',
                      top: topPx,
                      left: `${xLow}%`,
                      width: `${Math.max(0.4, xHigh - xLow)}%`,
                      height: BAR_THICKNESS,
                      background:
                        'linear-gradient(90deg, color-mix(in srgb, var(--primary) 35%, transparent), color-mix(in srgb, var(--secondary) 55%, transparent))',
                      border: '1px solid color-mix(in srgb, var(--secondary) 55%, transparent)',
                      borderRadius: 4,
                      boxShadow: '0 0 18px color-mix(in srgb, var(--primary) 18%, transparent)',
                    }}
                  />
                  {/* Low tick */}
                  <span
                    style={{
                      position: 'absolute',
                      top: topPx - 2,
                      left: `calc(${xLow}% - 18px)`,
                      width: 18,
                      textAlign: 'right',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 9.5,
                      color: 'var(--text-muted)',
                      lineHeight: '22px',
                    }}
                  >
                    {fmtPrice(r.low)}
                  </span>
                  {/* High tick */}
                  <span
                    style={{
                      position: 'absolute',
                      top: topPx - 2,
                      left: `${xHigh}%`,
                      paddingLeft: 4,
                      fontFamily: 'var(--font-mono)',
                      fontSize: 9.5,
                      color: 'var(--text-muted)',
                      lineHeight: '22px',
                    }}
                  >
                    {fmtPrice(r.high)}
                  </span>
                  {/* Mid dot */}
                  <span
                    style={{
                      position: 'absolute',
                      top: topPx + BAR_THICKNESS / 2 - 5,
                      left: `calc(${xMid}% - 5px)`,
                      width: 10,
                      height: 10,
                      background: 'var(--accent-cyan)',
                      borderRadius: '50%',
                      boxShadow: '0 0 8px var(--accent-cyan)',
                    }}
                    title={`${t('chart.footballField.mid')} ${fmtPrice(r.mid)}`}
                  />
                </div>
              )
            })}

            {/* Current price reference line */}
            {cp !== null && (
              <>
                <div
                  style={{
                    position: 'absolute',
                    top: 0,
                    bottom: 16,
                    left: `${xPctFor(cp)}%`,
                    width: 2,
                    background: 'var(--warning)',
                    boxShadow: '0 0 10px var(--warning)',
                  }}
                />
                <span
                  style={{
                    position: 'absolute',
                    top: 2,
                    left: `calc(${xPctFor(cp)}% + 4px)`,
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    color: 'var(--warning)',
                    letterSpacing: '0.04em',
                    background: 'var(--ff-label-bg)',
                    padding: '1px 4px',
                    borderRadius: 3,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {t('chart.footballField.current')} {fmtCurrent(cp)}
                </span>
              </>
            )}

            {/* Headline synthesis target marker (label rides the bottom so it
                never collides with the current-price label pinned to the top) */}
            {tgtPoint !== null && (
              <>
                <div
                  style={{
                    position: 'absolute',
                    top: 0,
                    bottom: 16,
                    left: `${xPctFor(tgtPoint)}%`,
                    width: 2,
                    background: 'var(--primary)',
                    boxShadow: '0 0 10px var(--primary)',
                  }}
                />
                <span
                  style={{
                    position: 'absolute',
                    bottom: 20,
                    left: `calc(${xPctFor(tgtPoint)}% + 4px)`,
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    color: 'var(--primary)',
                    letterSpacing: '0.04em',
                    background: 'var(--ff-label-bg)',
                    padding: '1px 4px',
                    borderRadius: 3,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {t('chart.footballField.target')} {fmtPrice(tgtPoint)}
                </span>
              </>
            )}

            {/* X axis */}
            <div
              style={{
                position: 'absolute',
                bottom: 0,
                left: 0,
                right: 0,
                height: 16,
                display: 'flex',
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--text-dim)',
                borderTop: '1px solid var(--border-soft)',
                pointerEvents: 'none',
              }}
            >
              {tickStops.map((t) => (
                <span
                  key={t}
                  style={{
                    position: 'absolute',
                    left: `${xPctFor(t)}%`,
                    transform: 'translateX(-50%)',
                    top: 2,
                  }}
                >
                  {fmtPrice(t)}
                </span>
              ))}
            </div>
          </div>

          {/* Per-method upside/downside vs current */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              paddingTop: TOP_PAD,
              gap: ROW_HEIGHT - 18,
            }}
          >
            {rows.map((r) => {
              const upside = cp !== null && cp > 0 ? ((r.mid - cp) / cp) * 100 : null
              const up = upside !== null && upside >= 0
              return (
                <div
                  key={r.method}
                  style={{
                    height: 18,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    color: 'var(--text-secondary)',
                  }}
                >
                  <span style={{ color: 'var(--accent-cyan)' }}>
                    {t('chart.footballField.mid')} {fmtPrice(r.mid)}
                  </span>
                  {upside !== null && (
                    <span style={{ color: up ? 'var(--success)' : 'var(--danger)' }}>
                      {up ? '+' : ''}
                      {upside.toFixed(1)}%
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {band && (
          <HistoryRail
            band={band}
            label={METHOD_LABEL[band.metric ?? ''] ?? (band.metric ?? '').toUpperCase()}
            t={t}
          />
        )}
      </div>
    </div>
  )
}

/**
 * Provenance rail for a comps method: where the CURRENT multiple sits inside the
 * company's own 3-year P25–P75 band. Multiple-space (its OWN mini-axis) so it is
 * never confused with the price plot above — it answers "is the multiple this
 * method applied cheap or rich vs the stock's own history", the missing
 * "cite-the-computation" link that Bloomberg EQRV shows but cannot trace.
 */
function HistoryRail({
  band,
  label,
  t,
}: {
  band: HistoricalBandShape
  label: string
  t: (key: string, params?: Record<string, string | number>) => string
}) {
  const cur = Number(band.current)
  const p25 = Number(band.p25)
  const p75 = Number(band.p75)
  const med = Number(band.median)
  const p90 = Number(band.p90)
  const fin = (v: number) => Number.isFinite(v)
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

  return (
    <div
      style={{
        margin: '4px 16px 0',
        paddingTop: 14,
        borderTop: '1px dashed var(--border-soft)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          marginBottom: 16,
          flexWrap: 'wrap',
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            color: 'var(--text-secondary)',
          }}
        >
          {t('chart.footballField.history.title', {
            metric: label,
            // window_years rides the unified band snapshot (REPORT_BAND_WINDOW_YEARS);
            // artifacts written before the field render the window-agnostic fallback
            // instead of a hardcoded "3-yr" that batch-1c's 5y unification made false.
            window: band?.window_years ? `${band.window_years}-yr` : 'trailing',
          })}
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 9.5,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            padding: '1px 8px',
            borderRadius: 999,
            color: clsColor,
            border: `1px solid color-mix(in srgb, ${clsColor} 45%, transparent)`,
            background: `color-mix(in srgb, ${clsColor} 12%, transparent)`,
          }}
        >
          {t(`chart.footballField.history.${clsKey}`)}
        </span>
        {typeof band.sample_count === 'number' && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-dim)' }}>
            {t('chart.footballField.history.samples', { count: band.sample_count })}
          </span>
        )}
      </div>

      <div style={{ position: 'relative', height: 28 }}>
        <div
          style={{
            position: 'absolute',
            top: 14,
            left: 0,
            right: 0,
            height: 1,
            background: 'var(--border-grid)',
          }}
        />
        {fin(p25) && fin(p75) && (
          <div
            style={{
              position: 'absolute',
              top: 8,
              left: x(p25),
              width: `calc(${x(p75)} - ${x(p25)})`,
              height: 12,
              borderRadius: 3,
              background:
                'linear-gradient(90deg, color-mix(in srgb, var(--primary) 18%, transparent), color-mix(in srgb, var(--secondary) 26%, transparent))',
              border: '1px solid color-mix(in srgb, var(--secondary) 35%, transparent)',
            }}
          />
        )}
        {fin(med) && (
          <div
            style={{
              position: 'absolute',
              top: 5,
              left: x(med),
              width: 1.5,
              height: 18,
              background: 'var(--text-secondary)',
            }}
            title={`${t('chart.footballField.history.median')} ${fx(med)}`}
          />
        )}
        {fin(p90) && (
          <div
            style={{
              position: 'absolute',
              top: 9,
              left: x(p90),
              width: 1,
              height: 10,
              background: 'var(--text-dim)',
            }}
            title={`P90 ${fx(p90)}`}
          />
        )}
        {fin(cur) && (
          <>
            <div
              style={{
                position: 'absolute',
                top: 3,
                bottom: 3,
                left: x(cur),
                width: 2,
                background: clsColor,
                boxShadow: `0 0 8px ${clsColor}`,
              }}
            />
            <div
              style={{
                position: 'absolute',
                top: -3,
                left: x(cur),
                transform: 'translateX(-50%)',
                width: 0,
                height: 0,
                borderLeft: '4px solid transparent',
                borderRight: '4px solid transparent',
                borderTop: `5px solid ${clsColor}`,
              }}
            />
          </>
        )}
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
    </div>
  )
}

function computeTickStops(min: number, max: number): number[] {
  const span = max - min
  if (span <= 0) return [min]
  const raw = span / 5
  const exp = Math.pow(10, Math.floor(Math.log10(raw)))
  const candidates = [1, 2, 2.5, 5, 10].map((m) => m * exp)
  const step = candidates.find((c) => c >= raw) ?? candidates[candidates.length - 1]
  const first = Math.ceil(min / step) * step
  const stops: number[] = []
  for (let v = first; v <= max + step * 0.001; v += step) {
    stops.push(Number(v.toFixed(4)))
  }
  return stops
}
