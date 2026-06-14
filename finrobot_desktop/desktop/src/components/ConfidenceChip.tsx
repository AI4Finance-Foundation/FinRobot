// ConfidenceChip — the small tier chip that renders analytical conviction on a
// NON-hue channel (HIGH CONVICTION / MEDIUM / LOW / SPECULATIVE). It NEVER
// borrows a verdict hue: the chip is a neutral slate pill whose only
// tier-dependent treatment is a static neutral glow + opacity (the prior
// REVIEW-as-amber bug was exactly this kind of hue borrow).
//
// It carries a `data-confidence` attribute so the verdict surface is
// mechanically testable next to the existing `data-verdict` hook — confidence
// rendering is a known recurrence class, so it gets a stable test seam.

import type { ConfidenceTier } from '../utils/verdict'
import { confidenceChip } from '../utils/verdict'

interface ConfidenceChipProps {
  tier: ConfidenceTier
  /** Compact mode for dense rows (smaller padding/font). */
  compact?: boolean
}

export function ConfidenceChip({ tier, compact = false }: ConfidenceChipProps): React.ReactElement {
  const chip = confidenceChip(tier)
  return (
    <span
      data-testid="confidence-chip"
      data-confidence={tier}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        fontFamily: 'var(--font-mono)',
        fontSize: compact ? 9 : 10,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        padding: compact ? '1px 7px' : '2px 9px',
        borderRadius: 999,
        color: 'var(--text-secondary)',
        background: 'var(--neutral-soft)',
        border: '1px solid var(--neutral-edge)',
        opacity: chip.opacity,
        boxShadow: chip.glow !== 'none' ? chip.glow : undefined,
        whiteSpace: 'nowrap',
      }}
    >
      <ConvictionGlyph tier={tier} />
      {chip.label}
    </span>
  )
}

// Four filled bars of a signal-strength meter — a language-neutral, hue-free
// conviction glyph (more bars = higher conviction). Inline SVG per cosmic spec.
function ConvictionGlyph({ tier }: { tier: ConfidenceTier }): React.ReactElement {
  const filled = tier === 'high' ? 4 : tier === 'medium' ? 3 : tier === 'low' ? 2 : 1
  const bars = [0, 1, 2, 3]
  return (
    <svg width="12" height="10" viewBox="0 0 12 10" fill="none" aria-hidden>
      {bars.map((i) => {
        const h = 2.5 + i * 2.2
        return (
          <rect
            key={i}
            x={i * 3}
            y={10 - h}
            width="2"
            height={h}
            rx="0.5"
            fill="currentColor"
            opacity={i < filled ? 0.9 : 0.22}
          />
        )
      })}
    </svg>
  )
}
