// Coverage triage — the bounded "needs your eyes" derivation for the AI panel's
// triage strip. Pure (DOM-free) so it unit-tests without React, and so the strip
// and any future surface share ONE definition of what counts as an anomaly.
//
// This MIRRORS the backend's deterministic anomaly call-outs in
// finrobot/coverage/prompt.py (`_movers` / `_below_target`) so the chat snapshot
// the LLM sees and the strip the analyst sees flag the exact same names — zero
// caliber drift. The護城河 is that "what counts as a mover" is a deterministic
// number, defined once, never delegated to the LLM. v1 covers the two backend
// classes ONLY (mover, past_target); a "near target" class would add a caliber
// the backend does not have, so it is deliberately omitted (協議第 5 条).
//
// Caliber (must match prompt.py exactly):
//   - change_pct_1d is in percentage POINTS (1.2 ⇒ +1.2%) — never re-scale it.
//   - upside_to_target_live is a FRACTION ((target − live) / live; 0.153 ⇒ +15.3%).

import type { CoverageRow } from '../../api/coverage'

export type TriageKind = 'past_target' | 'mover'

export interface TriageItem {
  row: CoverageRow
  kind: TriageKind
  /** Sort weight within a kind: |upside_to_target_live| for past_target,
   *  |change_pct_1d| for mover. Already absolute, descending = more urgent. */
  magnitude: number
}

// Absolute 1-day % move (percentage points) at/above which a name is a "mover".
// = the backend's `coverage_anomaly_change_threshold` default (3.0, a ~2σ daily
// move for a typical large-cap). Kept in sync with finrobot/config.py.
export const MOVER_THRESHOLD = 3.0

// How many triage cards the strip spells out before collapsing the tail to a
// "+N more" count. Bounds the strip so its height tracks today's anomaly count,
// never the watchlist size N. The strip owns the truncation (so it can show the
// remainder); deriveTriage returns the FULL set.
export const TRIAGE_MAX = 4

/**
 * Derive the triage items for a watchlist, most-urgent first.
 *
 * A row is `past_target` iff its LIVE price has crossed the report target
 * (`upside_to_target_live < 0`), and `mover` iff `|change_pct_1d| >=
 * MOVER_THRESHOLD`. A row satisfying BOTH is classified `past_target` (the more
 * urgent — the thesis itself may be void), never duplicated.
 *
 * Ordering: all `past_target` before all `mover` (a breached thesis outranks a
 * day's noise); within each kind, descending magnitude. Returns EVERY qualifying
 * row — the caller truncates to `TRIAGE_MAX` so it can surface the remainder.
 */
export function deriveTriage(rows: CoverageRow[]): TriageItem[] {
  const items: TriageItem[] = []
  for (const row of rows) {
    const upside = row.upside_to_target_live
    if (upside !== null && upside < 0) {
      // Past target wins outright — do not also consider it a mover.
      items.push({ row, kind: 'past_target', magnitude: Math.abs(upside) })
      continue
    }
    const change = row.change_pct_1d
    if (change !== null && Math.abs(change) >= MOVER_THRESHOLD) {
      items.push({ row, kind: 'mover', magnitude: Math.abs(change) })
    }
  }
  // past_target (kind rank 0) before mover (rank 1); then magnitude desc.
  const rank: Record<TriageKind, number> = { past_target: 0, mover: 1 }
  return items.sort((a, b) => {
    if (a.kind !== b.kind) return rank[a.kind] - rank[b.kind]
    return b.magnitude - a.magnitude
  })
}
