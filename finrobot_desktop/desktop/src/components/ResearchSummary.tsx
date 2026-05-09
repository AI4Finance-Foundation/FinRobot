import { useCallback } from 'react'
import type { ResearchResult } from '../stores/appStore'
import { useAppStore } from '../stores/appStore'
import { BASE_URL } from '../api/client'

interface Props {
  result: ResearchResult
  currentPrice: number | null
}

const RATING_STYLES: Record<string, { color: string; bg: string }> = {
  buy:  { color: 'var(--positive)', bg: 'var(--positive-bg)' },
  hold: { color: 'var(--warning)',  bg: 'rgba(251, 191, 36, 0.10)' },
  sell: { color: 'var(--negative)', bg: 'var(--negative-bg)' },
}

function getRatingStyle(recommendation: string) {
  const key = recommendation.toLowerCase().trim()
  return RATING_STYLES[key] || RATING_STYLES.hold
}

export default function ResearchSummary({ result, currentPrice }: Props) {
  const ticker = useAppStore((s) => s.ticker)

  const upside =
    currentPrice && currentPrice > 0
      ? ((result.price_target - currentPrice) / currentPrice) * 100
      : null
  const isPositive = upside !== null && upside >= 0

  const ratingStyle = getRatingStyle(result.recommendation)

  const handleViewReport = useCallback(() => {
    window.open(`${BASE_URL}/api/report/html?ticker=${ticker}`, '_blank')
  }, [ticker])

  const handleExportPdf = useCallback(async () => {
    const resp = await fetch(`${BASE_URL}/api/report/pdf?ticker=${ticker}`)
    if (!resp.ok) return
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${ticker}_research_report.pdf`
    a.click()
    URL.revokeObjectURL(url)
  }, [ticker])

  return (
    <div className="valuation-hero animate-in">
      {/* Rating + Price Target */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 'var(--sp-4)' }}>
        <div>
          <div className="valuation-label">Investment Rating</div>
          <div style={{
            display: 'inline-block',
            padding: '4px 16px',
            borderRadius: 'var(--r-sm)',
            background: ratingStyle.bg,
            color: ratingStyle.color,
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            fontSize: '1.2rem',
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
          }}>
            {result.recommendation}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="valuation-label">Price Target</div>
          <div className="valuation-price" style={{ fontSize: '2.2rem' }}>
            <span className="currency">$</span>
            {result.price_target.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Upside/Downside */}
      {upside !== null && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-3)', marginBottom: 'var(--sp-5)' }}>
          <div className={`valuation-upside ${isPositive ? 'positive' : 'negative'}`}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
              {isPositive ? <path d="M6 2v8M3 5l3-3 3 3" /> : <path d="M6 10V2M3 7l3 3 3-3" />}
            </svg>
            {isPositive ? '+' : ''}{upside.toFixed(1)}% vs ${currentPrice!.toFixed(2)}
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            {result.price_target_basis}
          </span>
        </div>
      )}

      {/* Key Metrics */}
      <div className="valuation-metrics" style={{ gridTemplateColumns: '1fr 1fr' }}>
        {/* Catalysts */}
        <div>
          <div className="metric-label">Key Catalysts</div>
          <ul style={{
            listStyle: 'none',
            padding: 0,
            margin: 0,
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
            marginTop: '4px',
          }}>
            {result.catalysts.slice(0, 4).map((c, i) => (
              <li key={i} style={{
                fontSize: '0.78rem',
                color: 'var(--text-secondary)',
                display: 'flex',
                alignItems: 'flex-start',
                gap: 'var(--sp-2)',
              }}>
                <span style={{ color: 'var(--positive)', flexShrink: 0, marginTop: '2px' }}>+</span>
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Risks */}
        <div>
          <div className="metric-label">Key Risks</div>
          <ul style={{
            listStyle: 'none',
            padding: 0,
            margin: 0,
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
            marginTop: '4px',
          }}>
            {result.risks.slice(0, 4).map((r, i) => (
              <li key={i} style={{
                fontSize: '0.78rem',
                color: 'var(--text-secondary)',
                display: 'flex',
                alignItems: 'flex-start',
                gap: 'var(--sp-2)',
              }}>
                <span style={{ color: 'var(--negative)', flexShrink: 0, marginTop: '2px' }}>{'\u2013'}</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Actions */}
      <div style={{
        display: 'flex',
        gap: 'var(--sp-3)',
        marginTop: 'var(--sp-5)',
        paddingTop: 'var(--sp-4)',
        borderTop: '1px solid var(--border-subtle)',
      }}>
        <button className="btn btn-primary" onClick={handleViewReport}>
          <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="2" y="1" width="10" height="12" rx="1" />
            <path d="M5 4h4M5 7h4M5 10h2" />
          </svg>
          View Full Report
        </button>
        <button className="btn" onClick={handleExportPdf}>
          <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 10v2h10v-2M7 2v7m-3-3l3 3 3-3" />
          </svg>
          Export PDF
        </button>
      </div>
    </div>
  )
}
