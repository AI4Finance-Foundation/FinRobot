// useCoverage — TanStack Query hooks over the surfaced Coverage API. Server
// state (system group / overview / compare) lives here; local sort density lives
// in coverageStore. Opening a ticker auto-enrols it into Studied Tickers.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  coverageApi,
  type CoverageGroupSummary,
  type CoverageGroupDetail,
  type CoverageOverview,
  type ComparisonResult,
} from '../api/coverage'

const KEYS = {
  groups: ['coverage', 'groups'] as const,
  overview: (id: string) => ['coverage', 'overview', id] as const,
  compare: (tickers: string[]) => ['coverage', 'compare', tickers.join(',')] as const,
}

export function useCoverageGroups() {
  return useQuery<CoverageGroupSummary[]>({
    queryKey: KEYS.groups,
    queryFn: () => coverageApi.listGroups(),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })
}

export interface CoverageOverviewState {
  data: CoverageOverview | undefined
  isLoading: boolean
  isError: boolean
  /** Showing the fast skeleton while the full (market) fetch is unresolved —
   *  in flight OR failed-with-fallback. Market cells render as loading, not as
   *  missing; an outright '—' here would be indistinguishable from "no data". */
  marketPending: boolean
  /** The full (market) fetch FAILED while the fast skeleton stands in. Market
   *  columns keep shimmering (marketPending stays true) and the page surfaces a
   *  retry affordance wired to refetch() (BUG-032). */
  marketError: boolean
  /** Re-run the full fetch — used by the error-state retry (BUG-051) and the
   *  market-degraded retry bar (BUG-032). */
  refetch: () => void
}

/**
 * Two-phase overview: a fast skeleton (research + run state, local SQLite ~ms)
 * paints the table instantly, then the full fetch backfills market/valuation.
 * The fast query nests under the full key so member-mutation invalidations
 * (prefix-matched on `['coverage','overview',id]`) hit both phases.
 */
export function useCoverageOverview(groupId: string | null): CoverageOverviewState {
  const full = useQuery<CoverageOverview>({
    queryKey: KEYS.overview(groupId ?? ''),
    queryFn: () => coverageApi.overview(groupId as string),
    enabled: !!groupId,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })
  const fast = useQuery<CoverageOverview>({
    queryKey: [...KEYS.overview(groupId ?? ''), 'fast'],
    queryFn: () => coverageApi.overview(groupId as string, false, true),
    // Only needed until the full table lands; never refetches once full has data.
    enabled: !!groupId && !full.data,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })
  const data = full.data ?? fast.data
  return {
    data,
    isLoading: !data && full.isLoading,
    isError: !data && full.isError,
    // While the full fetch is unresolved (in flight OR failed) but the fast
    // skeleton stands in, keep market cells shimmering rather than collapsing to
    // '—'. Dropping the old `&& !full.isError` term is the whole BUG-032 fix:
    // previously a full-fetch failure turned every market column into a silent
    // '—' (looked like "no data"); now it stays a loading placeholder and the
    // page offers a retry via marketError below.
    marketPending: !full.data && !!fast.data,
    // Full fetch failed but the fast skeleton kept the table alive — market data
    // is unavailable (not merely slow). Drives the degraded retry bar.
    marketError: !full.data && full.isError && !!fast.data,
    refetch: () => void full.refetch(),
  }
}

export function useCompare(tickers: string[], enabled: boolean) {
  return useQuery<ComparisonResult>({
    queryKey: KEYS.compare(tickers),
    queryFn: () => coverageApi.compare(tickers),
    enabled: enabled && tickers.length >= 2,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })
}

/**
 * Auto-add an opened ticker to the default Studied Tickers workspace.
 * Fired once per successful /stocks/:ticker open (the search → workspace
 * contract). Idempotent server-side, so re-opens are cheap no-ops. Invalidates
 * the group list (member_count) + every overview (the studied group's table
 * gains a row); we don't know the studied group's id here, so the broad
 * `['coverage','overview']` prefix covers it without threading the id through.
 */
export function useAddStudiedTicker() {
  const qc = useQueryClient()
  return useMutation<CoverageGroupDetail, Error, string>({
    mutationFn: (ticker) => coverageApi.addStudiedTicker(ticker),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.groups })
      qc.invalidateQueries({ queryKey: ['coverage', 'overview'] })
    },
  })
}
