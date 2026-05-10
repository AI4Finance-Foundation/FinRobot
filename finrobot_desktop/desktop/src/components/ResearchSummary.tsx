import { useCallback, useState } from 'react'
import { useCountUp } from '../hooks/useCountUp'
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

/** Show first N items with expand toggle */
function ExpandableList({ items, icon, iconColor, initialCount = 3 }: {
  items: string[]
  icon: string
  iconColor: string
  initialCount?: number
}) {
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? items : items.slice(0, initialCount)
  const hasMore = items.length > initialCount

  return (
    <>
      <ul className="research-list">
        {visible.map((item, i) => (
          <li key={i} className="research-list-item">
            <span className="research-list-icon" style={{ color: iconColor }}>{icon}</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
      {hasMore && (
        <button
          className="research-expand-btn"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Show less' : `+${items.length - initialCount} more`}
        </button>
      )}
    </>
  )
}

export default function ResearchSummary({ result, currentPrice }: Props) {
  const ticker = useAppStore((s) => s.ticker)
  const animatedTarget = useCountUp(result.price_target)

  const upside =
    currentPrice && currentPrice > 0
      ? ((result.price_target - currentPrice) / currentPrice) * 100
      : null
  const animatedUpside = useCountUp(upside ?? 0, 700, 1)
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
      <div className="hero-header">
        <div>
          <div className="valuation-label">
            Investment Rating
            <span
              className="source-badge source-llm"
              data-tooltip="AI judgment informed by data"
            >
              AI
            </span>
          </div>
          <span
            className="status-badge status-badge--lg"
            style={{ background: ratingStyle.bg, color: ratingStyle.color }}
          >
            {result.recommendation}
          </span>
        </div>
        <div className="text-right">
          <div className="valuation-label">
            Price Target
            <span
              className="source-badge source-llm"
              data-tooltip="AI judgment informed by DCF + comps"
            >
              AI
            </span>
          </div>
          <div className="valuation-price" style={{ fontSize: '2.2rem' }}>
            <span className="currency">$</span>
            {animatedTarget.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Upside/Downside */}
      {upside !== null && (
        <div className="metrics-row metrics-row--sm" style={{ marginBottom: 'var(--sp-5)' }}>
          <div className={`valuation-upside ${isPositive ? 'positive' : 'negative'}`}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
              {isPositive ? <path d="M6 2v8M3 5l3-3 3 3" /> : <path d="M6 10V2M3 7l3 3 3-3" />}
            </svg>
            {isPositive ? '+' : ''}{animatedUpside.toFixed(1)}% vs ${currentPrice!.toFixed(2)}
          </div>
          <span className="implied-method">{result.price_target_basis}</span>
        </div>
      )}

      {/* Investment Thesis */}
      {result.narrative && (
        <div className="research-thesis">
          <div className="research-section-label">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3">
              <rect x="1.5" y="1.5" width="9" height="9" rx="1" />
              <path d="M4 4h4M4 6h4M4 8h2" />
            </svg>
            Investment Thesis
          </div>
          <p className="research-thesis-text">{result.narrative}</p>
        </div>
      )}

      {/* Catalysts & Risks */}
      <div className="research-drivers">
        <div>
          <div className="research-section-label">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="var(--positive)" strokeWidth="1.3">
              <circle cx="6" cy="6" r="4" />
              <path d="M6 4v4M4 6h4" />
            </svg>
            Catalysts
            <span className="research-count">{result.catalysts.length}</span>
          </div>
          <ExpandableList
            items={result.catalysts}
            icon="+"
            iconColor="var(--positive)"
          />
        </div>
        <div>
          <div className="research-section-label">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="var(--negative)" strokeWidth="1.3">
              <path d="M6 3v4M6 9v0" />
              <circle cx="6" cy="6" r="4" />
            </svg>
            Risks
            <span className="research-count">{result.risks.length}</span>
          </div>
          <ExpandableList
            items={result.risks}
            icon={'\u2013'}
            iconColor="var(--negative)"
          />
        </div>
      </div>

      {/* Actions */}
      <div className="research-actions">
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
