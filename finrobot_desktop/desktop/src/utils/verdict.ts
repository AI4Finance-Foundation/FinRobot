// Verdict label + tone helpers.
//
// The verdict is ALWAYS directional: BUY / HOLD / SELL. The deleted "REVIEW"
// refuse-to-judge state no longer exists — a withheld POINT target ships
// alongside a directional verdict (price_target === null + valuation_withheld),
// never as a non-directional badge. Legacy stored artifacts may still carry
// recommendation === "REVIEW"; the backend display token for those is the
// neutral "WITHHELD" (summary_extractor._WITHHELD_VERDICT_DISPLAY). We render
// that token in a neutral slate — never the forbidden "REVIEW" string, and
// never borrowing a buy/sell hue.
//
// Backend types remain the uppercase string union; we only localise at the
// display layer.

import { tSync, type Locale } from '../i18n'

// The directional verdict union. "WITHHELD" is a DISPLAY token only (legacy
// artifacts) — it is never a verdict the backend computes anymore.
export type Verdict = 'BUY' | 'HOLD' | 'SELL'

/** Analytical confidence tier — the dial that replaced the binary reliable
 * gate. Rendered on a NON-hue channel (chip label + glow/opacity), never by
 * tinting the verdict badge. Mirrors ValuationSynthesis.confidence. */
export type ConfidenceTier = 'high' | 'medium' | 'low' | 'very_low'

// Legacy display token — a stored REVIEW recommendation surfaces as this.
const WITHHELD_TOKEN = 'WITHHELD'

/**
 * Translate a verdict for display. Pass an explicit locale to avoid hook usage
 * in non-React contexts. The default reads the current zustand snapshot.
 *
 *   verdictLabel('BUY')           → '买入' (when locale=zh) or 'BUY' (en)
 *   verdictLabel('HOLD', 'en')    → 'HOLD'
 *   verdictLabel('REVIEW')        → 'WITHHELD' (legacy artifacts, neutral)
 *   verdictLabel(null)            → '—'
 */
export function verdictLabel(
  verdict: Verdict | string | null | undefined,
  locale?: Locale,
): string {
  if (!verdict) return '—'
  const upper = verdict.toUpperCase()
  // Legacy REVIEW → neutral WITHHELD display token (never the "REVIEW" string).
  if (upper === 'REVIEW' || upper === 'WITHHELD') return tSync('verdict.withheld')
  if (upper !== 'BUY' && upper !== 'HOLD' && upper !== 'SELL') return upper

  // Both locales go through the catalog:
  //   zh → '买入' / '持有' / '卖出' (中国券商 standard)
  //   en → 'BUY' / 'HOLD' / 'SELL' (investment-bank uppercase convention)
  // The `locale` parameter is reserved for callers who explicitly need a
  // non-default locale; current store snapshot is used by default.
  void locale
  const key = upper === 'BUY' ? 'verdict.buy' : upper === 'HOLD' ? 'verdict.hold' : 'verdict.sell'
  return tSync(key)
}

/** Cosmic-theme tone (bg / fg / border) for a verdict badge. */
export interface VerdictTone {
  bg: string
  fg: string
  border: string
}

// Single source of truth for verdict colouring — consumed by the cover hero
// badge AND the right-rail version-timeline badge. The hue is BOUND to the
// directional call (涨绿跌红) and is NEVER borrowed for confidence. The legacy
// WITHHELD token is a neutral slate (no directional call to colour).
const VERDICT_TONE: Record<string, VerdictTone> = {
  BUY: {
    bg: 'var(--success-soft)',
    fg: 'var(--success)',
    border: 'color-mix(in srgb, var(--success) 55%, transparent)',
  },
  HOLD: {
    bg: 'var(--warning-soft)',
    fg: 'var(--warning)',
    border: 'color-mix(in srgb, var(--warning) 55%, transparent)',
  },
  SELL: {
    bg: 'var(--danger-soft)',
    fg: 'var(--danger)',
    border: 'color-mix(in srgb, var(--danger) 55%, transparent)',
  },
  [WITHHELD_TOKEN]: {
    bg: 'var(--neutral-soft)',
    fg: 'var(--text-secondary)',
    border: 'var(--neutral-edge)',
  },
}

/** Resolve a verdict's badge tone. Legacy REVIEW maps to the neutral WITHHELD
 * tone; any other unknown / missing verdict falls back to HOLD amber. */
export function verdictTone(verdict: Verdict | string | null | undefined): VerdictTone {
  const upper = (verdict ?? '').toUpperCase()
  if (upper === 'REVIEW' || upper === 'WITHHELD') return VERDICT_TONE[WITHHELD_TOKEN]
  return VERDICT_TONE[upper] ?? VERDICT_TONE.HOLD
}

// ── Confidence tier (NON-hue channel) ────────────────────────────────────────

/** Visual treatment for a confidence tier. The verdict hue is untouched; the
 * tier modulates only a NEUTRAL glow + chip opacity, so conviction reads on a
 * channel orthogonal to direction (high = bright/tight, very_low = dim/wide). */
export interface ConfidenceChip {
  /** Localised chip label (HIGH CONVICTION / MEDIUM / LOW / SPECULATIVE). */
  label: string
  /** Chip opacity — scales down as conviction drops. */
  opacity: number
  /** Static neon glow (neutral primary-blue), brighter at higher conviction.
   * 'none' at the lowest tiers so a speculative call doesn't glow confidently. */
  glow: string
  /** Fraction [0,1] of the maximum band width — high = tight, very_low = wide.
   * Drives <TargetRange> when explicit target_low/high aren't supplied. */
  bandFactor: number
}

const TIER_ORDER: ConfidenceTier[] = ['high', 'medium', 'low', 'very_low']

/** Normalise a backend tier string; unknown → 'low' (matches the model default
 * so a legacy artifact never implies conviction it wasn't graded for). */
export function normalizeConfidence(value: string | null | undefined): ConfidenceTier {
  const v = (value ?? '').toLowerCase()
  return (TIER_ORDER as string[]).includes(v) ? (v as ConfidenceTier) : 'low'
}

const TIER_LABEL_KEY: Record<ConfidenceTier, string> = {
  high: 'confidence.high',
  medium: 'confidence.medium',
  low: 'confidence.low',
  very_low: 'confidence.veryLow',
}

const TIER_VISUAL: Record<ConfidenceTier, { opacity: number; glow: string; bandFactor: number }> = {
  high: {
    opacity: 1,
    glow: '0 0 16px color-mix(in srgb, var(--primary) 40%, transparent)',
    bandFactor: 0.25,
  },
  medium: {
    opacity: 0.92,
    glow: '0 0 12px color-mix(in srgb, var(--primary) 26%, transparent)',
    bandFactor: 0.5,
  },
  low: {
    opacity: 0.8,
    glow: '0 0 8px color-mix(in srgb, var(--primary) 16%, transparent)',
    bandFactor: 0.75,
  },
  very_low: { opacity: 0.68, glow: 'none', bandFactor: 1 },
}

/** Resolve the chip rendering for a confidence tier (label + non-hue glow). */
export function confidenceChip(
  tier: ConfidenceTier | string | null | undefined,
  locale?: Locale,
): ConfidenceChip {
  void locale
  const t = normalizeConfidence(typeof tier === 'string' ? tier : null)
  const visual = TIER_VISUAL[t]
  return { label: tSync(TIER_LABEL_KEY[t]), ...visual }
}
