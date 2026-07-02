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
import { extractErrorDetail } from '../api/errors'
import { fetchWithTimeout } from '../api/fetch'
import { FetchHttpError } from '../utils/errorMessage'
import type { SentimentSnapshot } from '../types/v5'

export type { SentimentSnapshot } from '../types/v5'

/** Fetch retail sentiment for a ticker. Resolves with the backend snapshot on a
 *  2xx (the `reason` field tells the UI why it's unavailable); throws on a
 *  non-2xx or network/timeout so the consumer can render a retry, never a
 *  misleading "not configured". */
export async function fetchSentimentSnapshot(
  ticker: string,
  days = 7,
  signal?: AbortSignal,
): Promise<SentimentSnapshot> {
  const r = await fetchWithTimeout(`${BASE_URL}/api/sentiment/${ticker}?days=${days}`, {
    signal,
  })
  if (!r.ok) {
    throw new FetchHttpError(r.status, r.statusText, await extractErrorDetail(r, ''))
  }
  return (await r.json()) as SentimentSnapshot
}

export function useTickerSentiment(ticker: string, days = 7) {
  return useQuery<SentimentSnapshot, FetchHttpError | Error>({
    queryKey: ['ticker-sentiment', ticker, days],
    queryFn: ({ signal }) => fetchSentimentSnapshot(ticker, days, signal),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    refetchOnMount: false,
    retry: 1,
    // When the upstream is rate-limiting us (429), the backend's circuit breaker
    // cools down on its own — so poll (a touch above the 60s base cooldown) to
    // pick the data back up automatically once it clears. Makes the card's
    // "auto-retrying" copy truthful; any other state polls never.
    refetchInterval: (query) => (query.state.data?.reason === 'rate_limited' ? 90_000 : false),
  })
}
