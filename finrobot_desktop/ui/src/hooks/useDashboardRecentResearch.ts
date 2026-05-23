// useDashboardRecentResearch — pulls /api/dashboard/recent-research.
//
// 2026-05-23 (v2): drawer cards. Each card is one ticker; the ticker's
// recent runs come back as `runs` rows the UI routes individually to
// /stocks/:ticker/runs/:artifact_id so every report is directly clickable.
// `runs` is capped backend-side at MAX_RUNS_PER_TICKER (5); `run_count`
// carries the true total so the UI can render an overflow footer.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { FetchHttpError } from '../utils/errorMessage'

export type Signal = 'hit' | 'watching' | 'failed'

export interface RecentTickerRun {
  artifact_id: string
  type: string
  verdict: 'BUY' | 'HOLD' | 'SELL' | null
  created_at: string
  age_label: string
}

export interface RecentTickerItem {
  ticker: string
  run_count: number
  runs: RecentTickerRun[]
  latest_signal: Signal | null
  latest_at: string
}

export interface RecentResearchResponse {
  items: RecentTickerItem[]
  total_in_store: number
  distinct_ticker_count: number
  generated_at: string
}

export function useDashboardRecentResearch(limit = 5) {
  return useQuery<RecentResearchResponse>({
    queryKey: ['dashboard', 'recent-research', limit],
    queryFn: async ({ signal }) => {
      const r = await fetch(
        `${BASE_URL}/api/dashboard/recent-research?limit=${limit}`,
        { signal },
      )
      if (!r.ok) throw new FetchHttpError(r.status, r.statusText)
      return r.json() as Promise<RecentResearchResponse>
    },
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 1,
  })
}
