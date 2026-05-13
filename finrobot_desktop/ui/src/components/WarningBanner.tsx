import { useState } from 'react'

interface Props {
  warnings: string[]
}

export default function WarningBanner({ warnings }: Props) {
  const [expanded, setExpanded] = useState(false)

  if (!warnings || warnings.length === 0) return null

  const show = expanded ? warnings : warnings.slice(0, 3)
  const hasMore = warnings.length > 3

  return (
    <div className="warning-banner animate-in">
      <svg viewBox="0 0 16 16" fill="currentColor">
        <path d="M8 1L1 14h14L8 1zm0 4.5v4m0 2v.5" />
      </svg>
      <div>
        {show.map((w, i) => (
          <div key={i} style={{ paddingBottom: i < show.length - 1 ? '2px' : 0 }}>
            {w}
          </div>
        ))}
        {hasMore && !expanded && (
          <button
            onClick={() => setExpanded(true)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--warning)',
              fontSize: '0.72rem',
              cursor: 'pointer',
              marginTop: 'var(--sp-1)',
              textDecoration: 'underline',
              padding: 0,
            }}
          >
            {warnings.length} warnings total
          </button>
        )}
        {hasMore && expanded && (
          <button
            onClick={() => setExpanded(false)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--warning)',
              fontSize: '0.72rem',
              cursor: 'pointer',
              marginTop: 'var(--sp-1)',
              textDecoration: 'underline',
              padding: 0,
            }}
          >
            Collapse
          </button>
        )}
      </div>
    </div>
  )
}
