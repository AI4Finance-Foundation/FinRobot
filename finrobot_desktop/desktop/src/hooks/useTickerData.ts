/**
 * useTickerData — TanStack Query hooks for per-ticker server state.
 */

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { extractErrorDetail } from '../api/errors'
import { fetchWithTimeout, HEAVY_API_TIMEOUT_MS } from '../api/fetch'
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

/** Deterministic trend snapshot computed by engine.compute.market.technical_payload
 *  from the same price bars the chart renders. `available: false` carries a
 *  `reason` ("insufficient_history" | "no_data") instead of the numeric fields. */
export interface Technicals {
  available: boolean
  reason?: string
  trend?: 'uptrend' | 'downtrend' | 'sideways'
  current_price?: number
  sma20?: number | null
  sma50?: number | null
  sma200?: number | null
  /** 52-week high/low from intraday extremes (Yahoo/Bloomberg convention). */
  high_52w?: number
  low_52w?: number
  /** (current − low) / (high − low), 0..1; null when high == low. */
  range_position?: number | null
}

export interface PriceData {
  ticker: string
  // current_price comes from provider; can be null when the upstream feed
  // hasn't returned a recent quote (extended hours, halted, fresh listing).
  current_price: number | null
  /** Native quote currency of current_price. The canonical PRICE snapshot is
   *  NEVER FX-normalized, so for a foreign LOCAL listing (2330.TW) this is the
   *  exchange currency (TWD), NOT USD. Consumers comparing the live price against
   *  a USD-based artifact target (the verdict gauge) MUST check this and abstain
   *  on a non-USD tag — the client cannot run FX. Absent (legacy/stale cache) ⇒
   *  treat as USD (the US-majority no-op). */
  quote_currency?: string | null
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
  /** Backend's session classification, computed in the exchange's timezone:
   *  'live' = US regular session in progress (current_price is intraday);
   *  'closed' = market closed (current_price is the close of the as_of session).
   *  The pill reads THIS instead of comparing as_of to the viewer's local date,
   *  which would mislabel a live quote as a close across timezone boundaries. */
  session_state?: 'live' | 'closed' | null
  /** Which provider actually served this payload ("fmp" / "yfinance" / "<provider>:provider-cache"). */
  data_source?: string | null
  /** Free-text degradation notices from the data layer (e.g. grafted stale
   *  history when the live source served quote-only). Rendered under the
   *  price-trend card — a degraded chart must be visibly degraded. */
  warnings?: string[]
  /** SMA stack + trend + 52w range snapshot from the price bars. */
  technicals?: Technicals
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
  // Cluster size from near-duplicate merging (>1 ⇒ this event aggregates that
  // many distinct source stories). 1/absent for a single-source event.
  source_count?: number | null
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
export async function fetchJsonOrThrowHttp<T>(
  url: string,
  signal?: AbortSignal,
  timeoutMs?: number,
): Promise<T> {
  const resp = await fetchWithTimeout(url, { signal }, timeoutMs)
  if (!resp.ok) {
    // The backend ships a user-facing `detail` on data errors (422 invalid
    // ticker / 502 provider failed / 503 capability unconfigured). Read the
    // body once and carry it into the typed error so mapErrorToUserMessage
    // surfaces the real reason instead of the generic status bucket —
    // mirrors coverage's req() (BUG-053).
    const detail = await extractErrorDetail(resp, '')
    throw new FetchHttpError(resp.status, resp.statusText, detail)
  }
  return resp.json() as Promise<T>
}

// A cold-start 503 ("Data engine is still starting") means the post-yield warmup
// hasn't wired the provider chain yet (~2s after boot, see server.lifespan +
// routes/_ready.py). A live-data query that raced it must retry on THAT timescale,
// not sit in the slow self-heal cadence — otherwise a workspace opened mid-warmup
// shows an error for up to a minute instead of filling in seconds.
const COLD_START_503_RETRY_MS = 2_000

// ── Hooks ─────────────────────────────────────────────────────────────────────

/** Fetch price + change for a ticker. */
export function useTickerPrice(ticker: string) {
  return useQuery<PriceData, FetchHttpError>({
    queryKey: ['ticker-price', ticker],
    queryFn: ({ signal }) =>
      fetchJsonOrThrowHttp<PriceData>(`${BASE_URL}/api/data/${ticker}/price`, signal),
    enabled: !!ticker,
    staleTime: 60_000, // 1 min — price data is volatile
    // 60s normal cadence, but recover in ~2s from a cold-start 503 so a workspace
    // opened during the sidecar warmup window doesn't sit blank for a minute.
    // When the market is closed the price is the frozen session close and won't
    // move — poll far less often (5 min) to save requests/battery.
    refetchInterval: (query) => {
      if (query.state.error?.status === 503) return COLD_START_503_RETRY_MS
      return query.state.data?.session_state === 'closed' ? 300_000 : 60_000
    },
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
    // Heavy endpoint: fetch_news → LLM classify → extract → rank runs ~11–18s
    // server-side, so the default 8s timeout would abort every request before
    // it returns (the calendar then looked permanently empty). Use the 30s
    // heavy budget like the other provider-round-trip endpoints.
    queryFn: ({ signal }) =>
      fetchJsonOrThrowHttp<CatalystEventData[]>(
        `${BASE_URL}/api/data/${ticker}/catalysts`,
        signal,
        HEAVY_API_TIMEOUT_MS,
      ),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
    refetchOnMount: false,
    // Delegate retry policy to QueryClient defaults (production: 1 retry).
    // Gate-level error handling in StockWorkspace supersedes per-hook retry
    // for the price query; catalysts / financials use the client default.
    // Self-heal after a backend outage like the price card does (its 60s
    // refetchInterval keeps firing in error state). Polling this LLM-heavy
    // endpoint while HEALTHY would be wasteful, so the interval only runs
    // while the query sits in error — fast for a cold-start 503, slow otherwise.
    refetchInterval: (query) =>
      query.state.error?.status === 503
        ? COLD_START_503_RETRY_MS
        : query.state.status === 'error'
          ? 60_000
          : false,
  })
}

// Mirror of finrobot.engine.primitives.historical_valuation output — the
// current multiple vs the company's OWN multi-year percentile band. Same shape
// the report freezes into technical_analysis.historical_bands.
export interface HistoricalBand {
  ticker?: string
  metric?: 'ev_ebitda' | 'p_fcf' | string
  current?: number | null
  median?: number | null
  p25?: number | null
  p75?: number | null
  p90?: number | null
  sample_count?: number
  classification?: 'expensive' | 'fair' | 'cheap' | 'unknown'
  // Backend-generated, may be Chinese prose — NOT rendered raw in the EN UI.
  warnings?: string[]
}

/** Fetch the current multiple vs its own multi-year band (EV/EBITDA · P/FCF).
 *  Powers the workspace "vs own history" card — Koyfin's signature, pre-report.
 *  Cheap + server-cached for studied tickers; cold tickers compute under the
 *  heavy budget. Bands move slowly (annual percentiles) → long staleTime. */
export function useTickerHistoricalBands(ticker: string) {
  return useQuery<HistoricalBand, FetchHttpError>({
    queryKey: ['ticker-historical-bands', ticker],
    queryFn: ({ signal }) =>
      fetchJsonOrThrowHttp<HistoricalBand>(
        `${BASE_URL}/api/valuation/historical-bands/${ticker}`,
        signal,
        HEAVY_API_TIMEOUT_MS,
      ),
    enabled: !!ticker,
    staleTime: 30 * 60_000,
    refetchOnMount: false,
    retry: false,
    // Recover from a cold-start 503 (engine warming); bands are otherwise static
    // enough to not poll. Without this a workspace opened mid-warmup left the
    // "vs own history" card stuck in error until a manual remount.
    refetchInterval: (query) =>
      query.state.error?.status === 503 ? COLD_START_503_RETRY_MS : false,
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
    // Error-only self-heal interval — see useTickerCatalysts above. Without it
    // a backend blip froze this card on the error state forever while the
    // price card (60s interval) recovered by itself. Fast on a cold-start 503.
    refetchInterval: (query) =>
      query.state.error?.status === 503
        ? COLD_START_503_RETRY_MS
        : query.state.status === 'error'
          ? 60_000
          : false,
  })
}
