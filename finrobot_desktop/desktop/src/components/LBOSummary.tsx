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
  const leverageRatio = result.entry_debt / (result.entry_ev - result.entry_debt + result.entry_equity)
  const debtToEquity = result.entry_equity > 0 ? result.entry_debt / result.entry_equity : 0

  const hasSensitivity =
    result.sensitivity?.irr_grid?.length > 0 &&
    result.sensitivity?.entry_multiples?.length > 0 &&
    result.sensitivity?.exit_multiples?.length > 0

  return (
    <>
      {/* Hero — IRR + MOIC headline */}
      <div className="valuation-hero animate-in">
        <div style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          marginBottom: 'var(--sp-5)',
        }}>
          <div>
            <div className="valuation-label">Leveraged Buyout Analysis</div>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              fontSize: '1.4rem',
              color: 'var(--gold)',
              letterSpacing: '0.03em',
            }}>
              {ticker}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div className="valuation-label">Holding Period</div>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
              fontSize: '1.1rem',
              color: 'var(--text-primary)',
            }}>
              {result.schedule.length} years
            </div>
          </div>
        </div>

        {/* IRR + MOIC — hero metrics */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--sp-6)',
          marginBottom: 'var(--sp-5)',
        }}>
          {/* IRR pill */}
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 'var(--sp-1)',
          }}>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              fontSize: '2rem',
              color: irrColor(result.irr),
              lineHeight: 1,
            }}>
              {fmtPct(result.irr)}
            </div>
            <div style={{
              fontSize: '0.72rem',
              fontWeight: 600,
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
            }}>
              IRR
            </div>
          </div>

          {/* Divider */}
          <div style={{
            width: 1,
            height: 40,
            background: 'var(--border)',
          }} />

          {/* MOIC */}
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 'var(--sp-1)',
          }}>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              fontSize: '2rem',
              color: 'var(--text-primary)',
              lineHeight: 1,
            }}>
              {fmtMult(result.moic)}
            </div>
            <div style={{
              fontSize: '0.72rem',
              fontWeight: 600,
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
            }}>
              MOIC
            </div>
          </div>

          <div style={{ flex: 1 }} />

          {/* Rating badge */}
          <span style={{
            display: 'inline-block',
            fontSize: '0.68rem',
            fontWeight: 700,
            letterSpacing: '0.06em',
            padding: '4px 10px',
            borderRadius: 'var(--r-sm)',
            color: irrColor(result.irr),
            background: irrBg(result.irr),
          }}>
            {irrLabel(result.irr)}
          </span>
        </div>

        {/* Warning */}
        {result.irr_formula_warning && (
          <div style={{
            fontSize: '0.72rem',
            color: 'var(--gold)',
            marginBottom: 'var(--sp-4)',
            padding: '6px 10px',
            background: 'var(--gold-dim)',
            borderRadius: 'var(--r-sm)',
          }}>
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
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['', 'Entry', 'Exit', 'Change'].map((h, i) => (
                  <th key={i} style={{
                    padding: '8px 16px',
                    textAlign: i === 0 ? 'left' : 'right',
                    fontSize: '0.7rem',
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                    color: 'var(--text-muted)',
                  }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={{ padding: '8px 16px', fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                  Enterprise Value
                </td>
                <td className="fin-value" style={{ padding: '8px 16px' }}>{fmtUsd(result.entry_ev)}</td>
                <td className="fin-value" style={{ padding: '8px 16px' }}>{fmtUsd(result.exit_ev)}</td>
                <td className="fin-value" style={{
                  padding: '8px 16px',
                  color: result.exit_ev >= result.entry_ev ? 'var(--positive)' : 'var(--negative)',
                  fontWeight: 600,
                }}>
                  {result.entry_ev > 0 ? `${result.exit_ev >= result.entry_ev ? '+' : ''}${(((result.exit_ev - result.entry_ev) / result.entry_ev) * 100).toFixed(1)}%` : '\u2014'}
                </td>
              </tr>
              <tr>
                <td style={{ padding: '8px 16px', fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                  Equity Value
                </td>
                <td className="fin-value" style={{ padding: '8px 16px' }}>{fmtUsd(result.entry_equity)}</td>
                <td className="fin-value" style={{ padding: '8px 16px' }}>{fmtUsd(result.exit_equity)}</td>
                <td className="fin-value" style={{
                  padding: '8px 16px',
                  color: result.exit_equity >= result.entry_equity ? 'var(--positive)' : 'var(--negative)',
                  fontWeight: 600,
                }}>
                  {result.entry_equity > 0 ? `${result.exit_equity >= result.entry_equity ? '+' : ''}${(((result.exit_equity - result.entry_equity) / result.entry_equity) * 100).toFixed(1)}%` : '\u2014'}
                </td>
              </tr>
              <tr style={{ borderTop: '1px solid var(--border)' }}>
                <td style={{ padding: '8px 16px', fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                  EBITDA (Exit)
                </td>
                <td className="fin-value" style={{ padding: '8px 16px', color: 'var(--text-muted)' }}>{'\u2014'}</td>
                <td className="fin-value" style={{ padding: '8px 16px' }}>{fmtUsd(result.exit_ebitda)}</td>
                <td className="fin-value" style={{ padding: '8px 16px', color: 'var(--text-muted)' }}>{'\u2014'}</td>
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
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Year', 'Revenue', 'EBITDA', 'FCF', 'Debt Paydown', 'Ending Debt'].map((h, i) => (
                    <th key={i} style={{
                      padding: '8px 12px',
                      textAlign: i === 0 ? 'left' : 'right',
                      fontSize: '0.7rem',
                      fontWeight: 600,
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                      color: 'var(--text-muted)',
                    }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.schedule.map((yr) => (
                  <tr key={yr.year}>
                    <td style={{
                      padding: '8px 12px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.82rem',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                    }}>
                      Y{yr.year}
                    </td>
                    <td className="fin-value" style={{ padding: '8px 12px' }}>{fmtUsd(yr.revenue)}</td>
                    <td className="fin-value" style={{ padding: '8px 12px' }}>{fmtUsd(yr.ebitda)}</td>
                    <td className="fin-value" style={{
                      padding: '8px 12px',
                      color: yr.fcf >= 0 ? 'var(--positive)' : 'var(--negative)',
                    }}>
                      {fmtUsd(yr.fcf)}
                    </td>
                    <td className="fin-value" style={{ padding: '8px 12px' }}>{fmtUsd(yr.total_debt_paydown)}</td>
                    <td className="fin-value" style={{ padding: '8px 12px' }}>{fmtUsd(yr.ending_debt)}</td>
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
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  <th style={{
                    padding: '8px 12px',
                    textAlign: 'left',
                    fontSize: '0.68rem',
                    fontWeight: 600,
                    color: 'var(--text-muted)',
                  }}>
                    Entry ↓ / Exit →
                  </th>
                  {result.sensitivity.exit_multiples.map((em) => (
                    <th key={em} style={{
                      padding: '8px 8px',
                      textAlign: 'center',
                      fontSize: '0.72rem',
                      fontWeight: 600,
                      fontFamily: 'var(--font-mono)',
                      color: 'var(--text-secondary)',
                    }}>
                      {em.toFixed(1)}x
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.sensitivity.entry_multiples.map((entryMult, rowIdx) => (
                  <tr key={entryMult}>
                    <td style={{
                      padding: '8px 12px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.72rem',
                      fontWeight: 600,
                      color: 'var(--text-secondary)',
                    }}>
                      {entryMult.toFixed(1)}x
                    </td>
                    {result.sensitivity.irr_grid[rowIdx]?.map((irr, colIdx) => {
                      const val = irr ?? -1
                      return (
                        <td key={colIdx} style={{
                          padding: '6px 8px',
                          textAlign: 'center',
                          fontFamily: 'var(--font-mono)',
                          fontSize: '0.72rem',
                          fontWeight: 600,
                          color: irrColor(val),
                          background: irrBg(val),
                        }}>
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
