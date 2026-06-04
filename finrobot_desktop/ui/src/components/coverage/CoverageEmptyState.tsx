// CoverageEmptyState — the archive has no studied ticker records yet. Research
// starts from `/research`; Coverage remains the management surface and points
// back to that search-first door.

import { useNavigate } from 'react-router-dom'
import { useI18n } from '../../i18n'

export function CoverageEmptyState(): React.ReactElement {
  const { t } = useI18n()
  const navigate = useNavigate()

  return (
    <div
      data-testid="coverage-empty"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        padding: '20px 24px',
        overflowY: 'auto',
      }}
    >
      <div
        style={{
          width: 'min(520px, 100%)',
          padding: 24,
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-lg)',
          background: 'var(--bg-card-deep)',
          textAlign: 'center',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 14,
        }}
      >
        <h1
          style={{
            margin: 0,
            fontFamily: 'var(--font-display)',
            fontSize: 18,
            letterSpacing: '0.08em',
            color: 'var(--text-primary)',
          }}
        >
          {t('coverage.emptyArchive.title')}
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: 14, lineHeight: 1.7, margin: 0 }}>
          {t('coverage.emptyArchive.body')}
        </p>
        <button
          type="button"
          className="btn-shimmer"
          onClick={() => navigate('/research')}
          style={{ padding: '9px 18px', fontSize: 11 }}
        >
          {t('coverage.emptyArchive.action')}
        </button>
      </div>
    </div>
  )
}
