// CoverageTrustStrip — the credibility proof for the target user (analyst /
// quant): "do this product's calls actually work?" Re-homes the orphaned
// /api/dashboard/hit-rate (UX-013) as a COMPACT strip under the search hero,
// scoped to the active coverage group's tickers (portfolio-level is the only
// statistically meaningful scope — a single name has too few closed calls).
//
// Honesty rules (the whole point of surfacing a track record):
//   • Below MIN_CLOSED resolved calls, we DON'T show a percentage — a "100%
//     (1/1)" reads as false precision. We show the closed-call count instead.
//   • is_sampled (BUG-039/062) → a "based on the latest N" caption, never a
//     truncated rate passed off as the complete record.
//   • Scope (group name + n names) + lookback window are always visible so the
//     number is never read out of context.

import { useState } from 'react'
import {
  useDashboardHitRate,
  hitRateSampleCaption,
  type HitRateWindow,
  type HitRateBucket,
} from '../../hooks/useDashboardHitRate'
import { useI18n } from '../../i18n'

// Below this many CLOSED (resolved) calls a hit-rate is noise, not a signal —
// suppress the percentage and disclose the raw count instead.
const MIN_CLOSED = 5

const WINDOWS: HitRateWindow[] = ['30d', '90d', 'all']

interface Props {
  /** The active group's member tickers — the scope for the track record. */
  tickers: string[]
  /** Group display name, shown so the scope is never ambiguous. */
  groupName: string
}

function pct(bucket: HitRateBucket): string {
  return `${Math.round((bucket.hit_rate ?? 0) * 100)}%`
}

export function CoverageTrustStrip({ tickers, groupName }: Props): React.ReactElement | null {
  const { t } = useI18n()
  const [win, setWin] = useState<HitRateWindow>('all')
  const { data, isLoading, isError } = useDashboardHitRate(win, tickers)

  // An empty group has no track record; don't render a placeholder strip.
  if (tickers.length === 0) return null
  // Network failure or first load: stay silent rather than show a broken strip
  // above the wall (the wall itself surfaces its own load/error state).
  if (isError || (isLoading && !data)) return null
  if (!data) return null

  const { overall, by_verdict } = data
  const enough = overall.n_closed >= MIN_CLOSED
  const sampleCaption = hitRateSampleCaption(data)

  return (
    <div
      data-testid="coverage-trust-strip"
      style={{
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 14,
        padding: '8px 16px',
        marginBottom: 10,
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-md)',
        background: 'var(--bg-card)',
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
      }}
    >
      {/* Label + scope — the number is never shown without what it covers. */}
      <span
        style={{
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-display)',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          fontSize: 11,
        }}
      >
        {t('coverage.trust.label')}
      </span>
      <span style={{ color: 'var(--text-secondary)' }}>
        {t('coverage.trust.scope', { group: groupName, n: tickers.length })}
      </span>

      <span aria-hidden style={{ color: 'var(--border-soft)' }}>
        ·
      </span>

      {/* Overall hit rate — suppressed below MIN_CLOSED to avoid false precision. */}
      {overall.n_closed === 0 ? (
        <span style={{ color: 'var(--text-muted)' }}>{t('coverage.trust.none')}</span>
      ) : enough ? (
        <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
          {t('coverage.trust.hitRate', {
            rate: pct(overall),
            hit: overall.n_hit,
            closed: overall.n_closed,
          })}
        </span>
      ) : (
        <span style={{ color: 'var(--text-muted)' }}>
          {t('coverage.trust.insufficient', { closed: overall.n_closed })}
        </span>
      )}

      {/* Per-verdict breakdown — only meaningful (and only shown) once the
          overall sample clears the threshold. */}
      {enough && (
        <span style={{ color: 'var(--text-secondary)', display: 'flex', gap: 10 }}>
          {(['BUY', 'HOLD', 'SELL'] as const).map((v) =>
            by_verdict[v].n_closed > 0 ? (
              <span key={v}>
                {v} {pct(by_verdict[v])}
                <span style={{ color: 'var(--text-muted)' }}> ({by_verdict[v].n_closed})</span>
              </span>
            ) : null,
          )}
        </span>
      )}

      {/* Lookback window toggle — pushed to the right. */}
      <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
        {WINDOWS.map((w) => (
          <button
            key={w}
            type="button"
            onClick={() => setWin(w)}
            className="coverage-hover-btn"
            aria-pressed={win === w}
            style={{
              padding: '3px 9px',
              borderRadius: 'var(--radius-sm)',
              border: `1px solid ${win === w ? 'var(--border-glow)' : 'var(--border-soft)'}`,
              background: win === w ? 'var(--primary-soft)' : 'transparent',
              color: win === w ? 'var(--text-primary)' : 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              cursor: 'pointer',
            }}
          >
            {t(`coverage.trust.window.${w}`)}
          </button>
        ))}
      </div>

      {/* Sampled disclosure — full-width caption so a truncated record is never
          read as complete. */}
      {sampleCaption && (
        <span style={{ flexBasis: '100%', color: 'var(--text-muted)', fontSize: 11 }}>
          {sampleCaption}
        </span>
      )}
    </div>
  )
}
