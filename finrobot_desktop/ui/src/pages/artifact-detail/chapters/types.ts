// Lightweight typed views over artifact.outputs.structured.* dicts.
// The backend ships these as `dict[str, Any]` so the React side narrows
// per-section. Keeping these here (not in shared types/) so the report
// view owns its read model — other consumers should NOT couple to these.

export interface ThesisShape {
  recommendation?: string
  price_target?: number
  price_target_basis?: string
  catalysts?: string[]
  risks?: string[]
  narrative?: string
  tagline?: string | null
  key_takeaways?: string[] | null
  company_overview?: string | null
  valuation_overview?: string | null
  competitor_analysis?: string | null
  news_summary?: string | null
}

export interface DcfShape {
  wacc?: number
  cost_of_equity?: number | null
  projection_years?: number
  projected_revenue?: number[]
  projected_ebitda?: number[]
  projected_fcf?: number[]
  terminal_value?: number
  pv_terminal?: number
  pv_fcf_total?: number
  enterprise_value?: number
  equity_value?: number
  implied_price?: number
  sensitivity_table?: Record<string, unknown> | null
  inputs?: {
    revenue_base?: number
    revenue_growth_rates?: number[]
    ebitda_margin?: number
    terminal_growth_rate?: number
    tax_rate?: number
    beta?: number
    risk_free_rate?: number
    debt_ratio?: number
  }
}

export interface CatalystEventShape {
  category: string
  headline: string
  sentiment: 'positive' | 'negative' | 'neutral'
  impact_score: number
  probability: number
  reasoning?: string
}

export interface CatalystAnalysisShape {
  events?: CatalystEventShape[]
  overall_sentiment?: string
  key_catalysts?: string[]
  net_sentiment?: number
  category_breakdown?: Record<string, number>
  top_positive?: CatalystEventShape[]
  top_negative?: CatalystEventShape[]
}

export interface CompanyFinancialsShape {
  ticker: string
  name?: string | null
  revenue: number
  ebitda: number
  net_income: number
  market_cap: number
  gross_margin: number
  operating_margin: number
  pe_ratio?: number | null
  ev_ebitda?: number | null
  ev_revenue?: number | null
}

export interface PeerCompsShape {
  target?: CompanyFinancialsShape
  peers?: CompanyFinancialsShape[]
  median_ev_ebitda?: number | null
  median_pe?: number | null
  median_ev_revenue?: number | null
  peer_justification?: string
  positioning_narrative?: string
}

export interface MonteCarloShape {
  implied_prices?: number[]
  percentiles?: Record<string, number>
  mean?: number
  std?: number
  current_price_percentile?: number
  histogram_bins?: number[]
  histogram_counts?: number[]
  assumptions_used?: Record<string, unknown>
  n_valid?: number
}

export interface SniperShape {
  ideal_buy?: number
  secondary_buy?: number
  stop_loss?: number
  take_profit?: number
  position_size_pct?: number
  safety_margin?: number
  support_level?: number
  resistance_level?: number
  risk_reward_ratio?: number
}

export interface HistoricalBandShape {
  metric?: 'ev_ebitda' | 'p_fcf' | string
  current?: number | null
  median?: number | null
  p25?: number | null
  p75?: number | null
  p90?: number | null
  timeline?: Array<[string, number]>
  sample_count?: number
  classification?: 'expensive' | 'fair' | 'cheap' | 'unknown'
  warnings?: string[]
}

export interface TechnicalAnalysisShape {
  monte_carlo?: MonteCarloShape | null
  sniper?: SniperShape | null
  historical_bands?: HistoricalBandShape | null
  warnings?: string[]
}

export interface ArtifactStructured {
  thesis?: ThesisShape
  financial_modeling?: DcfShape
  peer_analysis?: PeerCompsShape
  catalyst_analysis?: CatalystAnalysisShape
  technical_analysis?: TechnicalAnalysisShape
}
