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
  // Honesty disclosure (BUG-039/BUG-062): true when the IN-scope, IN-window
  // artifact count exceeded `sample_size`, so the buckets cover only the latest
  // `sample_size` artifacts rather than the full track record. Consumers must
  // surface this (e.g. a "基于最近 N 条样本" caption) so the analyst never reads
  // a truncated hit-rate as the complete record. Backend default is false.
  is_sampled: boolean
  sample_size: number
}

/**
 * Human-readable disclosure caption for a sampled hit-rate, or `null` when the
 * buckets cover the full in-scope/in-window record. Kept here (not in a
 * component) so every banner that renders `HitRateOverview` discloses sampling
 * consistently.
 */
export function hitRateSampleCaption(overview: HitRateOverview | undefined): string | null {
  if (!overview?.is_sampled) return null
  return `基于最近 ${overview.sample_size} 条样本（非完整记录）`
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
