// Shared finance value-types used by chart adapters and artifact-detail
// chapter renderers.
//
// These are hand-written frontend shapes (distinct from the OpenAPI-derived
// `components['schemas'][…]` in `api/schema.d.ts`): chapter renderers feed
// loosely-typed artifact JSON into the chart adapters via `as unknown as …`
// casts, so the adapters need a stable structural contract independent of the
// backend schema. They were extracted from the now-deleted client-state
// `appStore` (BUG-024) — research results live in TanStack Query now, so the
// only thing left worth keeping was this type vocabulary.

export interface DCFInputs {
  revenue_base: number
  revenue_growth_rates: number[]
  ebitda_margin: number
  capex_pct_revenue: number
  nwc_pct_revenue: number
  da_pct_revenue?: number
  tax_rate: number
  risk_free_rate: number
  beta: number
  equity_risk_premium: number
  cost_of_debt: number
  debt_ratio: number
  terminal_growth_rate: number
  shares_outstanding: number
  net_debt: number
  assumption_provenance?: Record<string, string>
}

export interface DCFResult {
  cost_of_equity: number
  wacc: number
  projection_years: number
  projected_revenue: number[]
  projected_ebitda: number[]
  projected_fcf: number[]
  terminal_value: number
  pv_terminal: number
  pv_fcf_total: number
  enterprise_value: number
  equity_value: number
  implied_price: number
  sensitivity_table: unknown
  inputs: DCFInputs
  // No fcf_formula field: FCF always uses the standard
  // EBIT(1-T) + D&A - CapEx - ΔNWC; per-field source attribution lives in
  // assumption_provenance.
}

export interface CompanyFinancials {
  ticker: string
  name: string | null
  revenue: number
  ebitda: number
  net_income: number
  market_cap: number
  total_debt: number
  total_cash: number
  enterprise_value: number | null
  gross_margin: number
  operating_margin: number
  pe_ratio: number | null
  ev_ebitda: number | null
  ev_revenue: number | null
}

export interface CompsResult {
  target: CompanyFinancials
  peers: CompanyFinancials[]
  median_ev_ebitda: number | null
  median_pe: number | null
  median_ev_revenue: number | null
  mean_ev_ebitda: number | null
  mean_pe: number | null
  peer_justification: string
  positioning_narrative: string
}

export interface HistoricalMetrics {
  years: number[]
  revenue: number[]
  revenue_growth_yoy: (number | null)[]
  cogs: number[]
  gross_profit: number[]
  gross_margin: number[]
  sga: number[]
  sga_ratio: number[]
  ebitda: number[]
  ebitda_margin: number[]
  operating_income: number[]
  operating_margin: number[]
  net_income: number[]
  eps: number[]
  pe_ratio: (number | null)[]
  operating_cash_flow: number[]
  investing_cash_flow: number[]
  financing_cash_flow: number[]
  cagr_revenue: number | null
  ticker: string
  price_data_available: boolean
}
