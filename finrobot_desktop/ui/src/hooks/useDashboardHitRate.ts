// useDashboardHitRate — pulls /api/dashboard/hit-rate for the landing banner.
//
// Window switcher (30d/90d/all) lives in the consuming component; the hook
// just takes the chosen window and verdict filter, hands them to react-query,
// and surfaces the response shape verbatim.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'

export type HitRateWindow = '30d' | '90d' | 'all'
export type VerdictFilter = 'BUY' | 'HOLD' | 'SELL' | 'all'

export interface HitRateBucket {
  n_total: number
  n_closed: number
  n_hit: number
  hit_rate: number | null
}

export interface HitRateOverview {
  window: HitRateWindow
  sample_window_days: number | null
  overall: HitRateBucket
  by_verdict: Record<'BUY' | 'HOLD' | 'SELL', HitRateBucket>
  generated_at: string
}

export function useDashboardHitRate(
  window: HitRateWindow = 'all',
  verdictFilter: VerdictFilter = 'all',
) {
  return useQuery<HitRateOverview>({
    queryKey: ['dashboard', 'hit-rate', window, verdictFilter],
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({ window, verdict_filter: verdictFilter })
      const r = await fetch(`${BASE_URL}/api/dashboard/hit-rate?${params}`, { signal })
      if (!r.ok) throw new Error(`hit-rate HTTP ${r.status}`)
      return r.json() as Promise<HitRateOverview>
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 1,
  })
}
