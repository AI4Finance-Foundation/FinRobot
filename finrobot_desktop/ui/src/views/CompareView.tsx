import { useCallback, useState } from 'react'
import { useAppStore } from '../stores/appStore'
import type { ComparisonResultData, CompanyValuation } from '../stores/appStore'
import { BASE_URL } from '../api/client'
import { fmtMult, fmtPrice } from '../utils/formatters'
import { TermTip, isKnownTerm } from '../components/TermTip'

export default function CompareView() {
  const comparisonResult = useAppStore((s) => s.comparisonResult)
  const comparisonLoading = useAppStore((s) => s.comparisonLoading)
  const setComparisonResult = useAppStore((s) => s.setComparisonResult)
  const setComparisonLoading = useAppStore((s) => s.setComparisonLoading)
  const currentTicker = useAppStore((s) => s.ticker)

  const [tickerInput, setTickerInput] = useState(currentTicker || '')
  const [error, setError] = useState<string | null>(null)

  const handleCompare = useCallback(async () => {
    const raw = tickerInput.trim()
    if (!raw) return
    // Split on commas, spaces, or both
    const tickers = raw
      .split(/[\s,]+/)
      .map((t) => t.toUpperCase().trim())
      .filter(Boolean)

    if (tickers.length < 2) {
      setError('Enter at least 2 tickers to compare.')
      return
    }
    if (tickers.length > 10) {
      setError('Maximum 10 tickers supported.')
      return
    }

    setError(null)
    setComparisonLoading(true)
    setComparisonResult(null)

    try {
      const resp = await fetch(`${BASE_URL}/api/compute/compare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tickers }),
      })
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        throw new Error(body.detail || `Server error ${resp.status}`)
      }
      const result: ComparisonResultData = await resp.json()
      setComparisonResult(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setComparisonLoading(false)
    }
  }, [tickerInput, setComparisonResult, setComparisonLoading])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') handleCompare()
    },
    [handleCompare]
  )

  return (
    <div className="tab-content compare-tab">
      {/* Input section */}
      <div className="card animate-in">
        <div className="card-header">
          <span className="card-title">Multi-Company Comparison</span>
          <span className="card-badge">DCF</span>
        </div>
        <div className="card-body">
          <div style={{ display: 'flex', gap: 'var(--sp-3)', alignItems: 'center' }}>
            <input
              type="text"
              className="ticker-field"
              placeholder="AAPL, MSFT, GOOGL"
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={comparisonLoading}
              style={{
                flex: 1,
                padding: 'var(--sp-2) var(--sp-3)',
                background: 'var(--surface-1)',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.85rem',
                letterSpacing: '0.04em',
              }}
            />
            <button
              className="btn btn-primary"
              onClick={handleCompare}
              disabled={comparisonLoading || !tickerInput.trim()}
              style={{ whiteSpace: 'nowrap' }}
            >
              {comparisonLoading ? 'Running...' : 'Compare'}
            </button>
          </div>
          <div style={{ marginTop: 'var(--sp-2)', fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
            Enter 2-10 tickers separated by commas or spaces. Runs DCF valuation for each company.
          </div>
          {error && (
            <div className="error-msg" style={{ marginTop: 'var(--sp-3)' }}>
              {error}
            </div>
          )}
        </div>
      </div>

      {/* Loading state */}
      {comparisonLoading && (
        <div className="card animate-in">
          <div className="card-body" style={{ textAlign: 'center', padding: 'var(--sp-6)' }}>
            <div style={{ color: 'var(--accent)', marginBottom: 'var(--sp-3)' }}>
              Running DCF pipelines...
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
              This may take 30-90 seconds depending on the number of tickers and model speed.
            </div>
          </div>
        </div>
      )}

      {/* Results */}
      {comparisonResult && !comparisonLoading && (
        <>
          {/* Summary cards */}
          <div className="compare-cards animate-in" style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${Math.min(comparisonResult.companies.length, 4)}, 1fr)`,
            gap: 'var(--sp-3)',
          }}>
            {comparisonResult.companies.map((c) => (
              <ValuationCard key={c.ticker} company={c} />
            ))}
          </div>

          {/* Comparison table */}
          <div className="card animate-in">
            <div className="card-header">
              <span className="card-title">Side-by-Side Comparison</span>
              <span className="card-badge">{comparisonResult.companies.length} companies</span>
            </div>
            <div className="card-body" style={{ padding: 0, overflowX: 'auto' }}>
              <table className="fin-table" style={{ minWidth: 700 }}>
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Price</th>
                    <th>DCF Implied</th>
                    <th>Upside</th>
                    <th>WACC</th>
                    <th>TGR</th>
                    <th>EV/EBITDA</th>
                    <th>P/E</th>
                  </tr>
                </thead>
                <tbody>
                  {comparisonResult.companies.map((c) => (
                    <ComparisonRow key={c.ticker} company={c} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Warnings per company */}
          {comparisonResult.companies.some((c) => c.warnings.length > 0 || c.error) && (
            <div className="card animate-in">
              <div className="card-header">
                <span className="card-title">Notes</span>
              </div>
              <div className="card-body">
                {comparisonResult.companies.map((c) => {
                  if (!c.warnings.length && !c.error) return null
                  return (
                    <div key={c.ticker} style={{ marginBottom: 'var(--sp-3)' }}>
                      <div style={{ fontWeight: 600, fontSize: '0.82rem', color: 'var(--accent)', marginBottom: 'var(--sp-1)' }}>
                        {c.ticker}
                      </div>
                      {c.error && (
                        <div style={{ color: 'var(--negative)', fontSize: '0.78rem' }}>
                          Error: {c.error}
                        </div>
                      )}
                      {c.warnings.map((w, i) => (
                        <div key={i} style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginLeft: 'var(--sp-3)' }}>
                          - {w}
                        </div>
                      ))}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </>
      )}

      {/* Empty state */}
      {!comparisonResult && !comparisonLoading && (
        <div className="empty-state-card animate-in">
          <p>Enter tickers above to compare valuations side-by-side.</p>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: 'var(--sp-2)' }}>
            Each company runs through the full DCF pipeline independently.
          </p>
        </div>
      )}
    </div>
  )
}


function ValuationCard({ company }: { company: CompanyValuation }) {
  const c = company
  const isPositive = c.upside_pct != null && c.upside_pct >= 0
  const hasError = !!c.error

  return (
    <div className="card" style={{
      opacity: hasError ? 0.6 : 1,
      borderColor: hasError ? 'var(--negative)' : undefined,
    }}>
      <div className="card-body" style={{ padding: 'var(--sp-4)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 'var(--sp-2)' }}>
          <div>
            <span className="font-mono" style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--accent)', letterSpacing: '0.04em' }}>
              {c.ticker}
            </span>
            {c.company_name && (
              <span style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginLeft: 'var(--sp-2)' }}>
                {c.company_name}
              </span>
            )}
          </div>
          <span
            className="source-badge source-calc"
            data-tooltip="DCF computed by FinAgent"
            style={{ fontSize: '0.6rem' }}
          >
            CALC
          </span>
        </div>

        {hasError ? (
          <div style={{ color: 'var(--negative)', fontSize: '0.78rem', marginTop: 'var(--sp-2)' }}>
            {c.error}
          </div>
        ) : (
          <>
            <div style={{ fontSize: '1.4rem', fontWeight: 700, fontFamily: 'var(--font-mono)', marginBottom: 'var(--sp-1)' }}>
              {fmtPrice(c.implied_price)}
            </div>

            {c.upside_pct != null && (
              <div style={{
                fontSize: '0.82rem',
                fontWeight: 600,
                color: isPositive ? 'var(--positive)' : 'var(--negative)',
                marginBottom: 'var(--sp-3)',
              }}>
                {isPositive ? '+' : ''}{c.upside_pct.toFixed(1)}%
                {c.current_price != null && (
                  <span style={{ fontWeight: 400, color: 'var(--text-tertiary)', marginLeft: 'var(--sp-2)' }}>
                    vs {fmtPrice(c.current_price)}
                  </span>
                )}
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--sp-2)' }}>
              <MiniMetric label="WACC" value={c.wacc != null ? `${(c.wacc * 100).toFixed(1)}%` : null} />
              <MiniMetric label="TGR" value={c.terminal_growth != null ? `${(c.terminal_growth * 100).toFixed(1)}%` : null} />
              <MiniMetric label="EV/EBITDA" value={c.ev_ebitda != null ? fmtMult(c.ev_ebitda) : null} />
              <MiniMetric label="P/E" value={c.pe_ratio != null ? fmtMult(c.pe_ratio) : null} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}


function MiniMetric({ label, value }: { label: string; value: string | null }) {
  // Auto-wrap known jargon terms with TermTip hover tooltips. Splits "EV/EBITDA"
  // so each token gets its own lookup.
  const renderLabel = (): React.ReactNode => {
    if (label.includes('/')) {
      const parts = label.split('/')
      return parts.map((p, i) => (
        <span key={i}>
          {i > 0 && '/'}
          {isKnownTerm(p) ? <TermTip term={p}>{p}</TermTip> : p}
        </span>
      ))
    }
    return isKnownTerm(label) ? <TermTip term={label}>{label}</TermTip> : label
  }

  return (
    <div>
      <div style={{ fontSize: '0.65rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        {renderLabel()}
      </div>
      <div className="font-mono" style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)' }}>
        {value ?? '\u2014'}
      </div>
    </div>
  )
}


function ComparisonRow({ company }: { company: CompanyValuation }) {
  const c = company
  const hasError = !!c.error
  const isPositive = c.upside_pct != null && c.upside_pct >= 0

  if (hasError) {
    return (
      <tr style={{ opacity: 0.5 }}>
        <td className="cell-first">
          <span className="font-mono" style={{ fontWeight: 700, fontSize: '0.82rem', color: 'var(--negative)' }}>
            {c.ticker}
          </span>
        </td>
        <td colSpan={7} className="fin-value cell" style={{ color: 'var(--negative)', fontSize: '0.78rem' }}>
          {c.error}
        </td>
      </tr>
    )
  }

  return (
    <tr>
      <td className="cell-first">
        <span className="font-mono" style={{ fontWeight: 700, fontSize: '0.82rem', color: 'var(--accent)', letterSpacing: '0.03em' }}>
          {c.ticker}
        </span>
        {c.company_name && (
          <span className="implied-method">{c.company_name}</span>
        )}
      </td>
      <td className="fin-value cell">{fmtPrice(c.current_price)}</td>
      <td className="fin-value cell" style={{ fontWeight: 600 }}>{fmtPrice(c.implied_price)}</td>
      <td className="fin-value cell" style={{ color: isPositive ? 'var(--positive)' : 'var(--negative)', fontWeight: 600 }}>
        {c.upside_pct != null ? `${c.upside_pct >= 0 ? '+' : ''}${c.upside_pct.toFixed(1)}%` : '\u2014'}
      </td>
      <td className="fin-value cell">{c.wacc != null ? `${(c.wacc * 100).toFixed(1)}%` : '\u2014'}</td>
      <td className="fin-value cell">{c.terminal_growth != null ? `${(c.terminal_growth * 100).toFixed(1)}%` : '\u2014'}</td>
      <td className="fin-value cell">{fmtMult(c.ev_ebitda)}</td>
      <td className="fin-value cell">{fmtMult(c.pe_ratio)}</td>
    </tr>
  )
}
