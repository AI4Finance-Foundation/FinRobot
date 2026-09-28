// Cosmic warning banner — surfaces backend `warnings` array prominently so
// analysts can see data-quality / staleness / fallback notices instead of
// trusting silently-degraded numbers. AGENTS.md red-line #2 (不确定性传递)
// requires every backend warning to land somewhere visible in the UI; before
// this component existed, warnings sat in the API response and went nowhere.
//
// Behavior:
//   - Hidden when `warnings` is null/undefined/empty (no false alarms).
//   - Single warning → single inline row.
//   - 2+ warnings → first one shown, "+N more" toggles a collapsible list.
//   - Tone defaults to `warn` (amber); pass `tone="danger"` for stale-cache or
//     provider-down scenarios where the analyst MUST notice before acting.

import { useState, type CSSProperties } from 'react'
import { useI18n } from '../i18n'

interface Props {
  warnings: readonly string[] | null | undefined
  tone?: 'warn' | 'danger'
  /** Optional label shown before the first warning, e.g. "数据警告". */
  label?: string
  /** Inline style overrides for the outer container. */
  style?: CSSProperties
}

export function WarningBanner({
  warnings,
  tone = 'warn',
  label,
  style: outerStyle,
}: Props): React.ReactElement | null {
  const { t } = useI18n()
  const [expanded, setExpanded] = useState(false)
  const items = (warnings ?? []).filter((w) => typeof w === 'string' && w.trim().length > 0)
  if (items.length === 0) return null

  const palette = TONE_STYLES[tone]
  const first = items[0]
  const rest = items.slice(1)

  return (
    <div
      role="alert"
      data-testid={`warning-banner-${tone}`}
      style={{
        padding: '10px 16px',
        background: palette.bg,
        border: `1px solid ${palette.border}`,
        borderLeft: `3px solid ${palette.accent}`,
        borderRadius: 'var(--radius-sm)',
        color: palette.text,
        fontSize: 12.5,
        lineHeight: 1.55,
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        ...outerStyle,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: palette.accent }}>
          ⚠
        </span>
        {label && (
          <strong style={{ color: palette.accent, letterSpacing: '0.04em' }}>{label}</strong>
        )}
        <span style={{ flex: 1, fontFamily: 'var(--font-body)' }}>{first}</span>
        {rest.length > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            style={{
              border: 'none',
              background: 'transparent',
              color: palette.accent,
              fontSize: 11,
              fontFamily: 'var(--font-mono)',
              cursor: 'pointer',
              padding: '2px 8px',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            {expanded
              ? t('shell.warning.collapse')
              : t('shell.warning.more', { count: rest.length })}
          </button>
        )}
      </div>
      {expanded && rest.length > 0 && (
        <ul
          style={{
            margin: 0,
            paddingLeft: 22,
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
            fontFamily: 'var(--font-body)',
          }}
        >
          {rest.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

const TONE_STYLES: Record<
  'warn' | 'danger',
  {
    bg: string
    border: string
    accent: string
    text: string
  }
> = {
  warn: {
    bg: 'color-mix(in srgb, var(--warning) 6%, transparent)',
    border: 'color-mix(in srgb, var(--warning) 32%, transparent)',
    accent: 'var(--warning)',
    text: 'var(--text-secondary)',
  },
  danger: {
    // bg/border tint the same --danger hue as the accent (was off-palette
    // red-500 #ef4444; aligned to the canonical --danger #dc2626).
    bg: 'color-mix(in srgb, var(--danger) 8%, transparent)',
    border: 'color-mix(in srgb, var(--danger) 40%, transparent)',
    accent: 'var(--danger)',
    text: 'var(--text-secondary)',
  },
}
