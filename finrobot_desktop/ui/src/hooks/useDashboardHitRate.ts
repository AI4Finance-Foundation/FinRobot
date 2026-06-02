// useDashboardHitRate — pulls /api/dashboard/hit-rate for the landing banner.
//
// Window switcher (30d/90d/all) lives in the consuming component; the hook
// just takes the chosen window, hands it to react-query, and surfaces the
// response shape verbatim.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { fetchWithTimeout } from '../api/fetch'
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

/**
 * @param tickers Pass a coverage group's member symbols to scope the stats to
 *   that group (BUG-055). `undefined` → global (all artifacts); an empty array
 *   scopes to the empty set (an empty group has no track record) — deliberately
 *   distinct from global.
 */
export function useDashboardHitRate(window: HitRateWindow = 'all', tickers?: string[]) {
  const scoped = tickers !== undefined
  const tickerParam = scoped ? tickers.join(',') : null
  return useQuery<HitRateOverview>({
    queryKey: ['dashboard', 'hit-rate', window, scoped ? tickerParam : 'all'],
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({ window })
      if (scoped) params.set('tickers', tickerParam ?? '')
      const r = await fetchWithTimeout(`${BASE_URL}/api/dashboard/hit-rate?${params}`, { signal })
      if (!r.ok) throw new FetchHttpError(r.status, r.statusText)
      return r.json() as Promise<HitRateOverview>
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 1,
  })
}
