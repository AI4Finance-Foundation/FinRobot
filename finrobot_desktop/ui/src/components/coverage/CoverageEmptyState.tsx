// CoverageEmptyState — the cold-start screen (no coverage yet). The homepage's
// primary task is "launch single-stock deep research", and coverage is the
// archive that ACCUMULATES from that research — so the empty state leads with
// the SAME search hero as the populated desk (one identity, no FINROBOT-vs-
// Coverage-Desk split — UX-014) and drives straight into /stocks/:ticker
// (UX-001). No "create a group" form: opening a ticker auto-enrolls it into the
// Studied Tickers system group (useAddStudiedTicker), so coverage materialises
// from research with zero setup.

import { useNavigate } from 'react-router-dom'
import { CoverageHero } from './CoverageHero'
import { useI18n } from '../../i18n'

const HOT_TICKERS = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMD']

export function CoverageEmptyState(): React.ReactElement {
  const { t } = useI18n()
  const navigate = useNavigate()

  return (
    <div
      data-testid="coverage-empty"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        padding: '20px 24px',
        overflowY: 'auto',
      }}
    >
      <CoverageHero />

      <div
        style={{
          maxWidth: 560,
          margin: '4px auto 0',
          textAlign: 'center',
          display: 'flex',
          flexDirection: 'column',
          gap: 18,
        }}
      >
        <p style={{ color: 'var(--text-secondary)', fontSize: 14, lineHeight: 1.7, margin: 0 }}>
          {t('coverage.starter.searchFirstHint')}
        </p>

        <div>
          <div
            style={{
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-display)',
              fontSize: 11,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              marginBottom: 10,
            }}
          >
            {t('coverage.starter.quickPick')}
          </div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap' }}>
            {HOT_TICKERS.map((tk) => (
              <button
                key={tk}
                type="button"
                className="coverage-hover-btn"
                onClick={() => navigate(`/stocks/${tk}`)}
                aria-label={t('coverage.starter.researchTicker', { ticker: tk })}
                style={{
                  padding: '6px 16px',
                  borderRadius: 999,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 13,
                  cursor: 'pointer',
                  background: 'transparent',
                  color: 'var(--text-secondary)',
                  border: '1px solid var(--border-soft)',
                }}
              >
                {tk}
              </button>
            ))}
          </div>
        </div>

        <p style={{ color: 'var(--text-muted)', fontSize: 12, margin: 0 }}>
          {t('coverage.starter.autoCoverageNote')}
        </p>
      </div>
    </div>
  )
}
