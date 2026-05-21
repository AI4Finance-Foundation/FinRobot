// v5 frontend types. Kept in a dedicated file so we don't have to touch
// `hooks/useTickerData.ts` (which still carries the pre-v5 ArtifactSummary
// shape used by HistoryTab and friends). Once those legacy callers are
// migrated to /stock/:ticker (PR15), we can fold this back in.

export type ArtifactType =
  | 'dcf'
  | 'lbo'
  | 'comps'
  | 'ddm'
  | 'earnings'
  | 'ic_memo'
  | 'equity_research'
  | 'peer_research'
  | 'ad_hoc'
  | 'earnings_analysis'
  | 'playground_snapshot'

export type Signal = 'hit' | 'watching' | 'failed'

/** Mirror of `finagent.artifact.models.ArtifactSummary` (PR1 ADR-0001). */
export interface ArtifactSummaryV5 {
  id: string
  ticker: string | null
  cross_tickers: string[]
  type: ArtifactType
  created_at: string
  headline: string
  source: string
  archived: boolean

  // v5 PR1 additions — backend populates from artifact.outputs.structured.
  // null when the artifact pre-dates v5 or its pipeline doesn't have a thesis.
  entry_price: number | null
  target_price: number | null
  target_date: string | null
  signal: Signal | null
}

/** Mirror of `engine.compute.signal.HitRateStats` (PR1). */
export interface HitRateStats {
  n_total: number
  n_closed: number
  n_hit: number
  hit_rate: number | null
  avg_excess_return: number | null
}

/** Mirror of `engine.compute.valuation_aggregator.ValuationMethodRange` (PR2). */
export type ValuationMethodName =
  | 'dcf'
  | 'comps_pe'
  | 'lbo'
  | 'ddm'
  | 'ev_ebitda'
  | 'p_fcf'

export interface ValuationMethodRange {
  method: ValuationMethodName
  method_type: 'valuation' | 'multiple'
  low: number
  mid: number
  high: number
  confidence: number
  source: string
  warnings: string[]
}

export interface ValuationAggregate {
  ticker: string
  current_price: number | null
  as_of: string
  methods: ValuationMethodRange[]
  warnings: string[]
}

/** Mirror of historical bands response (PR3). */
export type HistoricalMetric = 'ev_ebitda' | 'p_fcf'

export interface HistoricalBandPoint {
  date: string
  value: number
}

export interface HistoricalBandResponse {
  ticker: string
  metric: HistoricalMetric
  current: number | null
  median: number | null
  p25: number | null
  p75: number | null
  p90: number | null
  timeline: HistoricalBandPoint[]
  sample_count: number
  classification: 'expensive' | 'fair' | 'cheap' | 'unknown'
  warnings: string[]
}

/** Mirror of sentiment endpoint (PR4b §6.12). */
export interface SentimentSnapshot {
  ticker: string
  days: number
  available: boolean
  coverage: string | null
  bullish_pct: number | null
  bearish_pct: number | null
  average_buzz: number | null
  source_alignment: string | null
  sources: {
    platform: string
    has_data: boolean
    bullish_pct: number | null
    activity_label: string
    activity_value: number | null
  }[]
  warnings: string[]
}
