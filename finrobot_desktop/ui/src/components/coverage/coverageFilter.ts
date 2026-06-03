// Coverage filters — the toolbar's quick lenses over the card wall. Pure +
// DOM-free so the page and tests agree on what each filter means. Every lens is
// derived from real CoverageRow fields (no fabricated state).

import type { CoverageRow } from '../../api/coverage'
import { coveragePriority } from './coveragePriority'

export type CoverageFilter = 'all' | 'needs_action' | 'running' | 'has_reports' | 'not_run'

export const COVERAGE_FILTERS: CoverageFilter[] = [
  'all',
  'needs_action',
  'running',
  'has_reports',
  'not_run',
]

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
    // "有研报" / "未跑过" key off research_count (thesis-bearing research), not
    // artifact_count — a ticker with only a DCF model has no report yet, so it
    // belongs in not_run. Mirrors the backend's never_run gate (research_count==0).
    case 'has_reports':
      return row.research_count > 0
    case 'not_run':
      return row.research_count === 0
  }
}

export function filterRows(rows: CoverageRow[], filter: CoverageFilter): CoverageRow[] {
  if (filter === 'all') return rows
  return rows.filter((r) => matchesFilter(r, filter))
}
