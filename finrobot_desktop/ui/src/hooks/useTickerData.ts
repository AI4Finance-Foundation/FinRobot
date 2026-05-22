/**
 * useTickerData — TanStack Query hooks for per-ticker server state.
 *
 * All hooks accept an optional AbortSignal so the caller can cancel inflight
 * requests when the ticker changes (AbortController pattern).
 */

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { extractErrorDetail } from '../api/errors'

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
  /** Exchange pretty name ("NasdaqGS" / "NYQ" / "AMEX" / …) for the LIVE pill. */
  exchange?: string | null
  /** Next earnings date ISO when yfinance carries it; null/undefined hides the badge. */
  next_earnings_date?: string | null
  history?: PricePoint[]  // backend always returns this; typed optional for safety
}

// Mirror of finagent.engine.models.financial.FinancialData — backend nests
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

// Mirror of finagent.engine.compute.catalyst output. Backend fields:
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

async function fetchJson<T>(
  url: string,
  signal?: AbortSignal,
  errorFallback = '请求失败',
): Promise<T> {
  const resp = await fetch(url, { signal })
  if (!resp.ok) {
    throw new Error(await extractErrorDetail(resp, errorFallback))
  }
  return resp.json() as Promise<T>
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

/** Fetch price + change for a ticker. */
export function useTickerPrice(ticker: string) {
  return useQuery<PriceData, Error>({
    queryKey: ['ticker-price', ticker],
    queryFn: ({ signal }) =>
      fetchJson<PriceData>(`${BASE_URL}/api/data/${ticker}/price`, signal, '无法加载行情'),
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
        '无法加载历史记录',
      ),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    refetchOnMount: false,
    retry: 1,
  })
}

/** Fetch catalysts for a ticker. */
export function useTickerCatalysts(ticker: string) {
  return useQuery<CatalystEventData[], Error>({
    queryKey: ['ticker-catalysts', ticker],
    queryFn: ({ signal }) =>
      fetchJson<CatalystEventData[]>(
        `${BASE_URL}/api/data/${ticker}/catalysts`,
        signal,
        '无法加载催化剂事件',
      ),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    refetchOnMount: false,
    retry: 1,
  })
}

/** Fetch financial data for a ticker. */
export function useTickerFinancials(ticker: string) {
  return useQuery<FinancialsData, Error>({
    queryKey: ['ticker-financials', ticker],
    queryFn: ({ signal }) =>
      fetchJson<FinancialsData>(
        `${BASE_URL}/api/data/${ticker}/financials`,
        signal,
        '无法加载基本面数据',
      ),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    refetchOnMount: false,
    retry: 1,
  })
}
