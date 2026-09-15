// Coverage card sorting — pure, so it unit-tests without the DOM, and the page
// and store share one definition of "what's sortable" and "how nulls sort". The
// research-library wall has no sort UI; the page applies one fixed order
// (needs_action desc) so urgent names surface at the top.
//
// Missing values (null/undefined) always sink to the bottom regardless of
// direction: an analyst scanning a column wants the real numbers grouped at the
// top, never a wall of "—" pushed up by an ascending sort.

import type { CoverageRow } from '../../api/coverage'
import { coveragePriority } from './coveragePriority'

export type CoverageSortKey =
  | 'needs_action'
  | 'ticker'
  | 'latest_report'
  | 'upside_to_target_live'
  | 'price'
  | 'change_pct_1d'
  | 'market_cap'
  | 'revenue_ttm'
  | 'ev_ebitda'
  | 'pe'
  | 'artifact_count'

export type SortDir = 'asc' | 'desc'

export interface CoverageSort {
  key: CoverageSortKey
  dir: SortDir
}

// The comparable scalar for a row under a given key. Derived keys
// (needs_action → priority score, latest_report → epoch ms) compute here so the
// sort core stays a single null-aware numeric/string compare.
function sortValue(row: CoverageRow, key: CoverageSortKey): number | string | null {
  if (key === 'needs_action') return coveragePriority(row).score
  if (key === 'latest_report') return row.latest_at ? Date.parse(row.latest_at) : null
  if (key === 'ticker') return row.ticker
  return row[key]
}

export function sortCoverageRows(rows: CoverageRow[], sort: CoverageSort | null): CoverageRow[] {
  if (!sort) return rows
  const { key, dir } = sort
  const factor = dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const av = sortValue(a, key)
    const bv = sortValue(b, key)
    const aNull = av === null || av === undefined || (typeof av === 'number' && Number.isNaN(av))
    const bNull = bv === null || bv === undefined || (typeof bv === 'number' && Number.isNaN(bv))
    if (aNull && bNull) return 0
    if (aNull) return 1 // a sinks regardless of dir
    if (bNull) return -1
    if (key === 'ticker') return factor * String(av).localeCompare(String(bv))
    return factor * ((av as number) - (bv as number))
  })
}
