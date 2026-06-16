// Lightweight typed views over artifact.outputs.structured.* dicts.
// The backend ships these as `dict[str, Any]` so the React side narrows
// per-section. Keeping these here (not in shared types/) so the report
// view owns its read model — other consumers should NOT couple to these.

// HistoricalMetrics is the ONE field here that IS a first-class shared type
// (the same model the live ['historical'] path returns) — now FROZEN into the
// artifact, so the read model references the canonical shape rather than
// re-declaring it.
import type { HistoricalMetrics } from '../../../types/finance'

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
  // Reverse-DCF reality check: what growth/WACC the CURRENT market price implies.
  // growth_unreachable=true ⇒ no plausible growth reaches the price (option-value
  // stock); ceiling_price is the most the DCF can reach at growth_ceiling.
  market_implied?: {
    horizon_years: number
    implied_growth?: number | null
    implied_wacc?: number | null
    growth_unreachable: boolean
    growth_ceiling?: number | null
    ceiling_price?: number | null
  } | null
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
  // Source provenance for the chronological news feed (ChapterNews). `published`
  // is an ISO date (null when the source didn't carry one → sorts last); `url`
  // is the source endpoint (finnhub.io = API endpoint, NOT an article page;
  // www.sec.gov = a real filing) — null when source-less. The Catalysts chapter
  // ignores both; the News feed renders an honest source chip from the domain.
  published?: string | null
  url?: string | null
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
  gross_margin: number | null
  operating_margin: number | null
  pe_ratio?: number | null
  ev_ebitda?: number | null
  ev_revenue?: number | null
  // NOPAT core P/E (market_cap / NOPAT). Same caliber the trailing comps_pe
  // valuation target is computed on (peer_median_core_pe × core_eps), so the
  // table can reconcile with the football-field "Comps (core P/E)" row. Filled
  // by calculate_core_pe in the backend; None when operating income / tax was
  // unavailable.
  core_pe_ratio?: number | null
}

export interface PeerCompsShape {
  target?: CompanyFinancialsShape
  peers?: CompanyFinancialsShape[]
  median_ev_ebitda?: number | null
  median_pe?: number | null
  median_ev_revenue?: number | null
  // Peer median of the NOPAT core P/E — the multiple the trailing comps target
  // uses. Distinct from median_pe (as-reported, the forward-EPS path multiple).
  median_core_pe?: number | null
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
  // Trade-level fields are null in NEUTRAL (levels-only) mode — see `direction`.
  ideal_buy?: number | null
  secondary_buy?: number | null
  stop_loss?: number | null
  take_profit?: number | null
  position_size_pct?: number | null
  safety_margin?: number | null
  support_level?: number
  resistance_level?: number
  risk_reward_ratio?: number | null
  // "LONG" | "SHORT" | "NEUTRAL" — drives entry/exit labels. SHORT (SELL-rated)
  // flips ideal_buy → short entry, take_profit → cover target (below entry),
  // stop_loss → above entry. NEUTRAL = valuation unreliable → no directional
  // trade, only support/resistance. Absent on legacy artifacts (treat as LONG).
  direction?: string
  sell_mode?: boolean
  invariant_warnings?: string[]
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
  // SEC Form 4 §8 canonical codes — mirrors ownership._FORM4_CODE_TO_TYPE.
  | 'tax_withholding' // F — withhold shares for exercise price / tax
  | 'conversion' // C — conversion of derivative
  | 'exercise_otm' // O — exercise of out-of-money derivative
  | 'exercise_itm_atm' // X — exercise of in/at-money derivative
  | 'disposition_to_issuer' // D — disposition back to issuer
  | 'discretionary' // I — discretionary 16b-3(f) transaction
  | 'equity_swap' // K — equity swap or similar
  | 'tender' // U — tender in change-of-control
  | 'voluntary_report' // V — voluntary early report
  | 'estate' // W — acquisition/disposition by will/descent
  | 'voting_trust' // Z — deposit/withdrawal from voting trust
  | 'small_acquisition' // L — small acquisition under 16a-6
  | 'gift' // G — bona fide gift
  | 'expiration_short' // E — expiration of short derivative position
  | 'expiration_long' // H — expiration of long derivative position
  | 'other' // J — other (free-text described)

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

// Two currency tags carried by the equity_research structured payload (BUG-030).
// quote_currency labels per-share & market-cap fields (price, 52w hi/lo, DCF
// implied price, sniper levels, price target, market_cap); reporting_currency
// labels income-statement / balance-sheet absolutes (revenue, EBITDA, EV, debt,
// cash, CEO comp). They DISAGREE for foreign-listed ADRs (TSM: USD / TWD).
// Absent on older artifacts → callers default to USD so US reports are unchanged.
export interface CurrencyTagsShape {
  quote_currency?: string
  reporting_currency?: string
}

// ---------------------------------------------------------------------------
// Numeric-audit gate (backend ArtifactAudit, finrobot/engine/models/numeric_claim.py).
// One Finding = one audit verdict on one number. The artifact builder runs the
// definitional verifiers over the finalized snapshot and ships the rollup here.
// `withhold_valuation` nulls the POINT price_target + sets valuation_withheld;
// the directional recommendation is PRESERVED (the REVIEW verdict is deleted),
// so the UI only RENDERS the data-health caveat, it never re-decides the call.
// ---------------------------------------------------------------------------

/** Per-finding severity. `review` is an advisory data-quality flag (the word is
 * the data-quality axis, NOT the deleted verdict); `blocked_field` withholds
 * that number (and any price target derived from it). `info` is advisory. */
export type NumericAuditSeverity = 'info' | 'review' | 'blocked_field'

/** Report-level rollup. `publishable` → render as-is (no banner). `caveated` →
 * ship with a muted data-quality caveat banner (the directional verdict still
 * stands; a point target may be withheld). `unpublishable` → core data
 * unresolvable (critical-failure path, red). Renamed from the old `review_only`
 * (commit ④) so the status reads as run-metadata, not a verdict. */
export type NumericAuditStatus = 'publishable' | 'caveated' | 'unpublishable'

export interface NumericAuditFinding {
  /** Which number, e.g. "ev_ebitda" / "pe_ratio" / "enterprise_value". */
  field_key: string
  /** Stable rule id, e.g. "financial_sector_ev_meaningless". */
  check: string
  severity: NumericAuditSeverity
  /** Human-readable reason carrying the actual numbers — drives the banner body. */
  evidence: string
}

export interface NumericAuditShape {
  findings?: NumericAuditFinding[]
  artifact_status?: NumericAuditStatus
  withhold_valuation?: boolean
}

// ---------------------------------------------------------------------------
// Frozen valuation synthesis — the football-field data, computed at generation
// against the SNAPSHOT price and persisted into the artifact (builders.py).
// Mirrors finrobot.engine.models.financial.ValuationSynthesis. The report MUST
// render the football field from THIS (not a live /api/valuation/aggregate
// refetch) so every price in the report is the one snapshot the narrative and
// the cover target were written against — reproducible + internally consistent.
// `current_price` is the generation-time quote; `methods[].name` is the method
// key (dcf / comps_pe / ev_ebitda / …) the FootballField maps to a label.
// ---------------------------------------------------------------------------

export interface ValuationMethodShape {
  name: string
  low: number
  mid: number
  high: number
  confidence: number
  source: string
  assumptions?: string | null
}

export interface ValuationSynthesisShape {
  methods: ValuationMethodShape[]
  weighted_price?: number | null
  /** The quote the whole report is anchored to — frozen at data-fetch time. */
  current_price: number
  upside_downside?: number | null
  outlier_methods?: string[]
  warnings?: string[]
  /** Legacy binary gate — superseded by `confidence`. Kept for back-compat reads
   * of older artifacts; new surfaces read the tier, not this flag. */
  reliable?: boolean
  // ── Confidence dial (commit ③; ADR 估值优雅降级). The synthesis ALWAYS yields a
  // directional call; uncertainty is a tier + a widening band, never a withhold of
  // the call. Absent on legacy artifacts → callers default to 'low'.
  confidence?: 'high' | 'medium' | 'low' | 'very_low'
  /** Low/high ends of the headline target band (widen as confidence drops).
   * null when the point target is honestly withheld (valuation_withheld). */
  target_low?: number | null
  target_high?: number | null
  /** Method the headline point anchors on (dcf / comps_pe / …). The point sits
   * AT the anchor, never a blended midpoint of divergent methods. */
  anchor_method?: string | null
  /** True when the POINT target is honestly withheld — the directional verdict
   * still ships. Replaces the old recommendation==='REVIEW' sentinel. */
  valuation_withheld?: boolean
  /** Human-readable disclosure of what degraded + which proxy/anchor was used. */
  degradation_note?: string | null
}

// Scenario SOTP (Batch 3B v1): the reverse-SOTP market-implied decomposition for
// an option-value name (TSLA-class). An INDEPENDENT channel — NOT a method in the
// football field's point synthesis (kept out so it never trips the reliability
// gate). The valuation chapter renders it as a floor / implied-option-premium
// panel. All numbers are COMPUTED (deterministic) and 100% sourceable; price_floor
// is a FLOOR, not a target.
export interface SegmentValuationShape {
  name: string
  metric_label: string
  metric_value: number
  multiple: number
  multiple_source: string
  implied_ev: number
}

export interface SOTPBreakdownShape {
  ticker: string
  as_of: string
  modelable_segments: SegmentValuationShape[]
  ev_floor: number
  net_debt: number
  equity_floor: number
  price_floor: number
  shares_outstanding: number
  current_price: number
  market_equity: number
  implied_option_ev: number
  implied_option_pct: number
  option_ev_if_success?: number | null
  option_anchor_source?: string | null
  implied_success_probability?: number | null
  floor_exceeds_market?: boolean
  market_exceeds_success_ceiling?: boolean
  warnings?: string[]
}

// Frozen forward-estimate provenance (builders.py persists this slim block at
// generation). The forward NUMBERS live in valuation_synthesis.methods; this is
// only what the football field / footnote need to label the forward comps row
// ("FY2026E") and cite its source WITHOUT a live aggregate refetch.
export interface ForwardEstimatesShape {
  /** Forecast fiscal-year-end the forward EPS/EBITDA/FCF belong to (e.g. "2026-09-30"). */
  fiscal_period?: string | null
  source?: string | null
  confidence?: string | null
}

export interface ArtifactStructured {
  thesis?: ThesisShape
  currency?: CurrencyTagsShape
  financial_modeling?: DcfShape
  peer_analysis?: PeerCompsShape
  valuation_synthesis?: ValuationSynthesisShape
  forward_estimates?: ForwardEstimatesShape
  catalyst_analysis?: CatalystAnalysisShape
  technical_analysis?: TechnicalAnalysisShape
  ownership_governance?: OwnershipGovernanceShape
  sec_filings?: SecFilingsShape
  xbrl_facts_snapshot?: XbrlFactsSnapshotShape
  numeric_audit?: NumericAuditShape
  sotp_breakdown?: SOTPBreakdownShape
  // Multi-year trend series, frozen at generation (builders.py persists the
  // pipeline's HistoricalMetrics) so ChapterFinancialAnalysis reads the charts
  // from the snapshot instead of a live ['historical'] refetch.
  historical_metrics?: HistoricalMetrics
}
