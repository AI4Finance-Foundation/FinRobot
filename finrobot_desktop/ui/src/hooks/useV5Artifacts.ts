// v5 artifact hooks — read the v5-shaped /api/artifacts endpoints so the
// new section components don't have to depend on the legacy ArtifactSummary
// type in useTickerData.ts.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { FetchHttpError } from '../utils/errorMessage'
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
    throw new FetchHttpError(resp.status, resp.statusText)
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

/** Full artifact (inputs / assumptions / outputs / meta) for a single id.
 *
 * Backed by `GET /api/artifacts/{id}` (defined in routes/artifacts.py). The
 * timeline endpoint only returns ArtifactSummary which strips heavy fields —
 * sections that need outputs.structured.* (risk grid, peer table, sensitivity
 * heatmap) must use this hook. Cached aggressively because artifacts are
 * immutable once written. */
export interface ArtifactDetail {
  id: string
  ticker: string | null
  type: string
  created_at: string
  // The outputs blob is intentionally unknown — each pipeline writes its own
  // structured shape; section components down-cast to the contract they care
  // about. Keeping it `unknown` here forces every consumer to define their
  // own narrow type and avoids accidental field drift across sections.
  outputs: Record<string, unknown>
  inputs: Record<string, unknown>
  assumptions: Record<string, unknown>
  meta: Record<string, unknown>
}

export function useArtifactDetail(artifactId: string | null | undefined) {
  return useQuery<ArtifactDetail, Error>({
    queryKey: ['artifact-detail', artifactId],
    queryFn: ({ signal }) =>
      getJson<ArtifactDetail>(`${BASE_URL}/api/artifacts/${artifactId}`, signal),
    enabled: !!artifactId,
    staleTime: Infinity, // artifacts are immutable once written
    refetchOnMount: false,
    retry: 1,
  })
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
