// useCoverage — TanStack Query hooks over the surfaced Coverage API. Server
// state (system group / overview) lives here; local sort density lives in
// coverageStore. Opening a ticker auto-enrols it into Studied Tickers.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  coverageApi,
  type CoverageGroupSummary,
  type CoverageGroupDetail,
  type CoverageOverview,
} from '../api/coverage'

const KEYS = {
  groups: ['coverage', 'groups'] as const,
  overview: (id: string) => ['coverage', 'overview', id] as const,
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
  /** The background network revalidate is in flight. Drives the global
   *  "refreshing" affordance; the card shimmers ONLY its cold cells (no snapshot
   *  yet) — rows that already hold a stale snapshot show their last-known value
   *  with a refreshing hint, never a blank shimmer. */
  marketPending: boolean
  /** The revalidate FAILED while the cache-only paint stands in — market numbers
   *  are the last-known snapshot (possibly stale), not fresh. The page surfaces a
   *  retry affordance wired to refetch() (BUG-032). */
  marketError: boolean
  /** Re-run the network revalidate — used by the error-state retry (BUG-051) and
   *  the market-degraded retry bar (BUG-032). */
  refetch: () => void
}

/**
 * Stale-while-revalidate overview. Phase 1 (`refresh=false`) is the instant
 * cache-only paint: the server reads the canonical cache (allow-stale, no
 * network) so the desk fills in ~ms at any N — no more waiting on the cold
 * provider fan-out (measured 6.6s/6 tickers, >180s/100). Phase 2 (`refresh=true`)
 * is the background network revalidate: a bounded fan-out repopulates the cache
 * and returns fresh numbers, swapped into the primary view. The revalidate query
 * nests under the primary key so member-mutation invalidations (prefix-matched on
 * `['coverage','overview',id]`) hit both phases.
 */
export function useCoverageOverview(groupId: string | null): CoverageOverviewState {
  const cached = useQuery<CoverageOverview>({
    queryKey: KEYS.overview(groupId ?? ''),
    queryFn: () => coverageApi.overview(groupId as string, false),
    enabled: !!groupId,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })
  const fresh = useQuery<CoverageOverview>({
    queryKey: [...KEYS.overview(groupId ?? ''), 'fresh'],
    queryFn: () => coverageApi.overview(groupId as string, true),
    // Fire once the instant paint has landed; the network result then supersedes
    // the cache-only snapshot.
    enabled: !!groupId && !!cached.data,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })
  const data = fresh.data ?? cached.data
  return {
    data,
    isLoading: !data && cached.isLoading,
    isError: !data && cached.isError,
    // Background revalidate in flight (and not yet resolved). The card uses this
    // together with per-row market_stale/price to decide shimmer (cold) vs
    // refreshing-hint (stale snapshot present).
    marketPending: !fresh.data && fresh.isFetching,
    // Revalidate failed but the cache-only paint kept the table alive — the
    // numbers are last-known, not fresh. Drives the degraded retry bar.
    marketError: !fresh.data && fresh.isError && !!cached.data,
    refetch: () => void fresh.refetch(),
  }
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
