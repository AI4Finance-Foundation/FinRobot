/**
 * useTickerData — TanStack Query hooks for per-ticker server state.
 *
 * All hooks accept an optional AbortSignal so the caller can cancel inflight
 * requests when the ticker changes (AbortController pattern).
 */

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface PricePoint {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface PriceData {
  ticker: string
  current_price: number
  change: number
  change_pct: number
  market_cap: number | null
  company_name: string | null
  history?: PricePoint[]  // backend always returns this; typed optional for safety
}

export interface ArtifactSummary {
  id: string
  ticker: string
  type: string
  created_at: string
  last_viewed_at: string | null
  is_archived: boolean
  title: string | null
}

// ── Fetcher helpers ───────────────────────────────────────────────────────────

async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const resp = await fetch(url, { signal })
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}: ${resp.url}`)
  }
  return resp.json() as Promise<T>
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

/** Fetch price + change for a ticker. */
export function useTickerPrice(ticker: string) {
  return useQuery<PriceData, Error>({
    queryKey: ['ticker-price', ticker],
    queryFn: ({ signal }) =>
      fetchJson<PriceData>(`${BASE_URL}/api/data/${ticker}/price`, signal),
    enabled: !!ticker,
    staleTime: 60_000,      // 1 min — price data is volatile
    refetchInterval: 60_000,
    retry: 2,
  })
}

/** Fetch the artifact timeline for a ticker (history tab). */
export function useTickerArtifacts(ticker: string) {
  return useQuery<ArtifactSummary[], Error>({
    queryKey: ['ticker-artifacts', ticker],
    queryFn: ({ signal }) =>
      fetchJson<ArtifactSummary[]>(
        `${BASE_URL}/api/artifacts/by-ticker/${ticker}/timeline`,
        signal,
      ),
    enabled: !!ticker,
    staleTime: 30_000,
    retry: 1,
  })
}

/** Fetch catalysts for a ticker. */
export function useTickerCatalysts(ticker: string) {
  return useQuery({
    queryKey: ['ticker-catalysts', ticker],
    queryFn: ({ signal }) =>
      fetchJson(`${BASE_URL}/api/data/${ticker}/catalysts`, signal),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    retry: 1,
  })
}

/** Fetch financial data for a ticker. */
export function useTickerFinancials(ticker: string) {
  return useQuery({
    queryKey: ['ticker-financials', ticker],
    queryFn: ({ signal }) =>
      fetchJson(`${BASE_URL}/api/data/${ticker}/financials`, signal),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    retry: 1,
  })
}
