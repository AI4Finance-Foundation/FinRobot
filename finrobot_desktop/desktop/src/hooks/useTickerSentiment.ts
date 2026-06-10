// useTickerSentiment — pulls /api/sentiment/{ticker} for the workspace's
// Retail Sentiment card (Adanos: Reddit / X.com / Polymarket aggregate).
//
// Honest failure model. The card has three distinct truths and must never
// conflate them (BUG: a timed-out fetch was rendering as "Adanos not
// configured", sending users who HAD configured it on a wild goose chase):
//   • 200 available:true            → render the aggregate.
//   • 200 available:false, reason   → backend reached a verdict: 'unconfigured'
//     (show the add-key CTA) vs 'provider_error' (key set, call hiccuped → retry).
//   • transport failure / non-2xx   → THROW, so react-query marks the query
//     `isError` and the component shows a retry — instead of caching a fake
//     `available:false` for 5 min that masquerades as "not configured".

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { fetchWithTimeout } from '../api/fetch'
import { FetchHttpError } from '../utils/errorMessage'
import type { SentimentSnapshot } from '../types/v5'

export type { SentimentSnapshot } from '../types/v5'

/** Fetch retail sentiment for a ticker. Resolves with the backend snapshot on a
 *  2xx (the `reason` field tells the UI why it's unavailable); throws on a
 *  non-2xx or network/timeout so the consumer can render a retry, never a
 *  misleading "not configured". */
export function useTickerSentiment(ticker: string, days = 7) {
  return useQuery<SentimentSnapshot, FetchHttpError | Error>({
    queryKey: ['ticker-sentiment', ticker, days],
    queryFn: async ({ signal }) => {
      const r = await fetchWithTimeout(`${BASE_URL}/api/sentiment/${ticker}?days=${days}`, {
        signal,
      })
      if (!r.ok) {
        throw new FetchHttpError(r.status, r.statusText)
      }
      return (await r.json()) as SentimentSnapshot
    },
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    refetchOnMount: false,
    retry: 1,
  })
}
