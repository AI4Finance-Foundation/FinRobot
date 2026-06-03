// useCoverage — TanStack Query hooks over the Coverage Desk API. Server state
// (groups / overview / compare) lives here; UI state (selection) is in
// coverageStore. Mutations invalidate the queries they affect so the table and
// group list stay live after an edit / batch run.

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
  /** Showing the fast skeleton while the full (market) fetch is in flight —
   *  market cells render as loading, not as missing. */
  marketPending: boolean
  /** Re-run the full fetch — used by the error-state retry (BUG-051). */
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
    marketPending: !full.data && !!fast.data && !full.isError,
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

export function useCreateGroup() {
  const qc = useQueryClient()
  return useMutation<CoverageGroupDetail, Error, { name: string; description?: string }>({
    mutationFn: ({ name, description }) => coverageApi.createGroup(name, description),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.groups }),
  })
}

export function useUpdateGroup() {
  const qc = useQueryClient()
  return useMutation<
    CoverageGroupDetail,
    Error,
    { id: string; name?: string; description?: string }
  >({
    mutationFn: ({ id, name, description }) => coverageApi.updateGroup(id, { name, description }),
    onSuccess: (_d, { id }) => {
      qc.invalidateQueries({ queryKey: KEYS.groups })
      qc.invalidateQueries({ queryKey: KEYS.overview(id) })
    },
  })
}

export function useDeleteGroup() {
  const qc = useQueryClient()
  return useMutation<void, Error, string>({
    mutationFn: (id) => coverageApi.deleteGroup(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.groups }),
  })
}

export function useAddMembers() {
  const qc = useQueryClient()
  return useMutation<CoverageGroupDetail, Error, { id: string; tickers: string[]; note?: string }>({
    mutationFn: ({ id, tickers, note }) => coverageApi.addMembers(id, tickers, note),
    onSuccess: (_d, { id }) => {
      qc.invalidateQueries({ queryKey: KEYS.groups })
      qc.invalidateQueries({ queryKey: KEYS.overview(id) })
    },
  })
}

export function useRemoveMember() {
  const qc = useQueryClient()
  return useMutation<CoverageGroupDetail, Error, { id: string; ticker: string }>({
    mutationFn: ({ id, ticker }) => coverageApi.removeMember(id, ticker),
    onSuccess: (_d, { id }) => {
      qc.invalidateQueries({ queryKey: KEYS.groups })
      qc.invalidateQueries({ queryKey: KEYS.overview(id) })
    },
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

export function useBatchRun() {
  const qc = useQueryClient()
  return useMutation<
    Awaited<ReturnType<typeof coverageApi.batchRun>>,
    Error,
    { id: string; tickers: string[]; pipelineType?: string; language?: string }
  >({
    mutationFn: ({ id, tickers, pipelineType, language }) =>
      coverageApi.batchRun(id, tickers, pipelineType, language),
    // Runs are async (SSE-tracked); refresh the overview so run_status shows.
    onSuccess: (_d, { id }) => qc.invalidateQueries({ queryKey: KEYS.overview(id) }),
  })
}
