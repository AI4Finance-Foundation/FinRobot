/**
 * useTickerData — TanStack Query hooks for per-ticker server state.
 */

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { FetchHttpError } from '../utils/errorMessage'

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
  // current_price comes from provider; can be null when the upstream feed
  // hasn't returned a recent quote (extended hours, halted, fresh listing).
  current_price: number | null
  change: number | null
  change_pct: number | null
  market_cap: number | null
  company_name: string | null
  /** Exchange pretty name ("NasdaqGS" / "NYQ" / "AMEX" / …) for the freshness pill. */
  exchange?: string | null
  /** Next earnings date ISO when yfinance carries it; null/undefined hides the badge. */
  next_earnings_date?: string | null
  history?: PricePoint[] // backend always returns this; typed optional for safety
  /** ISO8601 timestamp of when yfinance last successfully fetched. Drives the freshness pill. */
  fetched_at?: string | null
}

// Mirror of finrobot.engine.models.financial.FinancialData — backend nests
// values under income / balance / market / valuation buckets. Tile readers
// must traverse the nested path; e.g. market cap lives at
// `financials.market.market_cap`, NOT at the root.
export interface FinancialsData {
  ticker?: string
  company_name?: string | null
  timestamp?: string
  income?: {
    revenue?: number | null
    ebitda?: number | null
    net_income?: number | null
    gross_margin?: number | null
    operating_margin?: number | null
  }
  balance?: {
    total_debt?: number | null
    total_cash?: number | null
  }
  market?: {
    market_cap?: number | null
    shares_outstanding?: number | null
    current_price?: number | null
    pe_ratio?: number | null
    price_52w_high?: number | null
    price_52w_low?: number | null
    industry?: string | null
    sector?: string | null
    beta?: number | null
  }
  valuation?: {
    enterprise_value?: number | null
    ev_ebitda?: number | null
    ev_revenue?: number | null
  }
  data_source?: string
  warnings?: string[]
}

// Mirror of finrobot.engine.compute.catalyst output. Backend fields:
//   category, headline, sentiment (positive/negative/neutral),
//   impact_score (1..5 integer), probability (0..1), reasoning.
// `title`/`date`/`impact_direction`/`impact_magnitude` are UI-derived from
// these — see deriveCatalystDisplay in CatalystGrid.
export interface CatalystEventData {
  category?: string
  headline?: string
  sentiment?: 'positive' | 'negative' | 'neutral' | string
  impact_score?: number | null
  probability?: number | null
  reasoning?: string
}

// ── Fetcher helpers ───────────────────────────────────────────────────────────

/**
 * Fetch wrapper used by the per-ticker query hooks below.
 *
 * Throws FetchHttpError(status, statusText) on non-2xx responses so
 * StockWorkspace's gate can branch on status (422 → TickerNotFoundView,
 * everything else → ServiceDownView). Plain Error / TypeError / DOMException
 * (network failures, CORS, AbortError) propagate untouched — the gate
 * already routes those into ServiceDownView via the "not instanceof
 * FetchHttpError" branch.
 *
 * Exported for direct unit testing.
 */
export async function fetchJsonOrThrowHttp<T>(
  url: string,
  signal?: AbortSignal,
): Promise<T> {
  const resp = await fetch(url, { signal })
  if (!resp.ok) {
    throw new FetchHttpError(resp.status, resp.statusText)
  }
  return resp.json() as Promise<T>
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

/** Fetch price + change for a ticker. */
export function useTickerPrice(ticker: string) {
  return useQuery<PriceData, FetchHttpError>({
    queryKey: ['ticker-price', ticker],
    queryFn: ({ signal }) =>
      fetchJsonOrThrowHttp<PriceData>(`${BASE_URL}/api/data/${ticker}/price`, signal),
    enabled: !!ticker,
    staleTime: 60_000, // 1 min — price data is volatile
    refetchInterval: 60_000,
    // 422 = invalid ticker → retrying has no value. Other errors keep default (2 retries).
    retry: (failureCount, error) => {
      if (error instanceof FetchHttpError && error.status === 422) return false
      return failureCount < 2
    },
  })
}

/** Fetch catalysts for a ticker. */
export function useTickerCatalysts(ticker: string) {
  return useQuery<CatalystEventData[], FetchHttpError>({
    queryKey: ['ticker-catalysts', ticker],
    queryFn: ({ signal }) =>
      fetchJsonOrThrowHttp<CatalystEventData[]>(
        `${BASE_URL}/api/data/${ticker}/catalysts`,
        signal,
      ),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    refetchOnMount: false,
    // 422 = invalid ticker → retrying has no value.
    retry: (failureCount, error) => {
      if (error instanceof FetchHttpError && error.status === 422) return false
      return failureCount < 1
    },
  })
}

/** Fetch financial data for a ticker. */
export function useTickerFinancials(ticker: string) {
  return useQuery<FinancialsData, FetchHttpError>({
    queryKey: ['ticker-financials', ticker],
    queryFn: ({ signal }) =>
      fetchJsonOrThrowHttp<FinancialsData>(
        `${BASE_URL}/api/data/${ticker}/financials`,
        signal,
      ),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    refetchOnMount: false,
    // 422 = invalid ticker → retrying has no value.
    retry: (failureCount, error) => {
      if (error instanceof FetchHttpError && error.status === 422) return false
      return failureCount < 1
    },
  })
}
