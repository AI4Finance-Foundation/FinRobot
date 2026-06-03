// Coverage filters — the toolbar's quick lenses over the card wall. Pure +
// DOM-free so the page and tests agree on what each filter means. Every lens is
// derived from real CoverageRow fields (no fabricated state).

import type { CoverageRow } from '../../api/coverage'
import { coveragePriority } from './coveragePriority'

// Three triage lenses only. The old has_reports / not_run pills were cut — the
// card already self-reports those states (research count vs "暂无研报"), so a
// dedicated filter was redundant chrome. Needs Action is the default landing.
export type CoverageFilter = 'all' | 'needs_action' | 'running'

export const COVERAGE_FILTERS: CoverageFilter[] = ['all', 'needs_action', 'running']

// A run that has started but not finished — created or running. Matches the
// backend RunStatus values; 'completed' / 'failed' are terminal, not "running".
function isRunning(row: CoverageRow): boolean {
  return row.run_status === 'running' || row.run_status === 'created'
}

export function matchesFilter(row: CoverageRow, filter: CoverageFilter): boolean {
  switch (filter) {
    case 'all':
      return true
    case 'needs_action':
      return coveragePriority(row).needsAction
    case 'running':
      return isRunning(row)
  }
}

export function filterRows(rows: CoverageRow[], filter: CoverageFilter): CoverageRow[] {
  if (filter === 'all') return rows
  return rows.filter((r) => matchesFilter(r, filter))
}
