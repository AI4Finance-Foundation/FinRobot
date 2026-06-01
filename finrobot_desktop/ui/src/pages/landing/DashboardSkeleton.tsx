// DashboardSkeleton — shimmer placeholder for the hit-rate banner only,
// shown while the backend QuoteCache lifespan warmup is still running
// (the banner's bucket math needs warm quotes). The recent-research strip
// is NOT covered here — it renders immediately with its own loading state.
// Sizing roughly matches the real banner so the page does not reflow.
//
// Visibility is gated by `useQuotesWarmed` in `StocksLandingHero`.

import { useI18n } from '../../i18n'

export function DashboardSkeleton(): React.ReactElement {
  const { t } = useI18n()
  return (
    <div
      data-testid="dashboard-skeleton"
      style={{ display: 'flex', flexDirection: 'column', gap: 16 }}
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
