// EvidenceChip — renders a single evidence item as a pill.
//
// Each chip looks up its evidence_id in the store's evidence map. If the id
// is not in the map (late arrival or backend omission) the chip degrades
// gracefully: shows the raw id string rather than crashing.
//
// Value is wrapped in SourcedNumber so the analyst can hover to see
// formula_id, artifact provenance, and open the full report.

import { SourcedNumber } from '../SourcedNumber'
import type { DebateEvidenceItem } from '../../stores/debateStore'
import { useI18n, type Locale } from '../../i18n'
import { formatNumber } from '../../utils/format'

interface EvidenceChipProps {
  evidenceId: string
  /** The full evidence item from the store. Null means id not yet in map. */
  item: DebateEvidenceItem | null
  /** The artifact_id of the debate-initiating research report. */
  artifactId: string | null
}

/**
 * Render a raw evidence value for display. The backend sends full-precision
 * floats (e.g. 341.5839011153877) — the data layer keeps precision, the UI
 * rounds. Currency prefixes its symbol ($341.58), percent is suffixed with no
 * space (-15.33%), other units keep a trailing space. Non-numeric evidence
 * (rare) renders verbatim. Full precision stays available in the SourcedNumber
 * provenance hover.
 */
function formatEvidenceValue(
  value: number | string,
  unit: string | undefined,
  locale: Locale,
): string {
  if (typeof value !== 'number') {
    return unit ? `${value} ${unit}` : String(value)
  }
  if (Number.isNaN(value)) return '—'
  if (unit === '$') {
    const sign = value < 0 ? '-' : ''
    return `${sign}$${formatNumber(Math.abs(value), locale, 2)}`
  }
  if (unit === '%') return `${formatNumber(value, locale, 2)}%`
  const num = formatNumber(value, locale, 2)
  return unit ? `${num} ${unit}` : num
}

export function EvidenceChip({ evidenceId, item, artifactId }: EvidenceChipProps) {
  const { locale } = useI18n()

  if (!item) {
    // Degraded state: id received but evidence event hasn't arrived yet.
    // Show a muted pill with the raw id so nothing crashes.
    return (
      <span
        title={`Evidence ID: ${evidenceId}`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '2px 8px',
          borderRadius: 999,
          background: 'color-mix(in srgb, var(--text-dim) 12%, transparent)',
          border: '1px solid var(--border-faint)',
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--text-dim)',
          whiteSpace: 'nowrap',
        }}
      >
        {evidenceId}
      </span>
    )
  }

  const displayValue = formatEvidenceValue(item.value, item.unit, locale)

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '3px 9px',
        borderRadius: 999,
        background: 'color-mix(in srgb, var(--secondary) 10%, transparent)',
        border: '1px solid color-mix(in srgb, var(--secondary) 28%, transparent)',
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        color: 'var(--text-secondary)',
        whiteSpace: 'nowrap',
        transition: 'border-color 0.18s',
      }}
      title={item.label}
    >
      <span style={{ color: 'var(--text-muted)' }}>{item.label}</span>
      <span
        style={{
          color: 'var(--text-primary)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        <SourcedNumber
          value={displayValue}
          source={{
            formula_id: item.formula_id,
            artifact_id: artifactId ?? undefined,
          }}
        />
      </span>
    </span>
  )
}
