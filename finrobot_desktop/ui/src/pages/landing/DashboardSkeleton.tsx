// DashboardSkeleton — shimmer placeholder for the landing dashboard
// (hit-rate banner + recent-research strip) while the backend
// QuoteCache lifespan warmup is still running. Sizing roughly matches
// the real components so the page does not reflow when the data lands.
//
// Visibility is gated by `useQuotesWarmed` in `StocksLandingHero`.

import { useI18n } from '../../i18n'

export function DashboardSkeleton(): React.ReactElement {
  const { t } = useI18n()
  return (
    <div
      data-testid="dashboard-skeleton"
      style={{ display: 'flex', flexDirection: 'column', gap: 32 }}
    >
      {/* hit-rate banner placeholder: title bar + 3 metric columns */}
      <div
        className="cosmic-card cosmic-card-glass"
        style={{ padding: 28, display: 'flex', flexDirection: 'column', gap: 16 }}
      >
        <div className="skeleton" style={{ height: 16, width: '40%' }} aria-hidden />
        <div style={{ display: 'flex', gap: 24 }}>
          {[0, 1, 2].map((i) => (
            <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="skeleton" style={{ height: 36 }} aria-hidden />
              <div className="skeleton" style={{ height: 12, width: '60%' }} aria-hidden />
            </div>
          ))}
        </div>
      </div>

      {/* recent-research strip placeholder: 4 ticker drawer cards */}
      <div style={{ display: 'flex', gap: 16, overflow: 'hidden' }}>
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="cosmic-card cosmic-card-glass"
            style={{
              minWidth: 220,
              padding: 20,
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
            }}
          >
            <div className="skeleton" style={{ height: 18, width: '50%' }} aria-hidden />
            <div className="skeleton" style={{ height: 32 }} aria-hidden />
            <div className="skeleton" style={{ height: 12 }} aria-hidden />
            <div className="skeleton" style={{ height: 12, width: '80%' }} aria-hidden />
          </div>
        ))}
      </div>

      <div
        role="status"
        aria-live="polite"
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--text-muted)',
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          textAlign: 'center',
        }}
      >
        {t('landing.warmup.label')}
      </div>
    </div>
  )
}
