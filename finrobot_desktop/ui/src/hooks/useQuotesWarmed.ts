// useQuotesWarmed — polls /api/health/quotes-warmed until the lifespan
// QuoteCache warmup task has finished, so the landing page can skeleton
// the dashboard strip instead of triggering a cold dashboard fetch
// during the ~2s warmup window.
//
// Polls at 500ms while `warmed === false`, stops once flipped to true.
// On a fresh boot the warmed bit usually flips within ~3s; on subsequent
// boots within the 60s L2 TTL it is true on the first poll.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { fetchWithTimeout } from '../api/fetch'
import { FetchHttpError } from '../utils/errorMessage'

export interface QuotesWarmedStatus {
  warmed: boolean
  studied_ticker_count: number
}

export function useQuotesWarmed() {
  return useQuery<QuotesWarmedStatus>({
    queryKey: ['quotes-warmed'],
    queryFn: async ({ signal }) => {
      const r = await fetchWithTimeout(`${BASE_URL}/api/health/quotes-warmed`, { signal }, 2_000)
      if (!r.ok) throw new FetchHttpError(r.status, r.statusText)
      return r.json() as Promise<QuotesWarmedStatus>
    },
    // Poll fast while warming up; stop once the flag flips.
    refetchInterval: (q) => (q.state.data?.warmed ? false : 500),
    refetchOnWindowFocus: false,
    staleTime: 0,
    retry: 3,
  })
}
