import type { CatalystEvent, CatalystCategory } from '../stores/appStore'

interface Props {
  catalysts: CatalystEvent[]
  loading?: boolean
}

const CATEGORY_STYLES: Record<CatalystCategory, { color: string; bg: string; label: string }> = {
  product_launch: { color: '#60A5FA', bg: 'rgba(96, 165, 250, 0.12)', label: 'Product' },
  earnings:       { color: '#34D399', bg: 'rgba(52, 211, 153, 0.12)', label: 'Earnings' },
  regulatory:     { color: '#FB923C', bg: 'rgba(251, 146, 60, 0.12)', label: 'Regulatory' },
  acquisition:    { color: '#A78BFA', bg: 'rgba(167, 139, 250, 0.12)', label: 'Acquisition' },
  management:     { color: '#F87171', bg: 'rgba(248, 113, 113, 0.12)', label: 'Management' },
  market:         { color: '#7A8299', bg: 'rgba(122, 130, 153, 0.12)', label: 'Market' },
}

const SENTIMENT_COLORS: Record<string, string> = {
  positive: 'var(--positive)',
  negative: 'var(--negative)',
  neutral:  'var(--text-muted)',
}

function ImpactDots({ score }: { score: number }) {
  return (
    <span className="catalyst-impact-dots" aria-label={`Impact: ${score} out of 5`}>
      {Array.from({ length: 5 }, (_, i) => (
        <span
          key={i}
          className="catalyst-dot"
          style={{
            background: i < score ? 'var(--gold)' : 'var(--border)',
            width: 6,
            height: 6,
            borderRadius: '50%',
            display: 'inline-block',
          }}
        />
      ))}
    </span>
  )
}

function CatalystCard({ event }: { event: CatalystEvent }) {
  const catStyle = CATEGORY_STYLES[event.category] || CATEGORY_STYLES.market
  const sentColor = SENTIMENT_COLORS[event.sentiment] || SENTIMENT_COLORS.neutral

  return (
    <div className="catalyst-card">
      <div className="catalyst-card-top">
        <span
          className="catalyst-category-badge"
          style={{ color: catStyle.color, background: catStyle.bg }}
        >
          {catStyle.label}
        </span>
        <span
          className="catalyst-sentiment"
          style={{ color: sentColor }}
        >
          {event.sentiment}
        </span>
      </div>
      <div className="catalyst-headline">{event.headline}</div>
      <div className="catalyst-reasoning">{event.reasoning}</div>
      <div className="catalyst-card-bottom">
        <ImpactDots score={event.impact_score} />
        <span className="catalyst-prob font-mono">
          {Math.round(event.probability * 100)}% prob
        </span>
      </div>
    </div>
  )
}

export default function CatalystPanel({ catalysts, loading }: Props) {
  if (loading) {
    return (
      <div className="card animate-in">
        <div className="card-header">
          <span className="card-title">Catalysts</span>
        </div>
        <div className="card-body" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading catalysts...
        </div>
      </div>
    )
  }

  if (!catalysts.length) {
    return (
      <div className="card animate-in">
        <div className="card-header">
          <span className="card-title">Catalysts</span>
        </div>
        <div className="card-body" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
          No catalyst events found for this ticker.
        </div>
      </div>
    )
  }

  const positiveCount = catalysts.filter((c) => c.sentiment === 'positive').length
  const negativeCount = catalysts.filter((c) => c.sentiment === 'negative').length

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">Catalysts</span>
        <div className="card-header-right">
          {positiveCount > 0 && (
            <span className="catalyst-summary-badge catalyst-summary-badge--pos">
              {positiveCount} positive
            </span>
          )}
          {negativeCount > 0 && (
            <span className="catalyst-summary-badge catalyst-summary-badge--neg">
              {negativeCount} negative
            </span>
          )}
          <span className="card-badge">{catalysts.length} events</span>
        </div>
      </div>
      <div className="card-body catalyst-grid">
        {catalysts.map((event, i) => (
          <CatalystCard key={i} event={event} />
        ))}
      </div>
    </div>
  )
}
