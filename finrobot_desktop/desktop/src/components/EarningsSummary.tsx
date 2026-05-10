import type { EarningsResult } from '../stores/appStore'
import { useAppStore } from '../stores/appStore'

interface Props {
  result: EarningsResult
}

function fmtPct(val: number): string {
  return `${val >= 0 ? '+' : ''}${val.toFixed(1)}%`
}

function fmtEps(val: number): string {
  return `$${val.toFixed(2)}`
}

function fmtRevenue(val: number): string {
  const abs = Math.abs(val)
  if (abs >= 1e9) return `$${(val / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `$${(val / 1e6).toFixed(1)}M`
  return `$${val.toFixed(0)}`
}

function directionColor(dir: string): string {
  if (dir === 'beat') return 'var(--positive)'
  if (dir === 'miss') return 'var(--negative)'
  return 'var(--text-muted)'
}

function directionBg(dir: string): string {
  if (dir === 'beat') return 'var(--positive-bg)'
  if (dir === 'miss') return 'var(--negative-bg)'
  return 'rgba(255,255,255,0.04)'
}

function directionLabel(dir: string): string {
  if (dir === 'beat') return 'BEAT'
  if (dir === 'miss') return 'MISS'
  return 'INLINE'
}

export default function EarningsSummary({ result }: Props) {
  const beatPct = Math.round(result.beat_rate * 100)

  return (
    <>
      {/* Hero — Earnings Quality Scorecard */}
      <div className="valuation-hero animate-in">
        <div style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          marginBottom: 'var(--sp-5)',
        }}>
          <div>
            <div className="valuation-label">Earnings Analysis</div>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              fontSize: '1.4rem',
              color: 'var(--gold)',
              letterSpacing: '0.03em',
            }}>
              {result.ticker}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div className="valuation-label">Quarters Analyzed</div>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
              fontSize: '1.1rem',
              color: 'var(--text-primary)',
            }}>
              {result.surprises.length}
            </div>
          </div>
        </div>

        {/* Beat Rate — hero metric */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--sp-5)',
          marginBottom: 'var(--sp-5)',
        }}>
          {/* Circular beat rate indicator */}
          <div style={{ position: 'relative', width: 72, height: 72, flexShrink: 0 }}>
            <svg width="72" height="72" viewBox="0 0 72 72">
              {/* Background ring */}
              <circle
                cx="36" cy="36" r="30"
                fill="none"
                stroke="var(--border)"
                strokeWidth="5"
              />
              {/* Beat rate arc */}
              <circle
                cx="36" cy="36" r="30"
                fill="none"
                stroke={beatPct >= 70 ? 'var(--positive)' : beatPct >= 40 ? 'var(--gold)' : 'var(--negative)'}
                strokeWidth="5"
                strokeLinecap="round"
                strokeDasharray={`${beatPct * 1.885} 188.5`}
                transform="rotate(-90 36 36)"
                style={{ transition: 'stroke-dasharray 0.6s ease' }}
              />
            </svg>
            <div style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              fontSize: '1.1rem',
              color: 'var(--text-primary)',
            }}>
              {beatPct}%
            </div>
          </div>
          <div>
            <div style={{
              fontSize: '0.78rem',
              fontWeight: 600,
              color: 'var(--text-secondary)',
              marginBottom: '2px',
            }}>
              EPS Beat Rate
            </div>
            <div style={{
              fontSize: '0.75rem',
              color: 'var(--text-muted)',
              lineHeight: 1.4,
            }}>
              {result.consecutive_beats > 0
                ? `${result.consecutive_beats} consecutive beat${result.consecutive_beats > 1 ? 's' : ''} (current streak)`
                : 'No active beat streak'}
            </div>
          </div>
        </div>

        {/* Aggregate stats */}
        <div className="valuation-metrics">
          <div>
            <div className="metric-label">Avg EPS Surprise</div>
            <div className="metric-value" style={{
              color: result.avg_eps_surprise_pct >= 0 ? 'var(--positive)' : 'var(--negative)',
            }}>
              {fmtPct(result.avg_eps_surprise_pct)}
            </div>
          </div>
          <div>
            <div className="metric-label">Avg Revenue Surprise</div>
            <div className="metric-value" style={{
              color: result.avg_revenue_surprise_pct >= 0 ? 'var(--positive)' : 'var(--negative)',
            }}>
              {fmtPct(result.avg_revenue_surprise_pct)}
            </div>
          </div>
          <div>
            <div className="metric-label">Consecutive Beats</div>
            <div className="metric-value">
              {result.consecutive_beats}
            </div>
          </div>
        </div>
      </div>

      {/* Quarterly Surprises Table */}
      {result.surprises.length > 0 && (
        <div className="card animate-in">
          <div className="card-header">
            <span className="card-title">Quarterly Earnings History</span>
            <span className="card-badge">{result.surprises.length} quarters</span>
          </div>
          <div className="card-body" style={{ padding: 0, overflowX: 'auto' }}>
            <table className="fin-table" style={{ minWidth: 640 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Quarter', 'EPS Act.', 'EPS Est.', 'Surprise', '', 'Rev Act.', 'Rev Est.', 'Surprise', ''].map(
                    (h, i) => (
                      <th
                        key={i}
                        style={{
                          padding: '8px 12px',
                          textAlign: i === 0 ? 'left' : 'right',
                          fontSize: '0.7rem',
                          fontWeight: 600,
                          textTransform: 'uppercase',
                          letterSpacing: '0.05em',
                          color: 'var(--text-muted)',
                          ...(i === 4 ? { textAlign: 'center', width: 60 } : {}),
                          ...(i === 8 ? { textAlign: 'center', width: 60 } : {}),
                        }}
                      >
                        {h}
                      </th>
                    )
                  )}
                </tr>
              </thead>
              <tbody>
                {result.surprises.map((s, i) => (
                  <tr key={i}>
                    <td style={{
                      padding: '8px 12px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.82rem',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                    }}>
                      {s.date}
                    </td>
                    <td className="fin-value" style={{ padding: '8px 12px' }}>{fmtEps(s.eps_actual)}</td>
                    <td className="fin-value" style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>{fmtEps(s.eps_estimated)}</td>
                    <td className="fin-value" style={{
                      padding: '8px 12px',
                      color: directionColor(s.eps_direction),
                      fontWeight: 600,
                    }}>
                      {fmtPct(s.eps_surprise_pct)}
                    </td>
                    <td style={{ padding: '8px 6px', textAlign: 'center' }}>
                      <span style={{
                        display: 'inline-block',
                        fontSize: '0.62rem',
                        fontWeight: 700,
                        letterSpacing: '0.06em',
                        padding: '2px 6px',
                        borderRadius: 'var(--r-sm)',
                        color: directionColor(s.eps_direction),
                        background: directionBg(s.eps_direction),
                      }}>
                        {directionLabel(s.eps_direction)}
                      </span>
                    </td>
                    <td className="fin-value" style={{ padding: '8px 12px' }}>{fmtRevenue(s.revenue_actual)}</td>
                    <td className="fin-value" style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>{fmtRevenue(s.revenue_estimated)}</td>
                    <td className="fin-value" style={{
                      padding: '8px 12px',
                      color: directionColor(s.revenue_direction),
                      fontWeight: 600,
                    }}>
                      {fmtPct(s.revenue_surprise_pct)}
                    </td>
                    <td style={{ padding: '8px 6px', textAlign: 'center' }}>
                      <span style={{
                        display: 'inline-block',
                        fontSize: '0.62rem',
                        fontWeight: 700,
                        letterSpacing: '0.06em',
                        padding: '2px 6px',
                        borderRadius: 'var(--r-sm)',
                        color: directionColor(s.revenue_direction),
                        background: directionBg(s.revenue_direction),
                      }}>
                        {directionLabel(s.revenue_direction)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* New Analysis button */}
      <div className="export-bar animate-in">
        <div style={{ flex: 1 }} />
        <button className="btn btn-primary" onClick={() => useAppStore.getState().reset()}>
          <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M7 1v12M1 7h12" />
          </svg>
          New Analysis
        </button>
      </div>
    </>
  )
}
