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

export function useCoverageOverview(groupId: string | null) {
  return useQuery<CoverageOverview>({
    queryKey: KEYS.overview(groupId ?? ''),
    queryFn: () => coverageApi.overview(groupId as string),
    enabled: !!groupId,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })
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
