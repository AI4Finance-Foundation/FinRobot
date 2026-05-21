// v5 artifact hooks — read the v5-shaped /api/artifacts endpoints so the
// new section components don't have to depend on the legacy ArtifactSummary
// type in useTickerData.ts.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import type {
  ArtifactSummaryV5,
  HistoricalBandResponse,
  HistoricalMetric,
  SentimentSnapshot,
  ValuationAggregate,
} from '../types/v5'

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const resp = await fetch(url, { signal })
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText}`)
  }
  return (await resp.json()) as T
}

/** Timeline of v5 ArtifactSummary entries for one ticker. */
export function useV5ArtifactTimeline(ticker: string) {
  return useQuery<ArtifactSummaryV5[], Error>({
    queryKey: ['v5-artifacts-timeline', ticker],
    queryFn: ({ signal }) =>
      getJson<ArtifactSummaryV5[]>(
        `${BASE_URL}/api/artifacts/by-ticker/${ticker}/timeline`,
        signal,
      ),
    enabled: !!ticker,
    staleTime: 60_000,
    refetchOnMount: false,
  })
}

/** Latest artifact for a ticker filtered by type — convenience derivative. */
export function useLatestArtifact(
  ticker: string,
  type: ArtifactSummaryV5['type'],
) {
  const query = useV5ArtifactTimeline(ticker)
  const latest = query.data?.find((a) => a.type === type) ?? null
  return { ...query, latest }
}

/** Football Field aggregation (PR2 endpoint). */
export function useValuationAggregate(ticker: string) {
  return useQuery<ValuationAggregate, Error>({
    queryKey: ['valuation-aggregate', ticker],
    queryFn: ({ signal }) =>
      getJson<ValuationAggregate>(`${BASE_URL}/api/valuation/aggregate/${ticker}`, signal),
    enabled: !!ticker,
    staleTime: 60_000,
    refetchOnMount: false,
  })
}

/** Historical bands (PR3 endpoint). */
export function useHistoricalBand(
  ticker: string,
  metric: HistoricalMetric = 'ev_ebitda',
  years = 3,
) {
  return useQuery<HistoricalBandResponse, Error>({
    queryKey: ['historical-band', ticker, metric, years],
    queryFn: ({ signal }) =>
      getJson<HistoricalBandResponse>(
        `${BASE_URL}/api/valuation/historical-bands/${ticker}?metric=${metric}&years=${years}`,
        signal,
      ),
    enabled: !!ticker,
    staleTime: 12 * 60 * 60_000, // matches backend 12h cache (PR3)
    refetchOnMount: false,
  })
}

/** Retail sentiment (PR4b endpoint). */
export function useSentimentSnapshot(ticker: string, days = 7) {
  return useQuery<SentimentSnapshot, Error>({
    queryKey: ['sentiment', ticker, days],
    queryFn: ({ signal }) =>
      getJson<SentimentSnapshot>(`${BASE_URL}/api/sentiment/${ticker}?days=${days}`, signal),
    enabled: !!ticker,
    staleTime: 30 * 60_000,
    refetchOnMount: false,
  })
}
