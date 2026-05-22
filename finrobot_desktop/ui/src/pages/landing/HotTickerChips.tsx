// HotTickerChips — recent + popular ticker pills on the landing search.
//
// Shows up to 8 ticker chips, prioritising user's recents; falls back to
// a curated popular set for first-time users.

import { useNavigate } from 'react-router-dom'

const POPULAR = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'META', 'GOOGL', 'BRKB'] as const

interface Props {
  recentTickers: string[]
}

export function HotTickerChips({ recentTickers }: Props): React.ReactElement {
  const navigate = useNavigate()
  const recent = recentTickers.slice(0, 8)
  const showRecent = recent.length > 0
  const list = showRecent ? recent : POPULAR

  return (
    <div style={{ textAlign: 'center' }}>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.14em',
          marginBottom: 10,
        }}
      >
        {showRecent ? '最近' : '热门'}
      </div>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 8,
          justifyContent: 'center',
          maxWidth: 520,
        }}
      >
        {list.map((tk) => (
          <button
            key={tk}
            type="button"
            onClick={() => navigate(`/stocks/${tk}`)}
            aria-label={`Load ${tk}`}
            style={{
              padding: '6px 14px',
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              fontWeight: 600,
              color: 'var(--text-secondary)',
              background: 'rgba(15,15,34,0.6)',
              border: '1px solid var(--border-soft)',
              borderRadius: 999,
              cursor: 'pointer',
              letterSpacing: '0.05em',
              transition: 'all 0.15s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = 'var(--border-glow)'
              e.currentTarget.style.color = 'var(--text-primary)'
              e.currentTarget.style.boxShadow = '0 0 16px rgba(59,130,246,0.18)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'var(--border-soft)'
              e.currentTarget.style.color = 'var(--text-secondary)'
              e.currentTarget.style.boxShadow = 'none'
            }}
          >
            {tk}
          </button>
        ))}
      </div>
    </div>
  )
}
