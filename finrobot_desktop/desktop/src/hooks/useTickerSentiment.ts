// useTickerSentiment — pulls /api/sentiment/{ticker} for the workspace's
// Retail Sentiment card (Adanos: Reddit / X.com / Polymarket aggregate).
//
// Degrades quietly: a backend outage / timeout resolves to `available: false`
// rather than throwing, so the market-data column never blanks out on a
// sentiment hiccup. The "未配置 Adanos" empty state is itself a *successful*
// 200 with `available: false` (see finrobot/routes/sentiment.py), so the
// component branches on `data.available`, not on query error.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { fetchWithTimeout } from '../api/fetch'
import type { SentimentSnapshot } from '../types/v5'

export type { SentimentSnapshot } from '../types/v5'

// Local fallback when the network/fetch itself fails (not a backend 200). We
// surface it as an unavailable snapshot rather than a thrown error so the card
// shows the same "go configure" affordance instead of a red error box.
function unavailable(ticker: string, days: number, warning: string): SentimentSnapshot {
  return {
    ticker,
    days,
    available: false,
    coverage: null,
    bullish_pct: null,
    bearish_pct: null,
    average_buzz: null,
    source_alignment: null,
    sources: [],
    warnings: [warning],
  }
}

/** Fetch retail sentiment for a ticker. Never rejects — failures map to an
 *  `available: false` snapshot so the consumer renders the unconfigured CTA. */
export function useTickerSentiment(ticker: string, days = 7) {
  return useQuery<SentimentSnapshot>({
    queryKey: ['ticker-sentiment', ticker, days],
    queryFn: async ({ signal }) => {
      try {
        const r = await fetchWithTimeout(`${BASE_URL}/api/sentiment/${ticker}?days=${days}`, {
          signal,
        })
        if (!r.ok) {
          return unavailable(ticker, days, `sentiment ${r.status}`)
        }
        return (await r.json()) as SentimentSnapshot
      } catch {
        // Network error / timeout — degrade to the unconfigured-style empty
        // state rather than bubbling a query error into the column.
        return unavailable(ticker, days, 'sentiment fetch failed')
      }
    },
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    refetchOnMount: false,
    retry: 1,
  })
}
