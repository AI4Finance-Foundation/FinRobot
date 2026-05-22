// useDashboardRecentResearch — pulls /api/dashboard/recent-research.
//
// Top-N artifacts with live signal + delta-to-target. Used by the landing
// page horizontal strip.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'

export type Signal = 'hit' | 'watching' | 'failed'

export interface RecentResearchItem {
  artifact_id: string
  ticker: string | null
  cross_tickers: string[]
  type: string
  headline: string
  verdict: 'BUY' | 'HOLD' | 'SELL' | null
  entry_price: number | null
  target_price: number | null
  current_price: number | null
  delta_to_target_pct: number | null
  signal: Signal | null
  created_at: string
  age_label: string
}

export interface RecentResearchResponse {
  items: RecentResearchItem[]
  total_in_store: number
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
      if (!r.ok) throw new Error(`recent-research HTTP ${r.status}`)
      return r.json() as Promise<RecentResearchResponse>
    },
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 1,
  })
}
