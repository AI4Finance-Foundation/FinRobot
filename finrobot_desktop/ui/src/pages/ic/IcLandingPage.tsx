// IcLandingPage — /ic route.
//
// Lists tickers that have at least one equity_research artifact.
// Each row shows ticker + latest report timestamp. Clicking navigates to
// /ic/:ticker?artifact_id=<latest_equity_research_id>.
//
// Uses useDashboardRecentResearch (existing hook) — filters items where
// the latest run is type === 'equity_research'.
// Empty state prompts the analyst to generate a research report first.

import { useNavigate } from 'react-router-dom'
import { useDashboardRecentResearch } from '../../hooks/useDashboardRecentResearch'
import { formatDate } from '../../utils/format'
import { useI18n } from '../../i18n'

export function IcLandingPage() {
  const navigate = useNavigate()
  const { locale, t } = useI18n()
  const { data, isLoading, isError } = useDashboardRecentResearch(20)

  // Filter to tickers that have at least one equity_research run.
  const equityItems =
    data?.items.filter((item) => item.runs.some((r) => r.type === 'equity_research')) ?? []

  function handleSelect(ticker: string, artifactId: string) {
    navigate(`/ic/${ticker}?artifact_id=${artifactId}`)
  }

  return (
    <div
      data-testid="ic-landing-page"
      style={{
        maxWidth: 860,
        margin: '0 auto',
        padding: '48px 32px 80px',
      }}
    >
      {/* Page header */}
      <div style={{ marginBottom: 40 }}>
        <h1
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 24,
            letterSpacing: '0.14em',
            color: 'var(--text-primary)',
            margin: 0,
            marginBottom: 8,
          }}
        >
          Investment Committee
        </h1>
        <p
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 13,
            color: 'var(--text-muted)',
            margin: 0,
            lineHeight: 1.6,
          }}
        >
          {t('ic.landing.subtitle')}
        </p>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-muted)',
            letterSpacing: '0.08em',
          }}
        >
          {t('ic.landing.loading')}
        </div>
      )}

      {/* Error state */}
      {isError && !isLoading && (
        <div
          style={{
            padding: '16px 20px',
            background: 'color-mix(in srgb, var(--danger) 8%, transparent)',
            border: '1px solid color-mix(in srgb, var(--danger) 28%, transparent)',
            borderRadius: 'var(--radius-sm)',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--danger)',
          }}
        >
          {t('ic.landing.loadError')}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !isError && equityItems.length === 0 && (
        <div
          style={{
            padding: '40px 32px',
            background: 'rgba(15,15,34,0.6)',
            backdropFilter: 'blur(12px)',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-lg)',
            textAlign: 'center',
          }}
        >
          <div
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 15,
              letterSpacing: '0.10em',
              color: 'var(--text-muted)',
              marginBottom: 12,
            }}
          >
            {t('ic.landing.empty.title')}
          </div>
          <p
            style={{
              fontFamily: 'var(--font-body)',
              fontSize: 13,
              color: 'var(--text-dim)',
              margin: '0 0 24px',
              lineHeight: 1.6,
            }}
          >
            {t('ic.landing.empty.line1')}
            <br />
            {t('ic.landing.empty.line2')}
          </p>
          <button
            type="button"
            onClick={() => navigate('/stocks')}
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 12,
              letterSpacing: '0.10em',
              padding: '10px 24px',
              borderRadius: 'var(--radius-md)',
              border: 'none',
              background: 'linear-gradient(135deg, var(--secondary) 0%, var(--primary) 100%)',
              color: 'var(--text-primary)',
              cursor: 'pointer',
              transition: 'opacity 0.18s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.85')}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
          >
            {t('ic.landing.empty.cta')}
          </button>
        </div>
      )}

      {/* Ticker list */}
      {equityItems.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {equityItems.map((item) => {
            // Pick the latest equity_research artifact id.
            const latestRun = item.runs.find((r) => r.type === 'equity_research')
            if (!latestRun) return null

            return (
              <button
                key={item.ticker}
                type="button"
                onClick={() => handleSelect(item.ticker, latestRun.artifact_id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 16,
                  padding: '16px 20px',
                  background: 'rgba(15,15,34,0.6)',
                  backdropFilter: 'blur(12px)',
                  border: '1px solid var(--border-soft)',
                  borderRadius: 'var(--radius-md)',
                  cursor: 'pointer',
                  textAlign: 'left',
                  transition: 'border-color 0.18s, box-shadow 0.18s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--border-glow)'
                  e.currentTarget.style.boxShadow = '0 4px 20px rgba(59,130,246,0.10)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--border-soft)'
                  e.currentTarget.style.boxShadow = 'none'
                }}
                aria-label={t('ic.landing.row.aria', { ticker: item.ticker })}
              >
                {/* Ticker */}
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 15,
                    fontWeight: 600,
                    color: 'var(--accent-cyan)',
                    letterSpacing: '0.06em',
                    minWidth: 72,
                    flexShrink: 0,
                  }}
                >
                  {item.ticker}
                </span>

                {/* Latest verdict chip */}
                {latestRun.verdict && <VerdictPill verdict={latestRun.verdict} />}

                <span style={{ flex: 1, minWidth: 0 }} />

                {/* Report date */}
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    color: 'var(--text-muted)',
                    letterSpacing: '0.04em',
                    whiteSpace: 'nowrap',
                    flexShrink: 0,
                  }}
                >
                  {t('ic.landing.row.reportDate', {
                    date: formatDate(latestRun.created_at, locale, 'short'),
                  })}
                </span>

                {/* CTA chevron */}
                <span
                  style={{ color: 'var(--text-dim)', fontSize: 16, lineHeight: 1, flexShrink: 0 }}
                  aria-hidden
                >
                  ›
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

function VerdictPill({ verdict }: { verdict: 'BUY' | 'HOLD' | 'SELL' | null }) {
  if (!verdict) return null
  const color =
    verdict === 'BUY' ? 'var(--success)' : verdict === 'SELL' ? 'var(--danger)' : 'var(--warning)'
  return (
    <span
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        letterSpacing: '0.08em',
        padding: '2px 8px',
        borderRadius: 999,
        background: `color-mix(in srgb, ${color} 12%, transparent)`,
        border: `1px solid color-mix(in srgb, ${color} 32%, transparent)`,
        color,
      }}
    >
      {verdict}
    </span>
  )
}
