// useDashboardHitRate — pulls /api/dashboard/hit-rate for the landing banner.
//
// Window switcher (30d/90d/all) lives in the consuming component; the hook
// just takes the chosen window, hands it to react-query, and surfaces the
// response shape verbatim.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { FetchHttpError } from '../utils/errorMessage'

export type HitRateWindow = '30d' | '90d' | 'all'

export interface HitRateBucket {
  n_total: number
  n_closed: number
  n_hit: number
  hit_rate: number | null
}

export interface HitRateOverview {
  window: HitRateWindow
  overall: HitRateBucket
  by_verdict: Record<'BUY' | 'HOLD' | 'SELL', HitRateBucket>
  generated_at: string
}

export function useDashboardHitRate(window: HitRateWindow = 'all') {
  return useQuery<HitRateOverview>({
    queryKey: ['dashboard', 'hit-rate', window],
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({ window })
      const r = await fetch(`${BASE_URL}/api/dashboard/hit-rate?${params}`, { signal })
      if (!r.ok) throw new FetchHttpError(r.status, r.statusText)
      return r.json() as Promise<HitRateOverview>
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 1,
  })
}
