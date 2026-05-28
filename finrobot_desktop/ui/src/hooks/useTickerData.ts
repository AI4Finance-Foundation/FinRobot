/**
 * useTickerData — TanStack Query hooks for per-ticker server state.
 */

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { fetchWithTimeout } from '../api/fetch'
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
  /** ISO8601 timestamp of when the provider last successfully fetched (wall-clock). */
  fetched_at?: string | null
  /** ISO date (YYYY-MM-DD) of the latest price bar — the session current_price represents.
   *  The freshness pill binds to THIS, not fetched_at, so a closed-market view can't
   *  claim "near-real-time" over a prior session's closing price. */
  as_of?: string | null
  /** Which provider actually served this payload ("fmp" / "yfinance" / "<provider>:provider-cache"). */
  data_source?: string | null
}

// Mirror of finrobot.engine.models.financial.FinancialData — backend nests
// values under income / balance / market / valuation buckets. Tile readers
// must traverse the nested path; e.g. market cap lives at
// `financials.market.market_cap`, NOT at the root.
export interface FinancialsData {
  ticker?: string
  company_name?: string | null
  timestamp?: string
  /** TTM period end (the data's semantic date), e.g. "2026-03-31". */
  fiscal_period_end?: string | null
  /** Source + freshness + degradation flags (ADR-0004). */
  provenance?: {
    provider?: string
    as_of?: string | null
    period_basis?: string
    pe_ttm_lag_quarters?: number | null
    degraded?: string[]
  } | null
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
    /** EBITDA, operating caliber (EBIT + D&A) — the primary number shown. */
    ebitda_operating?: number | null
    /** EBITDA, street/reported caliber (NI + tax + interest + D&A). */
    ebitda_reported?: number | null
    /** EV/EBITDA on the operating caliber (primary). */
    ev_ebitda?: number | null
    /** EV/EBITDA on the reported caliber (footnote cross-check). */
    ev_ebitda_reported?: number | null
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
 * StockWorkspace's gate can branch on status. 422 means an invalid ticker and
 * stops at TickerNotFoundView; upstream failures are handled inside market
 * data widgets so the AI run/timeline column stays usable.
 *
 * Exported for direct unit testing.
 */
export async function fetchJsonOrThrowHttp<T>(url: string, signal?: AbortSignal): Promise<T> {
  const resp = await fetchWithTimeout(url, { signal })
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
    // No automatic react-query retries. For 422 (invalid ticker) retrying has
    // zero value, and for provider outages the workspace should render with
    // local degraded states instead of a hidden background retry loop.
    retry: false,
  })
}

/** Fetch catalysts for a ticker. */
export function useTickerCatalysts(ticker: string) {
  return useQuery<CatalystEventData[], FetchHttpError>({
    queryKey: ['ticker-catalysts', ticker],
    queryFn: ({ signal }) =>
      fetchJsonOrThrowHttp<CatalystEventData[]>(`${BASE_URL}/api/data/${ticker}/catalysts`, signal),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    refetchOnMount: false,
    // Delegate retry policy to QueryClient defaults (production: 1 retry).
    // Gate-level error handling in StockWorkspace supersedes per-hook retry
    // for the price query; catalysts / financials use the client default.
  })
}

/** Fetch financial data for a ticker. */
export function useTickerFinancials(ticker: string) {
  return useQuery<FinancialsData, FetchHttpError>({
    queryKey: ['ticker-financials', ticker],
    queryFn: ({ signal }) =>
      fetchJsonOrThrowHttp<FinancialsData>(`${BASE_URL}/api/data/${ticker}/financials`, signal),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    refetchOnMount: false,
    // Delegate retry policy to QueryClient defaults (production: 1 retry).
  })
}
