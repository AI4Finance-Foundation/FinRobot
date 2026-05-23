import { useMemo } from 'react'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
  currentPrice?: number | null
}

const METHOD_LABEL: Record<string, string> = {
  dcf: 'DCF',
  comps_pe: 'Comps (P/E)',
  comps_ev_ebitda: 'Comps (EV/EBITDA)',
  ev_ebitda: 'EV/EBITDA',
  p_fcf: 'P/FCF',
  ddm: 'DDM',
  lbo: 'LBO',
}

interface Row {
  method: string
  label: string
  low: number
  mid: number
  high: number
}

export default function FootballField({ data, title, currentPrice }: ChartProps) {
  const rows: Row[] = useMemo(
    () =>
      (data ?? [])
        .map((d) => ({
          method: String(d.method),
          label: METHOD_LABEL[String(d.method)] ?? String(d.method).toUpperCase(),
          low: Number(d.low),
          mid: Number(d.mid),
          high: Number(d.high),
        }))
        .filter((r) => Number.isFinite(r.low) && Number.isFinite(r.mid) && Number.isFinite(r.high)),
    [data],
  )

  if (rows.length === 0) return null

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

  function fmtPrice(v: number): string {
    if (Math.abs(v) >= 1000) return `$${Math.round(v).toLocaleString()}`
    if (Math.abs(v) >= 100) return `$${v.toFixed(0)}`
    return `$${v.toFixed(2)}`
  }

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
        {cp !== null && (
          <span className="card-badge">
            Current {fmtPrice(cp)}
            {isOffScale && (
              <span style={{ marginLeft: 8, color: 'var(--warning)' }}>· off-scale</span>
            )}
          </span>
        )}
      </div>

      {isOffScale && cp !== null && (
        <div
          style={{
            margin: '0 16px 8px',
            padding: '8px 12px',
            background: 'rgba(217, 119, 6, 0.08)',
            border: '1px solid rgba(217, 119, 6, 0.35)',
            borderRadius: 'var(--radius-sm)',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--warning)',
            lineHeight: 1.5,
          }}
        >
          市价 {fmtPrice(cp)} 距模型估值中位 {fmtPrice(dataMid)} 偏离{' '}
          <strong>{(((cp - dataMid) / dataMid) * 100).toFixed(0)}%</strong> ——
          {cp > dataMid ? '模型隐含明显高估' : '模型隐含明显低估'}，请审计假设来源后再下结论。
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
                  alignItems: 'center',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11.5,
                  color: 'var(--text-primary)',
                  letterSpacing: '0.04em',
                  textTransform: 'uppercase',
                }}
              >
                {r.label}
              </div>
            ))}
          </div>

          {/* Plot */}
          <div
            style={{
              position: 'relative',
              background: 'rgba(15, 15, 34, 0.5)',
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
                  background: 'rgba(255,255,255,0.05)',
                }}
              />
            ))}

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
                        'linear-gradient(90deg, rgba(59,130,246,0.35), rgba(139,92,246,0.55))',
                      border: '1px solid rgba(139,92,246,0.55)',
                      borderRadius: 4,
                      boxShadow: '0 0 18px rgba(59,130,246,0.18)',
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
                    title={`Mid ${fmtPrice(r.mid)}`}
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
                    background: 'rgba(0,0,0,0.4)',
                    padding: '1px 4px',
                    borderRadius: 3,
                    whiteSpace: 'nowrap',
                  }}
                >
                  CURRENT {fmtPrice(cp)}
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
                  <span style={{ color: 'var(--accent-cyan)' }}>Mid {fmtPrice(r.mid)}</span>
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
