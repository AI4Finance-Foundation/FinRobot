// ImpactMeter — Bloomberg "relevance meter" idiom: a 5-segment bar, filled =
// impact_score (clamped 0–5), dim = remainder. Inline SVG per cosmic spec §6.5.
// The colour is deliberately neutral (--accent-cyan, not the sentiment colour) —
// impact is magnitude, not direction; direction is carried elsewhere (the row
// border in the News feed). Shared by the News feed and the Key Catalysts list
// so both render per-item impact identically.

import { useI18n } from '../i18n'

interface ImpactMeterProps {
  /** Raw impact score; rendered clamped to the 0–5 segment scale. */
  score: number
}

export function ImpactMeter({ score }: ImpactMeterProps): React.ReactElement {
  const { t } = useI18n()
  // Defensive: a non-finite score (NaN/Infinity) clamps to 0 lit segments
  // rather than leaking "NaN" into data-filled / the tooltip. impact_score is a
  // required number in practice, but never render a fabricated/garbage count.
  const filled = Number.isFinite(score) ? Math.max(0, Math.min(5, Math.round(score))) : 0
  const segW = 5
  const gap = 2
  const segH = 8
  const width = 5 * segW + 4 * gap
  return (
    <span
      data-testid="impact-meter"
      data-filled={filled}
      style={{ display: 'inline-flex', alignItems: 'center' }}
      title={t('chapter.news.feed.impactTooltip', { score: filled })}
    >
      <svg width={width} height={segH} viewBox={`0 0 ${width} ${segH}`} aria-hidden>
        {Array.from({ length: 5 }, (_, i) => (
          <rect
            key={i}
            x={i * (segW + gap)}
            y={0}
            width={segW}
            height={segH}
            rx={1}
            fill={i < filled ? 'var(--accent-cyan)' : 'var(--border-grid)'}
          />
        ))}
      </svg>
    </span>
  )
}
