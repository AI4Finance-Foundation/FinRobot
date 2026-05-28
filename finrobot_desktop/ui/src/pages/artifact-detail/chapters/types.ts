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

// ---------------------------------------------------------------------------
// SEC ownership & governance — Chapter 12 read model
// Mirrors finrobot.engine.models.sec.* with read-only field subsets. Keep in
// sync when models change. Provenance is required on every datum (matches
// CLAUDE.md "数字溯源" contract).
// ---------------------------------------------------------------------------

export interface FilingProvenanceShape {
  form: string // "10-K" / "10-Q" / "8-K" / "4" / "13F-HR" / "DEF 14A"
  filing_date: string // ISO date
  accession_no: string
  period_of_report?: string | null
  source_url?: string | null
}

/** Canonical insider transaction types (matches Form 4 transaction codes in
 * finrobot/engine/models/sec.py — keep these two in lockstep). Anything
 * outside this union signals a backend mapping miss and surfaces as the raw
 * value in the UI (the `transactionLabel` fallback). */
export type InsiderTransactionType =
  | 'sale'
  | 'purchase'
  | 'exercise'
  | 'other_disposition'
  | 'grant'
  | 'award'

export interface InsiderTransactionShape {
  filing_date: string
  accession_no: string
  insider_name: string
  insider_position?: string | null
  transaction_type: InsiderTransactionType | string
  code: string
  shares: number
  value: number
  price_per_share?: number | null
  security_type?: string
  security_title?: string
  footnote_ids?: string
  footnotes_text?: string
  provenance: FilingProvenanceShape
}

export interface InstitutionalHoldingShape {
  holder_name: string
  holder_cik?: string | null
  cusip: string
  name_of_issuer: string
  title_of_class?: string
  shares: number
  value_usd: number
  period_end: string
  shares_change_pct?: number | null
  provenance: FilingProvenanceShape
}

export interface ProxyCompensationShape {
  filing_date: string
  accession_no: string
  ceo_name?: string | null
  ceo_total_compensation?: number | null
  ceo_yoy_change_pct?: number | null
  ceo_pay_ratio?: number | null
  top5_neo_total_compensation?: number | null
  peer_percentile?: number | null
  provenance: FilingProvenanceShape
}

export interface ScheduleThirteenAlertShape {
  filer_name: string
  filer_cik?: string | null
  filing_date: string
  accession_no: string
  schedule_type: '13D' | '13G' | string
  shares: number
  pct_of_class?: number | null
  transaction_summary?: string
}

export type OwnershipDegradedReason =
  | 'identity_missing'
  | 'no_recent_filings'
  | 'fetch_error'
  | 'parse_failed'

export interface OwnershipGovernanceShape {
  insider_transactions?: InsiderTransactionShape[]
  institutional_holdings?: InstitutionalHoldingShape[]
  proxy_compensation?: ProxyCompensationShape | null
  schedule13_alerts?: ScheduleThirteenAlertShape[]
  generated_at?: string
  degraded_sections?: string[]
  // ^ e.g. ["institutional_holdings"] when sec_holdings_cache is empty.
  degraded_reasons?: Partial<Record<string, OwnershipDegradedReason>>
  // ^ section key (matches degraded_sections entries) → reason code.
  // UI maps reason → i18n key for accurate messaging instead of one-size-fits-all.
}

// SEC filings + XBRL — read by other chapters (e.g. ChapterFinancialData
// shows 10-K section linkbacks) but typed here so the artifact contract
// lives in one place.

export interface SecFilingSectionShape {
  title: string
  canonical_id: string
  text: string
  char_count: number
  extracted_via?: 'edgartools_attribute' | 'filing_text_fallback' | string
}

export interface SecFilingShape {
  form: string
  filing_date: string
  period_of_report?: string | null
  accession_no: string
  source_url?: string | null
  sections?: SecFilingSectionShape[]
  full_text_char_count?: number
  is_amended?: boolean
  sections_extraction_quality?: 'ok' | 'fallback_to_full_text' | 'amended_redirected' | string
}

export interface SecEvent8KShape {
  filing_date: string
  period_of_report?: string | null
  accession_no: string
  items?: string[]
  items_with_description?: string[]
  text?: string
  source_url?: string | null
}

export interface SecFilingsShape {
  '10k'?: SecFilingShape | null
  '10q_history'?: SecFilingShape[]
  '8k_events'?: SecEvent8KShape[]
}

// XBRL is a sparse bag keyed by us-gaap concept; chapters that need a
// specific tag dig in by name.
export type XbrlFactsSnapshotShape = Record<string, unknown>

export interface ArtifactStructured {
  thesis?: ThesisShape
  financial_modeling?: DcfShape
  peer_analysis?: PeerCompsShape
  catalyst_analysis?: CatalystAnalysisShape
  technical_analysis?: TechnicalAnalysisShape
  ownership_governance?: OwnershipGovernanceShape
  sec_filings?: SecFilingsShape
  xbrl_facts_snapshot?: XbrlFactsSnapshotShape
}
