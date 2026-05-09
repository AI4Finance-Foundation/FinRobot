import { useCallback } from 'react'
import type { CompsResult } from '../stores/appStore'
import { useAppStore } from '../stores/appStore'
import { BASE_URL } from '../api/client'

interface Props {
  result: CompsResult
  currentPrice: number | null
}

function fmtUsd(val: number | null | undefined): string {
  if (val == null) return '\u2014'
  const abs = Math.abs(val)
  if (abs >= 1e12) return `$${(val / 1e12).toFixed(1)}T`
  if (abs >= 1e9) return `$${(val / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `$${(val / 1e6).toFixed(1)}M`
  return `$${val.toFixed(0)}`
}

function fmtMult(val: number | null | undefined): string {
  if (val == null) return '\u2014'
  return `${val.toFixed(1)}x`
}

export default function CompsSummary({ result, currentPrice }: Props) {
  const ticker = useAppStore((s) => s.ticker)

  // Compute implied price range from peer median multiples
  const impliedPrices: { method: string; price: number }[] = []
  const t = result.target
  const sharesOut = t.market_cap && currentPrice && currentPrice > 0
    ? t.market_cap / currentPrice
    : null

  if (result.median_ev_ebitda != null && t.ebitda > 0 && sharesOut) {
    const impliedEV = result.median_ev_ebitda * t.ebitda
    const netDebt = t.total_debt - t.total_cash
    const impliedEquity = impliedEV - netDebt
    const price = impliedEquity / sharesOut
    if (price > 0) impliedPrices.push({ method: 'EV/EBITDA', price })
  }
  if (result.median_pe != null && t.net_income > 0 && sharesOut) {
    const eps = t.net_income / sharesOut
    const price = result.median_pe * eps
    if (price > 0) impliedPrices.push({ method: 'P/E', price })
  }

  const handleExcelExport = useCallback(async () => {
    const resp = await fetch(`${BASE_URL}/api/export/excel/dcf`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, comps: result }),
    })
    if (!resp.ok) return
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${ticker}_comps.xlsx`
    a.click()
    URL.revokeObjectURL(url)
  }, [ticker, result])

  return (
    <>
      {/* Target + Median Stats */}
      <div className="valuation-hero animate-in">
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 'var(--sp-4)' }}>
          <div>
            <div className="valuation-label">Comparable Company Analysis</div>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              fontSize: '1.4rem',
              color: 'var(--gold)',
              letterSpacing: '0.03em',
            }}>
              {t.ticker}
            </div>
            {t.name && (
              <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                {t.name}
              </div>
            )}
          </div>
          <div style={{ textAlign: 'right' }}>
            <div className="valuation-label">Peer Set</div>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
              fontSize: '1.1rem',
              color: 'var(--text-primary)',
            }}>
              {result.peers.length} companies
            </div>
          </div>
        </div>

        {/* Implied price range */}
        {impliedPrices.length > 0 && (
          <div style={{ marginBottom: 'var(--sp-4)' }}>
            <div className="section-label">Implied Price (Peer Median)</div>
            <div style={{ display: 'flex', gap: 'var(--sp-5)' }}>
              {impliedPrices.map((ip) => {
                const upside = currentPrice && currentPrice > 0
                  ? ((ip.price - currentPrice) / currentPrice) * 100
                  : null
                return (
                  <div key={ip.method}>
                    <span style={{
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 700,
                      fontSize: '1.4rem',
                      color: 'var(--text-primary)',
                    }}>
                      ${ip.price.toFixed(2)}
                    </span>
                    <span style={{
                      fontSize: '0.72rem',
                      color: 'var(--text-muted)',
                      marginLeft: 'var(--sp-2)',
                    }}>
                      via {ip.method}
                    </span>
                    {upside !== null && (
                      <span style={{
                        marginLeft: 'var(--sp-2)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '0.78rem',
                        fontWeight: 600,
                        color: upside >= 0 ? 'var(--positive)' : 'var(--negative)',
                      }}>
                        {upside >= 0 ? '+' : ''}{upside.toFixed(1)}%
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Median stats */}
        <div className="valuation-metrics">
          <div>
            <div className="metric-label">Median EV/EBITDA</div>
            <div className="metric-value">{fmtMult(result.median_ev_ebitda)}</div>
          </div>
          <div>
            <div className="metric-label">Median P/E</div>
            <div className="metric-value">{fmtMult(result.median_pe)}</div>
          </div>
          <div>
            <div className="metric-label">Median EV/Rev</div>
            <div className="metric-value">{fmtMult(result.median_ev_revenue)}</div>
          </div>
        </div>
      </div>

      {/* Peer Table */}
      <div className="card animate-in">
        <div className="card-header">
          <span className="card-title">Peer Comparison</span>
          <span className="card-badge">{result.peers.length + 1} companies</span>
        </div>
        <div className="card-body" style={{ padding: 0, overflowX: 'auto' }}>
          <table className="fin-table" style={{ minWidth: 560 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <th style={{ padding: '8px 16px', textAlign: 'left', fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)' }}>Ticker</th>
                <th style={{ padding: '8px 12px', textAlign: 'right', fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)' }}>Market Cap</th>
                <th style={{ padding: '8px 12px', textAlign: 'right', fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)' }}>EV/EBITDA</th>
                <th style={{ padding: '8px 12px', textAlign: 'right', fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)' }}>P/E</th>
                <th style={{ padding: '8px 16px', textAlign: 'right', fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)' }}>EV/Rev</th>
              </tr>
            </thead>
            <tbody>
              {[t, ...result.peers].map((c) => {
                const isTarget = c.ticker === t.ticker
                return (
                  <tr key={c.ticker} style={isTarget ? { background: 'var(--gold-dim)' } : undefined}>
                    <td style={{ padding: '8px 16px' }}>
                      <span style={{
                        fontFamily: 'var(--font-mono)',
                        fontWeight: 700,
                        fontSize: '0.82rem',
                        color: isTarget ? 'var(--gold)' : 'var(--text-primary)',
                        letterSpacing: '0.03em',
                      }}>
                        {c.ticker}
                      </span>
                      {c.name && (
                        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginLeft: 'var(--sp-2)' }}>
                          {c.name}
                        </span>
                      )}
                    </td>
                    <td className="fin-value" style={{ padding: '8px 12px' }}>{fmtUsd(c.market_cap)}</td>
                    <td className="fin-value" style={{ padding: '8px 12px' }}>{fmtMult(c.ev_ebitda)}</td>
                    <td className="fin-value" style={{ padding: '8px 12px' }}>{fmtMult(c.pe_ratio)}</td>
                    <td className="fin-value" style={{ padding: '8px 16px' }}>{fmtMult(c.ev_revenue)}</td>
                  </tr>
                )
              })}
              {/* Median row */}
              <tr style={{ borderTop: '1px solid var(--border)' }}>
                <td style={{ padding: '8px 16px', fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                  Peer Median
                </td>
                <td className="fin-value" style={{ padding: '8px 12px' }}>{'\u2014'}</td>
                <td className="fin-value" style={{ padding: '8px 12px', color: 'var(--gold)' }}>{fmtMult(result.median_ev_ebitda)}</td>
                <td className="fin-value" style={{ padding: '8px 12px', color: 'var(--gold)' }}>{fmtMult(result.median_pe)}</td>
                <td className="fin-value" style={{ padding: '8px 16px', color: 'var(--gold)' }}>{fmtMult(result.median_ev_revenue)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Justification */}
      {result.peer_justification && (
        <div className="card animate-in">
          <div className="card-header">
            <span className="card-title">Peer Selection Rationale</span>
          </div>
          <div className="card-body">
            <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', lineHeight: 1.6, margin: 0 }}>
              {result.peer_justification}
            </p>
          </div>
        </div>
      )}

      {/* Export */}
      <div className="export-bar animate-in">
        <button className="btn" onClick={handleExcelExport}>
          <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 10v2h10v-2M7 2v7m-3-3l3 3 3-3" />
          </svg>
          Export Excel
        </button>
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
