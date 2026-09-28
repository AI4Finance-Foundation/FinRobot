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
  /** LLM-authored only when the verdict strongly disagrees with the stock's own
   * trailing-1y price action (BACKLOG A2/P1-1) — what the market's recent move is
   * pricing in and why the call differs. null on an ordinary, non-divergent call. */
  momentum_divergence_note?: string | null
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
  /** Steady-state Gordon perpetuity BASE (capex→maintenance anchor, ΔNWC→
   * marginal ratio) — NOT projected_fcf[-1]; disclosed so the terminal value
   * is reconstructible from printed inputs. Absent on legacy artifacts. */
  terminal_fcf?: number | null
  pv_fcf_total?: number
  enterprise_value?: number
  equity_value?: number
  implied_price?: number
  sensitivity_table?: Record<string, unknown> | null
  // ±2pp EBITDA-margin swing: [implied_price_at_-2pp, implied_price_at_+2pp],
  // low→high. Either end null when that shifted margin degrades (out of band /
  // Gordon guard); the whole field null when neither end is valid. Backend-
  // computed — never re-derived in the client. Absent on legacy artifacts.
  margin_swing?: [number | null, number | null] | null
  // Current-reality actuals for the four DCF drivers (keys revenue_growth /
  // ebitda_margin / capex_pct_revenue / nwc_pct_revenue) — the "Current" column of
  // the model-vs-current reconciliation. Calibers are MIXED (disclosed per cell):
  // ebitda_margin is always TTM; capex_pct_revenue is TTM when the canonical
  // snapshot resolved one (see assumption_current_actuals_capex_ttm — the only
  // driver whose caliber varies per ticker/run) and otherwise the latest fiscal
  // year; revenue_growth / nwc_pct_revenue are always the latest fiscal year (see
  // assumption_current_actuals_fy). Per-driver null when the source lacks a usable
  // point; whole field null on legacy artifacts. Deterministic (backend); the
  // client renders it verbatim, never re-computing a driver.
  assumption_current_actuals?: Record<string, number | null> | null
  // Fiscal year of the latest-FY current actuals (ΔNWC / growth, and capex on the
  // fallback path) — labels those cells "FY<year>" beside the TTM-labelled cells.
  // null on legacy.
  assumption_current_actuals_fy?: number | null
  // True when assumption_current_actuals.capex_pct_revenue is TTM-caliber; false
  // when it fell back to the latest fiscal year (the canonical snapshot's cash-
  // flow statement was thin/unavailable for this ticker); null/undefined on legacy
  // artifacts (predates this field) or when the actuals were never computed — the
  // reconciliation table then falls back to the FY label so it never claims a
  // caliber it can't back up (BUG-023 displayed==actual family).
  assumption_current_actuals_capex_ttm?: boolean | null
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
    // key → analyst-prose sourcing string ("35.0% (trailing 3yr median)"). The
    // "Model uses" column of the reconciliation — rendered VERBATIM, never
    // reformatted (the value already carries its own unit; BUG-030 / frontend
    // contract). Absent on legacy artifacts.
    assumption_provenance?: Record<string, string>
    // True when the explicit-window ΔNWC/revenue median was clamped into the
    // ±10% modelling band — drives the ⚠ on the ΔNWC reconciliation row. A
    // structured boolean so the ⚠ never parses the provenance prose.
    nwc_clamped?: boolean
  }
}

// ---------------------------------------------------------------------------
// Standalone DDM / LBO tool read models. Unlike DCF (financial_modeling) and
// comps (peer_analysis), these two have NO dedicated report chapter — they only
// appear as a football-field method row in the full report. The standalone DDM /
// LBO artifacts persist the raw DDMResult / LBOResult model_dump() at
// outputs.structured top level (builders.build_ddm_artifact / build_lbo_artifact),
// so the tool detail page renders them through DdmBody / LboBody (chapters/) using
// the SAME shared primitives (MetricModule / SubChapter / tableStyle) the report
// chapters use — one visual language, no raw K-V dump. Mirror
// finrobot.engine.models.financial.{DDMResult,DDMInputs,LBOResult,LBOYear,LBOInputs};
// keep in sync when those models change.
// ---------------------------------------------------------------------------

export interface DdmInputsShape {
  dividend_per_share?: number
  dividend_growth_rates?: number[]
  payout_ratio?: number
  risk_free_rate?: number
  beta?: number
  equity_risk_premium?: number
  terminal_growth_rate?: number
  terminal_payout_ratio?: number | null
  shares_outstanding?: number
  current_price?: number
  book_value_per_share?: number | null
  return_on_equity?: number | null
  net_interest_margin?: number | null
  // key (snake_case) → human-readable prose explanation of how each input was
  // derived (e.g. "34.4% (trailing 3yr EBITDA margin median)"). The VALUES are
  // already analyst prose; the tool page humanises the KEY and renders the value
  // verbatim (see CompactArtifactViewer ProvenanceList).
  assumption_provenance?: Record<string, string>
}

export interface DdmShape {
  cost_of_equity?: number
  projected_dividends?: number[]
  pv_dividends?: number[]
  pv_dividends_total?: number
  terminal_dividend?: number
  terminal_value?: number
  pv_terminal?: number
  equity_value_per_share?: number
  inputs?: DdmInputsShape
}

/** One year of the LBO debt schedule. All numbers deterministically computed. */
export interface LboYearShape {
  year: number
  revenue: number
  ebitda: number
  da: number
  ebit: number
  interest_expense: number
  ebt: number
  taxes: number
  net_income: number
  capex: number
  delta_nwc: number
  fcf: number
  mandatory_amort: number
  cash_sweep_amount: number
  total_debt_paydown: number
  revolver_draw: number
  ending_debt: number
}

export interface LboInputsShape {
  ticker?: string
  ltm_ebitda?: number
  entry_ebitda?: number | null
  entry_ev_ebitda?: number
  exit_ev_ebitda?: number
  holding_period_years?: number
  revenue_base?: number
  revenue_growth_rate?: number
  ebitda_margin?: number
  leverage_multiple?: number
  interest_rate?: number
  mandatory_amort_pct?: number
  tax_rate?: number
  assumption_provenance?: Record<string, string>
}

export interface LboSensitivityShape {
  entry_multiples?: number[]
  exit_multiples?: number[]
  irr_grid?: (number | null)[][]
  moic_grid?: (number | null)[][]
}

export interface LboShape {
  // Null throughout when the lbo_calculation step degraded (e.g. an impossible
  // capital structure) — the tool page degrades to the inputs + warnings rather
  // than crashing on a missing schedule (mirrors the MU peak-EBITDA case).
  entry_ev?: number | null
  entry_debt?: number | null
  entry_equity?: number | null
  schedule?: LboYearShape[]
  exit_ebitda?: number | null
  exit_ev?: number | null
  exit_equity?: number | null
  // MOIC/IRR contract (see lbo-recall): None = impossible capital structure
  // (negative entry equity); 0×/-1 = a genuine total loss (equity wiped).
  moic?: number | null
  irr?: number | null
  sensitivity?: LboSensitivityShape | null
  irr_formula_warning?: string | null
  capital_structure_warning?: string | null
}

export interface CatalystEventShape {
  category: string
  headline: string
  sentiment: 'positive' | 'negative' | 'neutral'
  impact_score: number
  // Internal net-sentiment weight (news 0.7 / 8-K 1.0), never rendered — the
  // Catalysts/News chapters dropped its column as fake precision. The backend now
  // excludes it from serialization (exclude=True), so it appears only on pre-fix
  // artifacts; optional and ignored everywhere.
  probability?: number
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
  // Price-to-book (market_cap / book equity). Banks' primary comps caliber — the
  // competitive table swaps its EV/EBITDA column to this for balance-sheet
  // financials (EV/EBITDA is a category error for deposit-takers).
  pb_ratio?: number | null
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
  // Peer median P/B — the bank-caliber comps multiple the competitive table leads
  // on for balance-sheet financials (in place of EV/EBITDA).
  median_pb?: number | null
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
  // Trailing window (years) the percentiles were computed over — the report's
  // unified band window, matching the valuation-method band. Lets the panel
  // label the band (e.g. "5y"). Absent on artifacts written before the field.
  window_years?: number | null
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
  // Where ceo_name came from. The comp figures always come from this DEF 14A,
  // but the NAME may be overridden by a fresher authority after a succession:
  // 'form4' = Form-4 officer title; 'sox302_cert' = the Ex-31.1 signer of the
  // latest 10-Q/10-K (the current principal executive officer by law).
  ceo_name_source?: 'def14a' | 'form4' | 'sox302_cert' | null
  // Filing the name was read from, when source !== 'def14a'.
  ceo_name_provenance?: FilingProvenanceShape | null
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
  /** True for a balance-sheet financial (bank / insurer) whose cash-flow methods
   * (FCFF-DCF, EV/EBITDA, P/FCF) are category errors and suppressed at the source.
   * Lets the DCF / Monte-Carlo / EV-EBITDA-band / sensitivity chapters frame the
   * absent panels as 'not applicable to a balance-sheet financial' rather than
   * 'missing — re-run', WITHOUT re-deriving the classification in the client. */
  financial_sector?: boolean
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

// Forward STREET-anchored scenario band (Batch 3B v2): the three legs are the
// 12-month analyst price-target DISTRIBUTION (street low/consensus/high). range_position
// is street positioning within that range — NEVER a robotaxi-success probability, and
// the legs are 12-month FORWARD values (the reverse-SOTP floor above is a present value).
export interface SOTPScenarioBandShape {
  // C (4-point merge): the reverse-SOTP cash-flow floor rides as an INDEPENDENT
  // present-value anchor beside the 12-month street cluster (bear/base/bull, forward).
  // floor_coverage = cash_flow_floor / current_price is the ONLY floor-vs-price
  // relation (same present-value caliber); a floor→street ratio is forbidden
  // (cross-caliber) and never appears — do NOT place the price marker on a
  // [floor, bull] axis.
  cash_flow_floor?: number | null
  floor_coverage?: number | null
  bear: number
  base: number
  bull: number
  median?: number | null
  current_price: number
  range_position: number
  analyst_count?: number | null
  confidence: string
  source: string
  as_of: string
  warnings?: string[]
}

// Lightweight, display-only reportable-segment revenue mix (BACKLOG A4,
// 2026-07-09) — the Company Overview chapter's non-SOTP sibling. Populated for
// tickers the SOTP option-value gate did NOT fire for (see SOTPBreakdownShape
// below for that heavier reverse-decomposition channel). SEC XBRL ASC-280
// reportable segments ONLY (an FMP product-mix fallback was tried and removed
// the same day — different, unaudited caliber + demonstrably unreliable, KO
// live). An issuer with no cleanly-anchorable XBRL segment breakdown ships NO
// SegmentOverview (honest "not available"), never a substitute.
export interface SegmentShareShape {
  name: string
  revenue?: number | null
  // Share of the SUM of segments in THIS breakdown — NOT a share of the
  // company's consolidated total revenue (see SegmentOverviewShape.warnings
  // for the corporate/eliminations reconciliation caveat).
  revenue_share?: number | null
  operating_income?: number | null
  gross_profit?: number | null
}

export interface SegmentOverviewShape {
  ticker: string
  as_of: string
  source: 'sec_xbrl_business_segment'
  period_label: string
  segments: SegmentShareShape[]
  warnings?: string[]
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
  scenario_band?: SOTPScenarioBandShape | null
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
  // BACKLOG A4 (2026-07-09): display-only sibling for tickers the SOTP gate
  // above did NOT fire for — see SegmentOverviewShape.
  segment_overview?: SegmentOverviewShape
  // Multi-year trend series, frozen at generation (builders.py persists the
  // pipeline's HistoricalMetrics) so ChapterFinancialAnalysis reads the charts
  // from the snapshot instead of a live ['historical'] refetch.
  historical_metrics?: HistoricalMetrics
}
