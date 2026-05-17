import { useCountUp } from '../hooks/useCountUp'
import type { EarningsResult } from '../stores/appStore'
import { useAppStore } from '../stores/appStore'
import { fmtUsd, fmtEps } from '../utils/formatters'
import EpsSurpriseChart from './charts/EpsSurpriseChart'

interface Props {
  result: EarningsResult
}

/** Signed percentage for surprise display (already in 0-100 range). */
function fmtSurprisePct(val: number): string {
  return `${val >= 0 ? '+' : ''}${val.toFixed(1)}%`
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
  const animatedBeatPct = useCountUp(beatPct, 700, 0)
  const animatedEpsSurprise = useCountUp(result.avg_eps_surprise_pct, 700, 1)
  const animatedRevSurprise = useCountUp(result.avg_revenue_surprise_pct, 700, 1)

  return (
    <>
      {/* Hero — Earnings Quality Scorecard */}
      <div className="valuation-hero animate-in">
        <div className="hero-header hero-header--lg">
          <div>
            <div className="valuation-label">Earnings Analysis</div>
            <div className="hero-ticker">{result.ticker}</div>
          </div>
          <div className="text-right">
            <div className="valuation-label">Quarters Analyzed</div>
            <div className="hero-stat">{result.surprises.length}</div>
          </div>
        </div>

        {/* Beat Rate — hero metric */}
        <div className="metrics-row metrics-row--sm">
          {/* Circular beat rate indicator */}
          <div style={{ position: 'relative', width: 72, height: 72, flexShrink: 0 }}>
            <svg width="72" height="72" viewBox="0 0 72 72">
              <circle
                cx="36" cy="36" r="30"
                fill="none"
                stroke="var(--border)"
                strokeWidth="5"
              />
              <circle
                cx="36" cy="36" r="30"
                fill="none"
                stroke={beatPct >= 70 ? 'var(--positive)' : beatPct >= 40 ? 'var(--accent)' : 'var(--negative)'}
                strokeWidth="5"
                strokeLinecap="round"
                strokeDasharray={`${beatPct * 1.885} 188.5`}
                transform="rotate(-90 36 36)"
                style={{ transition: 'stroke-dasharray 0.6s ease' }}
              />
            </svg>
            <div className="circle-overlay">{Math.round(animatedBeatPct)}%</div>
          </div>
          <div>
            <div className="beat-caption">EPS Beat Rate</div>
            <div className="beat-detail">
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
              {animatedEpsSurprise >= 0 ? '+' : ''}{animatedEpsSurprise.toFixed(1)}%
            </div>
          </div>
          <div>
            <div className="metric-label">Avg Revenue Surprise</div>
            <div className="metric-value" style={{
              color: result.avg_revenue_surprise_pct >= 0 ? 'var(--positive)' : 'var(--negative)',
            }}>
              {animatedRevSurprise >= 0 ? '+' : ''}{animatedRevSurprise.toFixed(1)}%
            </div>
          </div>
          <div>
            <div className="metric-label">Consecutive Beats</div>
            <div className="metric-value">{result.consecutive_beats}</div>
          </div>
        </div>
      </div>

      {/* EPS Surprise Chart */}
      {result.surprises.length > 1 && (
        <EpsSurpriseChart
          data={result.surprises.slice().reverse().map((s) => ({
            quarter: s.date,
            eps_actual: s.eps_actual,
            eps_estimated: s.eps_estimated,
            surprise_pct: s.eps_surprise_pct,
            direction: s.eps_direction,
          }))}
          title="EPS: Actual vs Consensus"
        />
      )}

      {/* Quarterly Surprises Table */}
      {result.surprises.length > 0 && (
        <div className="card animate-in">
          <div className="card-header">
            <span className="card-title">季度业绩历史</span>
            <span className="card-badge">{result.surprises.length} 个季度</span>
          </div>
          <div className="card-body" style={{ padding: 0, overflowX: 'auto' }}>
            <table className="fin-table" style={{ minWidth: 640 }}>
              <thead>
                <tr>
                  <th>季度</th>
                  <th>EPS 实际</th>
                  <th>EPS 预期</th>
                  <th>差值</th>
                  <th style={{ textAlign: 'center', width: 60 }}></th>
                  <th>营收实际</th>
                  <th>营收预期</th>
                  <th>差值</th>
                  <th style={{ textAlign: 'center', width: 60 }}></th>
                </tr>
              </thead>
              <tbody>
                {result.surprises.map((s, i) => (
                  <tr key={i} className={s.eps_direction === 'beat' ? 'row-beat' : s.eps_direction === 'miss' ? 'row-miss' : ''}>
                    <td className="cell-mono">{s.date}</td>
                    <td className="fin-value cell">{fmtEps(s.eps_actual)}</td>
                    <td className="fin-value cell" style={{ color: 'var(--text-muted)' }}>{fmtEps(s.eps_estimated)}</td>
                    <td className="fin-value cell" style={{
                      color: directionColor(s.eps_direction),
                      fontWeight: 600,
                    }}>
                      {fmtSurprisePct(s.eps_surprise_pct)}
                    </td>
                    <td className="text-center cell">
                      <span
                        className="status-badge status-badge--sm"
                        style={{ color: directionColor(s.eps_direction), background: directionBg(s.eps_direction) }}
                      >
                        {directionLabel(s.eps_direction)}
                      </span>
                    </td>
                    <td className="fin-value cell">{fmtUsd(s.revenue_actual)}</td>
                    <td className="fin-value cell" style={{ color: 'var(--text-muted)' }}>{fmtUsd(s.revenue_estimated)}</td>
                    <td className="fin-value cell" style={{
                      color: directionColor(s.revenue_direction),
                      fontWeight: 600,
                    }}>
                      {fmtSurprisePct(s.revenue_surprise_pct)}
                    </td>
                    <td className="text-center cell">
                      <span
                        className="status-badge status-badge--sm"
                        style={{ color: directionColor(s.revenue_direction), background: directionBg(s.revenue_direction) }}
                      >
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
        <div className="flex-1" />
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
