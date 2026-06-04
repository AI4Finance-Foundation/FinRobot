// Coverage priority — "does this ticker need the analyst's attention, and how
// urgently?" — DERIVED purely from real CoverageRow fields, never a fabricated
// backend score (audit decision §23). The backend already encodes every actionable
// signal in `needs_refresh[]` (never_run / run_failed / signal_closed), plus
// `run_status` and `warnings`; re-deriving a number here just orders them, it
// invents nothing. Pure + DOM-free so the grid, the toolbar count, and tests
// share one definition of "needs action".

import type { CoverageRow } from '../../api/coverage'

// Weight per needs_refresh kind — higher sorts first. A failed run is the most
// actionable (retry it now); a closed signal means the thesis needs a re-read;
// never-run is a gap to fill; the rest (price_drift / degraded / stale) are
// softer nudges. Mirrors the backend's own precedence in service._needs_refresh.
const KIND_WEIGHT: Record<string, number> = {
  run_failed: 100,
  signal_closed: 80,
  never_run: 60,
}
const KIND_WEIGHT_DEFAULT = 40 // price_drift / degraded / stale_catalyst / unknown
const WARNING_WEIGHT = 20 // data-quality warning with no refresh reason

export interface CoveragePriority {
  /** True when the ticker has any actionable reason (drives the Needs Action filter). */
  needsAction: boolean
  /** Urgency score — only meaningful for ordering, 0 = nothing pending. */
  score: number
  /** Human-readable reasons, most-urgent first (refresh reasons then warnings). */
  reasons: string[]
}

export function coveragePriority(row: CoverageRow): CoveragePriority {
  const reasons: string[] = row.needs_refresh.map((r) => r.detail)
  // Warnings are a softer signal but still "look here" — surface them after the
  // structured refresh reasons so the inspector/list can show the full picture.
  for (const w of row.warnings) if (!reasons.includes(w)) reasons.push(w)

  let score = 0
  for (const r of row.needs_refresh) {
    score = Math.max(score, KIND_WEIGHT[r.kind] ?? KIND_WEIGHT_DEFAULT)
  }
  if (score === 0 && row.warnings.length > 0) score = WARNING_WEIGHT

  // A live/created run isn't "needs action" — it's in flight; the Running filter
  // owns it. needsAction is purely the actionable backlog.
  const needsAction = row.needs_refresh.length > 0 || row.warnings.length > 0
  return { needsAction, score, reasons }
}
