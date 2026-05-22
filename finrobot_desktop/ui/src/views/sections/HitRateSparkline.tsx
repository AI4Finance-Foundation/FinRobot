// v5 §7.3 sparkline. One dot per artifact signal in chronological order
// (oldest left, newest right). Caps at 22 dots per spec.

import type { Signal } from '../../types/v5'

interface HitRateSparklineProps {
  signals: (Signal | null)[]
}

export function HitRateSparkline({ signals }: HitRateSparklineProps): React.ReactElement | null {
  if (signals.length === 0) return null
  const visible = signals.slice(-22)
  return (
    <div
      data-testid="hit-rate-sparkline"
      style={{ display: 'inline-flex', gap: 3, alignItems: 'center' }}
    >
      {visible.map((s, i) => (
        <span
          key={i}
          data-signal={s ?? 'none'}
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: dotColor(s),
            opacity: s === 'watching' ? 0.55 : 1,
          }}
        />
      ))}
    </div>
  )
}

function dotColor(s: Signal | null): string {
  if (s === 'hit') return 'var(--success)'
  if (s === 'failed') return 'var(--danger)'
  if (s === 'watching') return 'var(--warning)'
  return 'var(--text-faint)'
}
