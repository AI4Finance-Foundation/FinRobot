import { useCountUp } from '../hooks/useCountUp'
import type { LBOResult } from '../stores/appStore'
import { useAppStore } from '../stores/appStore'

interface Props {
  result: LBOResult
}

function fmtUsd(val: number): string {
  const abs = Math.abs(val)
  if (abs >= 1e12) return `$${(val / 1e12).toFixed(1)}T`
  if (abs >= 1e9) return `$${(val / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `$${(val / 1e6).toFixed(0)}M`
  return `$${val.toFixed(0)}`
}

function fmtPct(val: number): string {
  return `${(val * 100).toFixed(1)}%`
}

function fmtMult(val: number): string {
  return `${val.toFixed(1)}x`
}

function irrColor(irr: number): string {
  if (irr >= 0.25) return 'var(--positive)'
  if (irr >= 0.15) return 'var(--gold)'
  return 'var(--negative)'
}

function irrBg(irr: number): string {
  if (irr >= 0.25) return 'var(--positive-bg)'
  if (irr >= 0.15) return 'var(--gold-dim)'
  return 'var(--negative-bg)'
}

function irrLabel(irr: number): string {
  if (irr >= 0.25) return 'STRONG'
  if (irr >= 0.20) return 'ATTRACTIVE'
  if (irr >= 0.15) return 'MEETS HURDLE'
  return 'BELOW HURDLE'
}

export default function LBOSummary({ result }: Props) {
  const ticker = useAppStore((s) => s.ticker)
  const animatedIrr = useCountUp(result.irr * 100, 700, 1)
  const animatedMoic = useCountUp(result.moic, 700, 1)
  const debtToEquity = result.entry_equity > 0 ? result.entry_debt / result.entry_equity : 0

  const hasSensitivity = !!(
    result.sensitivity &&
    result.sensitivity.irr_grid?.length > 0 &&
    result.sensitivity.entry_multiples?.length > 0 &&
    result.sensitivity.exit_multiples?.length > 0
  )

  return (
    <>
      {/* Hero — IRR + MOIC headline */}
      <div className="valuation-hero animate-in">
        <div className="hero-header hero-header--lg">
          <div>
            <div className="valuation-label">Leveraged Buyout Analysis</div>
            <div className="hero-ticker">{ticker}</div>
          </div>
          <div className="text-right">
            <div className="valuation-label">Holding Period</div>
            <div className="hero-stat">{result.schedule.length} years</div>
          </div>
        </div>

        {/* IRR + MOIC — hero metrics */}
        <div className="metrics-row">
          <div className="metric-stack">
            <div className="big-number" style={{ color: irrColor(result.irr) }}>
              {animatedIrr.toFixed(1)}%
            </div>
            <div className="metric-sub">IRR</div>
          </div>

          <div className="v-divider" />

          <div className="metric-stack">
            <div className="big-number">{animatedMoic.toFixed(1)}x</div>
            <div className="metric-sub">MOIC</div>
          </div>

          <div className="flex-1" />

          <span
            className="status-badge"
            style={{ color: irrColor(result.irr), background: irrBg(result.irr) }}
          >
            {irrLabel(result.irr)}
          </span>
        </div>

        {/* Warning */}
        {result.irr_formula_warning && (
          <div className="inline-warning" style={{ color: 'var(--gold)', background: 'var(--gold-dim)' }}>
            {result.irr_formula_warning}
          </div>
        )}

        {/* Deal Structure metrics */}
        <div className="valuation-metrics">
          <div>
            <div className="metric-label">Entry EV</div>
            <div className="metric-value">{fmtUsd(result.entry_ev)}</div>
          </div>
          <div>
            <div className="metric-label">Entry Debt</div>
            <div className="metric-value">{fmtUsd(result.entry_debt)}</div>
          </div>
          <div>
            <div className="metric-label">Entry Equity</div>
            <div className="metric-value">{fmtUsd(result.entry_equity)}</div>
          </div>
          <div>
            <div className="metric-label">D/E Ratio</div>
            <div className="metric-value">{fmtMult(debtToEquity)}</div>
          </div>
        </div>
      </div>

      {/* Returns Bridge — Entry vs Exit */}
      <div className="card animate-in">
        <div className="card-header">
          <span className="card-title">Returns Bridge</span>
        </div>
        <div className="card-body" style={{ padding: 0, overflowX: 'auto' }}>
          <table className="fin-table" style={{ minWidth: 400 }}>
            <thead>
              <tr>
                <th>{ }</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Change</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="row-label">Enterprise Value</td>
                <td className="fin-value cell">{fmtUsd(result.entry_ev)}</td>
                <td className="fin-value cell">{fmtUsd(result.exit_ev)}</td>
                <td className="fin-value cell" style={{
                  color: result.exit_ev >= result.entry_ev ? 'var(--positive)' : 'var(--negative)',
                  fontWeight: 600,
                }}>
                  {result.entry_ev > 0 ? `${result.exit_ev >= result.entry_ev ? '+' : ''}${(((result.exit_ev - result.entry_ev) / result.entry_ev) * 100).toFixed(1)}%` : '\u2014'}
                </td>
              </tr>
              <tr>
                <td className="row-label">Equity Value</td>
                <td className="fin-value cell">{fmtUsd(result.entry_equity)}</td>
                <td className="fin-value cell">{fmtUsd(result.exit_equity)}</td>
                <td className="fin-value cell" style={{
                  color: result.exit_equity >= result.entry_equity ? 'var(--positive)' : 'var(--negative)',
                  fontWeight: 600,
                }}>
                  {result.entry_equity > 0 ? `${result.exit_equity >= result.entry_equity ? '+' : ''}${(((result.exit_equity - result.entry_equity) / result.entry_equity) * 100).toFixed(1)}%` : '\u2014'}
                </td>
              </tr>
              <tr className="row-border-top">
                <td className="row-label">EBITDA (Exit)</td>
                <td className="fin-value cell" style={{ color: 'var(--text-muted)' }}>{'\u2014'}</td>
                <td className="fin-value cell">{fmtUsd(result.exit_ebitda)}</td>
                <td className="fin-value cell" style={{ color: 'var(--text-muted)' }}>{'\u2014'}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Debt Schedule — Year-by-Year */}
      {result.schedule.length > 0 && (
        <div className="card animate-in">
          <div className="card-header">
            <span className="card-title">Debt Schedule</span>
            <span className="card-badge">{result.schedule.length} years</span>
          </div>
          <div className="card-body" style={{ padding: 0, overflowX: 'auto' }}>
            <table className="fin-table" style={{ minWidth: 580 }}>
              <thead>
                <tr>
                  <th>Year</th>
                  <th>Revenue</th>
                  <th>EBITDA</th>
                  <th>FCF</th>
                  <th>Debt Paydown</th>
                  <th>Ending Debt</th>
                </tr>
              </thead>
              <tbody>
                {result.schedule.map((yr) => (
                  <tr key={yr.year}>
                    <td className="cell-mono">Y{yr.year}</td>
                    <td className="fin-value cell">{fmtUsd(yr.revenue)}</td>
                    <td className="fin-value cell">{fmtUsd(yr.ebitda)}</td>
                    <td className="fin-value cell" style={{
                      color: yr.fcf >= 0 ? 'var(--positive)' : 'var(--negative)',
                    }}>
                      {fmtUsd(yr.fcf)}
                    </td>
                    <td className="fin-value cell">{fmtUsd(yr.total_debt_paydown)}</td>
                    <td className="fin-value cell">{fmtUsd(yr.ending_debt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* IRR Sensitivity — Entry × Exit Multiples */}
      {hasSensitivity && (
        <div className="card animate-in">
          <div className="card-header">
            <span className="card-title">IRR Sensitivity</span>
            <span className="card-badge">Entry × Exit Multiple</span>
          </div>
          <div className="card-body" style={{ padding: 0, overflowX: 'auto' }}>
            <table className="fin-table" style={{ minWidth: 420 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', fontSize: '0.68rem' }}>Entry ↓ / Exit →</th>
                  {result.sensitivity.exit_multiples.map((em) => (
                    <th key={em} className="cell-sens-header">{em.toFixed(1)}x</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.sensitivity.entry_multiples.map((entryMult, rowIdx) => (
                  <tr key={entryMult}>
                    <td className="cell-sens-header" style={{ textAlign: 'left', paddingLeft: 12 }}>
                      {entryMult.toFixed(1)}x
                    </td>
                    {result.sensitivity.irr_grid[rowIdx]?.map((irr, colIdx) => {
                      const val = irr ?? -1
                      return (
                        <td
                          key={colIdx}
                          className="cell-sens"
                          style={{ color: irrColor(val), background: irrBg(val) }}
                        >
                          {irr != null ? fmtPct(irr) : '\u2014'}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* New Analysis */}
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
