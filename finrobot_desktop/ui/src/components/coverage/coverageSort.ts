// Coverage Table sorting — pure, so it unit-tests without the DOM and the page
// and the store share one definition of "what's sortable" and "how nulls sort".
//
// Missing values (null/undefined) always sink to the bottom regardless of
// direction: an analyst scanning a column wants the real numbers grouped at the
// top, never a wall of "—" pushed up by an ascending sort.

import type { CoverageRow } from '../../api/coverage'

export type CoverageSortKey =
  | 'ticker'
  | 'price'
  | 'change_pct_1d'
  | 'market_cap'
  | 'revenue_ttm'
  | 'ev_ebitda'
  | 'pe'
  | 'upside_to_target_live'
  | 'run_count'

export type SortDir = 'asc' | 'desc'

export interface CoverageSort {
  key: CoverageSortKey
  dir: SortDir
}

// Natural first-click direction: tickers read A→Z, numbers read high→low.
export function defaultDir(key: CoverageSortKey): SortDir {
  return key === 'ticker' ? 'asc' : 'desc'
}

// Toggle within a column, or jump to a new column at its natural direction.
export function nextSort(current: CoverageSort | null, key: CoverageSortKey): CoverageSort {
  if (current && current.key === key) {
    return { key, dir: current.dir === 'desc' ? 'asc' : 'desc' }
  }
  return { key, dir: defaultDir(key) }
}

export function sortCoverageRows(rows: CoverageRow[], sort: CoverageSort | null): CoverageRow[] {
  if (!sort) return rows
  const { key, dir } = sort
  const factor = dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const av = a[key]
    const bv = b[key]
    const aNull = av === null || av === undefined
    const bNull = bv === null || bv === undefined
    if (aNull && bNull) return 0
    if (aNull) return 1 // a sinks regardless of dir
    if (bNull) return -1
    if (key === 'ticker') return factor * String(av).localeCompare(String(bv))
    return factor * ((av as number) - (bv as number))
  })
}
