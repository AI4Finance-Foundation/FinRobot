import { useCallback } from 'react'
import { useCountUp } from '../hooks/useCountUp'
import type { CompsResult } from '../stores/appStore'
import { useAppStore } from '../stores/appStore'
import { BASE_URL } from '../api/client'
import { fmtUsd, fmtMult } from '../utils/formatters'

interface Props {
  result: CompsResult
  currentPrice: number | null
}

export default function CompsSummary({ result, currentPrice }: Props) {
  const ticker = useAppStore((s) => s.ticker)
  const animatedEvEbitda = useCountUp(result.median_ev_ebitda ?? 0, 700, 1)
  const animatedPe = useCountUp(result.median_pe ?? 0, 700, 1)
  const animatedEvRev = useCountUp(result.median_ev_revenue ?? 0, 700, 1)

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
    const resp = await fetch(`${BASE_URL}/api/export/excel/comps/${ticker}`)
    if (!resp.ok) return
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${ticker}_comps.xlsx`
    a.click()
    URL.revokeObjectURL(url)
  }, [ticker])

  return (
    <>
      {/* Target + Median Stats */}
      <div className="valuation-hero animate-in">
        <div className="hero-header">
          <div>
            <div className="valuation-label">Comparable Company Analysis</div>
            <div className="hero-ticker">{t.ticker}</div>
            {t.name && <div className="hero-sub">{t.name}</div>}
          </div>
          <div className="text-right">
            <div className="valuation-label">Peer Set</div>
            <div className="hero-stat">{result.peers.length} companies</div>
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
                    <span className="implied-value">${ip.price.toFixed(2)}</span>
                    <span className="implied-method">via {ip.method}</span>
                    {upside !== null && (
                      <span
                        className="implied-delta"
                        style={{ color: upside >= 0 ? 'var(--positive)' : 'var(--negative)' }}
                      >
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
            <div className="metric-value">{result.median_ev_ebitda != null ? `${animatedEvEbitda.toFixed(1)}x` : '\u2014'}</div>
          </div>
          <div>
            <div className="metric-label">Median P/E</div>
            <div className="metric-value">{result.median_pe != null ? `${animatedPe.toFixed(1)}x` : '\u2014'}</div>
          </div>
          <div>
            <div className="metric-label">Median EV/Rev</div>
            <div className="metric-value">{result.median_ev_revenue != null ? `${animatedEvRev.toFixed(1)}x` : '\u2014'}</div>
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
              <tr>
                <th>Ticker</th>
                <th>Market Cap</th>
                <th>EV/EBITDA</th>
                <th>P/E</th>
                <th>EV/Rev</th>
              </tr>
            </thead>
            <tbody>
              {[t, ...result.peers].map((c) => {
                const isTarget = c.ticker === t.ticker
                return (
                  <tr key={c.ticker} className={isTarget ? 'row-target' : undefined}>
                    <td className="cell-first">
                      <span className="font-mono" style={{
                        fontWeight: 700,
                        fontSize: '0.82rem',
                        color: isTarget ? 'var(--gold)' : 'var(--text-primary)',
                        letterSpacing: '0.03em',
                      }}>
                        {c.ticker}
                      </span>
                      {c.name && (
                        <span className="implied-method">{c.name}</span>
                      )}
                    </td>
                    <td className="fin-value cell">{fmtUsd(c.market_cap)}</td>
                    <td className="fin-value cell">{fmtMult(c.ev_ebitda)}</td>
                    <td className="fin-value cell">{fmtMult(c.pe_ratio)}</td>
                    <td className="fin-value cell-first">{fmtMult(c.ev_revenue)}</td>
                  </tr>
                )
              })}
              {/* Median row */}
              <tr className="row-border-top">
                <td className="row-label">Peer Median</td>
                <td className="fin-value cell">{'\u2014'}</td>
                <td className="fin-value cell" style={{ color: 'var(--gold)' }}>{fmtMult(result.median_ev_ebitda)}</td>
                <td className="fin-value cell" style={{ color: 'var(--gold)' }}>{fmtMult(result.median_pe)}</td>
                <td className="fin-value cell-first" style={{ color: 'var(--gold)' }}>{fmtMult(result.median_ev_revenue)}</td>
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
            <p className="body-text">{result.peer_justification}</p>
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
