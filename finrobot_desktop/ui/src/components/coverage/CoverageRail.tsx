// CoverageRail — the Coverage Desk right rail: Track Record (reuses the
// existing /api/dashboard/hit-rate hook) + a Needs-Refresh digest derived from
// the current overview rows. No new menus — the landing's hit-rate lives here
// now (Coverage plan). Honest 0-data: no closed sample → "—", never a fake 0%.

import { useI18n } from '../../i18n'
import { formatPercent } from '../../utils/format'
import { useDashboardHitRate } from '../../hooks/useDashboardHitRate'
import type { CoverageRow } from '../../api/coverage'

const PANEL: React.CSSProperties = {
  background: 'rgba(15,15,34,0.6)',
  border: '1px solid var(--border-soft)',
  borderRadius: 'var(--radius-lg)',
  padding: 16,
  marginBottom: 16,
}
const TITLE: React.CSSProperties = {
  fontFamily: 'var(--font-display)',
  fontSize: 12,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--text-secondary)',
  marginBottom: 12,
}

export function CoverageRail({ rows }: { rows: CoverageRow[] }): React.ReactElement {
  return (
    <div style={{ width: 260, flexShrink: 0, overflow: 'auto' }}>
      <TrackRecordPanel />
      <NeedsRefreshPanel rows={rows} />
    </div>
  )
}

function TrackRecordPanel(): React.ReactElement {
  const { t, locale } = useI18n()
  const { data, isLoading } = useDashboardHitRate('all')
  const overall = data?.overall

  let body: React.ReactNode
  if (isLoading) {
    body = <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>…</span>
  } else if (!overall || overall.n_closed === 0) {
    // No closed sample → em-dash, never a fake 0% (Coverage plan rule).
    body = (
      <>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 28, color: 'var(--text-muted)' }}>
          —
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
          {overall && overall.n_total > 0
            ? t('coverage.track.watching')
            : t('coverage.track.empty')}
        </div>
      </>
    )
  } else {
    body = (
      <>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 28,
            color: 'var(--success)',
            textShadow: 'var(--glow-cyan)',
          }}
        >
          {formatPercent(overall.hit_rate, locale, 0)}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
          {t('coverage.track.sample', { closed: overall.n_closed, total: overall.n_total })}
        </div>
      </>
    )
  }

  return (
    <div style={PANEL}>
      <div style={TITLE}>{t('coverage.track.title')}</div>
      {body}
    </div>
  )
}

function NeedsRefreshPanel({ rows }: { rows: CoverageRow[] }): React.ReactElement {
  const { t } = useI18n()
  const flagged = rows.filter((r) => r.needs_refresh.length > 0)

  return (
    <div style={PANEL}>
      <div style={TITLE}>{t('coverage.refresh.title')}</div>
      {flagged.length === 0 ? (
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {t('coverage.refresh.empty')}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {flagged.slice(0, 8).map((r) => (
            <div key={r.ticker} style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  color: 'var(--text-primary)',
                  fontWeight: 600,
                  minWidth: 44,
                }}
              >
                {r.ticker}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.4 }}>
                {r.needs_refresh[0].detail}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
