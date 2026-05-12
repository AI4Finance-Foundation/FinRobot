import { create } from 'zustand'

type Phase =
  | 'idle'
  | 'loading_data'
  | 'data_ready'
  | 'running_pipeline'
  | 'pipeline_done'
  | 'interactive'

export type PipelineType = 'research' | 'dcf' | 'comps' | 'earnings' | 'lbo' | 'ic-memo'
export type ViewMode = 'workspace' | 'history'

export interface ResearchResult {
  recommendation: string
  price_target: number
  price_target_basis: string
  catalysts: string[]
  risks: string[]
  narrative: string
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

export interface EarningsSurprise {
  date: string
  eps_actual: number
  eps_estimated: number
  eps_surprise_pct: number
  eps_direction: 'beat' | 'miss' | 'inline'
  revenue_actual: number
  revenue_estimated: number
  revenue_surprise_pct: number
  revenue_direction: 'beat' | 'miss' | 'inline'
}

export interface EarningsResult {
  ticker: string
  surprises: EarningsSurprise[]
  beat_rate: number
  avg_eps_surprise_pct: number
  avg_revenue_surprise_pct: number
  consecutive_beats: number
}

export interface LBOYear {
  year: number
  revenue: number
  ebitda: number
  fcf: number
  mandatory_amort: number
  cash_sweep_amount: number
  total_debt_paydown: number
  ending_debt: number
}

export interface LBOSensitivity {
  entry_multiples: number[]
  exit_multiples: number[]
  irr_grid: (number | null)[][]
  moic_grid: (number | null)[][]
}

export interface LBOResult {
  entry_ev: number
  entry_debt: number
  entry_equity: number
  schedule: LBOYear[]
  exit_ebitda: number
  exit_ev: number
  exit_equity: number
  moic: number
  irr: number
  sensitivity: LBOSensitivity
  irr_formula_warning: string | null
}

export interface ICMemoRecommendation {
  verdict: string
  irr: number | null
  rationale: string
}

export interface ICMemoResult {
  situation_overview: string
  financial_summary: string
  investment_thesis: string
  risk_factors: string
  recommendation: ICMemoRecommendation
}

export interface MonteCarloResult {
  implied_prices: number[]
  percentiles: Record<string, number>
  mean: number
  std: number
  current_price_percentile: number
  histogram_bins: number[]
  histogram_counts: number[]
  assumptions_used: Record<string, number>
  n_valid: number
}

export interface CompanyValuation {
  ticker: string
  company_name: string
  current_price: number | null
  implied_price: number | null
  upside_pct: number | null
  wacc: number | null
  terminal_growth: number | null
  ev_ebitda: number | null
  pe_ratio: number | null
  dcf_result: DCFResult | null
  warnings: string[]
  error: string | null
}

export interface ComparisonResultData {
  companies: CompanyValuation[]
  generated_at: string
}

export type ActiveTab = 'overview' | 'financials' | 'valuation' | 'peers' | 'compare'

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

export interface QuarterlyData {
  ticker: string
  quarters: {
    quarter: string
    revenue: number
    operating_income: number
    net_income: number
    operating_cash_flow: number | null
  }[]
}

export interface PerformanceData {
  series: {
    ticker: string
    label: string
    data: { date: string; value: number }[]
  }[]
}

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
  fcf_formula: string
  fcf_formula_warning: string | null
}

export interface SensitivityResult {
  wacc_values: number[]
  tg_values: number[]
  implied_prices: (number | null)[][]
}

export type DcfSource = 'research' | 'standalone' | null
export type ScenarioKey = 'base' | 'bull' | 'bear'

interface Scenarios {
  base: DCFInputs | null
  bull: DCFInputs | null
  bear: DCFInputs | null
}

interface ScenarioResults {
  base: DCFResult | null
  bull: DCFResult | null
  bear: DCFResult | null
}

interface WorkspaceState {
  // UI state
  ticker: string
  phase: Phase
  pipelineType: PipelineType

  // Financial data warnings
  warnings: string[]

  // DCF state (filled after pipeline, updated on slider changes)
  dcfInputs: DCFInputs | null
  originalDcfInputs: DCFInputs | null
  dcfResult: DCFResult | null
  dcfSource: DcfSource
  sensitivityData: SensitivityResult | null
  currentPrice: number | null
  priceChange: number | null
  priceChangePct: number | null

  // Multi-scenario modeling
  activeScenario: ScenarioKey
  scenarios: Scenarios
  scenarioResults: ScenarioResults

  // Data freshness
  dataFetchedAt: number | null

  // Equity Research state
  researchResult: ResearchResult | null

  // Comps state
  compsResult: CompsResult | null

  // Earnings state
  earningsResult: EarningsResult | null

  // LBO state
  lboResult: LBOResult | null

  // IC Memo state
  icMemoResult: ICMemoResult | null

  // Monte Carlo state
  monteCarloResult: MonteCarloResult | null
  monteCarloLoading: boolean

  // Compare state
  comparisonResult: ComparisonResultData | null
  comparisonLoading: boolean

  // UI navigation
  view: ViewMode
  showSettings: boolean
  cmdPaletteOpen: boolean

  // Ask panel
  askPanelOpen: boolean

  // Tab navigation
  activeTab: ActiveTab

  // Data caches (per-ticker, invalidated on ticker change)
  historicalMetrics: HistoricalMetrics | null
  quarterlyData: QuarterlyData | null
  performanceData: PerformanceData | null
  historicalLoading: boolean
  quarterlyLoading: boolean
  performanceLoading: boolean

  // Actions
  setTicker: (t: string) => void
  setPhase: (p: Phase) => void
  setPipelineType: (t: PipelineType) => void
  setView: (v: ViewMode) => void
  setWarnings: (w: string[]) => void
  setDcfInputs: (inputs: DCFInputs) => void
  setOriginalDcfInputs: (inputs: DCFInputs) => void
  setDcfResult: (result: DCFResult, source?: DcfSource) => void
  setSensitivityData: (data: SensitivityResult) => void
  setCurrentPrice: (price: number) => void
  setPriceChange: (change: number, changePct: number) => void
  setDataFetchedAt: (ts: number) => void
  setResearchResult: (result: ResearchResult) => void
  setCompsResult: (result: CompsResult) => void
  setEarningsResult: (result: EarningsResult) => void
  setLboResult: (result: LBOResult) => void
  setIcMemoResult: (result: ICMemoResult) => void
  setMonteCarloResult: (result: MonteCarloResult | null) => void
  setMonteCarloLoading: (loading: boolean) => void
  setComparisonResult: (result: ComparisonResultData | null) => void
  setComparisonLoading: (loading: boolean) => void
  setShowSettings: (show: boolean) => void
  setCmdPaletteOpen: (open: boolean) => void
  toggleCmdPalette: () => void
  setAskPanelOpen: (open: boolean) => void
  setActiveTab: (tab: ActiveTab) => void
  setHistoricalMetrics: (data: HistoricalMetrics | null) => void
  setQuarterlyData: (data: QuarterlyData | null) => void
  setPerformanceData: (data: PerformanceData | null) => void
  setHistoricalLoading: (loading: boolean) => void
  setQuarterlyLoading: (loading: boolean) => void
  setPerformanceLoading: (loading: boolean) => void
  setActiveScenario: (s: ScenarioKey) => void
  setScenarioInputs: (s: ScenarioKey, inputs: DCFInputs) => void
  setScenarioResult: (s: ScenarioKey, result: DCFResult) => void
  initScenarios: (baseInputs: DCFInputs, baseResult: DCFResult) => void
  reset: () => void
}

const emptyScenarios: Scenarios = { base: null, bull: null, bear: null }
const emptyScenarioResults: ScenarioResults = { base: null, bull: null, bear: null }

const initialState = {
  ticker: '',
  phase: 'idle' as Phase,
  pipelineType: 'research' as PipelineType,
  warnings: [] as string[],
  dcfInputs: null,
  originalDcfInputs: null,
  dcfResult: null,
  dcfSource: null,
  sensitivityData: null,
  currentPrice: null,
  priceChange: null,
  priceChangePct: null,
  activeScenario: 'base' as ScenarioKey,
  scenarios: { ...emptyScenarios },
  scenarioResults: { ...emptyScenarioResults },
  dataFetchedAt: null,
  researchResult: null,
  compsResult: null,
  earningsResult: null,
  lboResult: null,
  icMemoResult: null,
  monteCarloResult: null,
  monteCarloLoading: false,
  comparisonResult: null,
  comparisonLoading: false,
  view: 'workspace' as ViewMode,
  showSettings: false,
  cmdPaletteOpen: false,
  askPanelOpen: false,
  activeTab: 'overview' as ActiveTab,
  historicalMetrics: null,
  quarterlyData: null,
  performanceData: null,
  historicalLoading: false,
  quarterlyLoading: false,
  performanceLoading: false,
}

/**
 * Create bull/bear DCFInputs by adjusting base assumptions.
 * Bull: +20% growth, +10% margin, -1% WACC (lower discount).
 * Bear: -20% growth, -10% margin, +1% WACC (higher discount).
 */
function deriveScenario(base: DCFInputs, direction: 'bull' | 'bear'): DCFInputs {
  const mult = direction === 'bull' ? 1 : -1
  return {
    ...base,
    revenue_growth_rates: base.revenue_growth_rates.map(
      (r) => Math.max(0, r * (1 + mult * 0.2))
    ),
    ebitda_margin: Math.max(0, Math.min(1, base.ebitda_margin * (1 + mult * 0.1))),
    risk_free_rate: Math.max(0, base.risk_free_rate - mult * 0.01),
  }
}

export const useAppStore = create<WorkspaceState>((set) => ({
  ...initialState,

  setTicker: (ticker) => set({
    ticker,
    researchResult: null,
    compsResult: null,
    earningsResult: null,
    lboResult: null,
    icMemoResult: null,
    monteCarloResult: null,
    monteCarloLoading: false,
    comparisonResult: null,
    comparisonLoading: false,
    dcfResult: null,
    dcfSource: null,
    dcfInputs: null,
    originalDcfInputs: null,
    sensitivityData: null,
    warnings: [],
    phase: 'idle',
    activeScenario: 'base' as ScenarioKey,
    scenarios: { ...emptyScenarios },
    scenarioResults: { ...emptyScenarioResults },
    askPanelOpen: false,
    activeTab: 'overview' as ActiveTab,
    historicalMetrics: null,
    quarterlyData: null,
    performanceData: null,
    historicalLoading: false,
    quarterlyLoading: false,
    performanceLoading: false,
  }),
  setPhase: (phase) => set({ phase }),
  setPipelineType: (pipelineType) => set({ pipelineType }),
  setView: (view) => set({ view }),
  setWarnings: (warnings) => set({ warnings }),
  setDcfInputs: (dcfInputs) => set({ dcfInputs }),
  setOriginalDcfInputs: (originalDcfInputs) => set({ originalDcfInputs }),
  setDcfResult: (dcfResult, source) => set({ dcfResult, ...(source !== undefined ? { dcfSource: source } : {}) }),
  setSensitivityData: (sensitivityData) => set({ sensitivityData }),
  setCurrentPrice: (currentPrice) => set({ currentPrice }),
  setPriceChange: (priceChange, priceChangePct) => set({ priceChange, priceChangePct }),
  setDataFetchedAt: (dataFetchedAt) => set({ dataFetchedAt }),
  setResearchResult: (researchResult) => set({ researchResult }),
  setCompsResult: (compsResult) => set({ compsResult }),
  setEarningsResult: (earningsResult) => set({ earningsResult }),
  setLboResult: (lboResult) => set({ lboResult }),
  setIcMemoResult: (icMemoResult) => set({ icMemoResult }),
  setMonteCarloResult: (monteCarloResult) => set({ monteCarloResult }),
  setMonteCarloLoading: (monteCarloLoading) => set({ monteCarloLoading }),
  setComparisonResult: (comparisonResult) => set({ comparisonResult }),
  setComparisonLoading: (comparisonLoading) => set({ comparisonLoading }),
  setShowSettings: (showSettings) => set({ showSettings }),
  setCmdPaletteOpen: (cmdPaletteOpen) => set({ cmdPaletteOpen }),
  toggleCmdPalette: () => set((s) => ({ cmdPaletteOpen: !s.cmdPaletteOpen })),
  setAskPanelOpen: (askPanelOpen) => set({ askPanelOpen }),
  setActiveTab: (activeTab) => set({ activeTab }),
  setHistoricalMetrics: (historicalMetrics) => set({ historicalMetrics }),
  setQuarterlyData: (quarterlyData) => set({ quarterlyData }),
  setPerformanceData: (performanceData) => set({ performanceData }),
  setHistoricalLoading: (historicalLoading) => set({ historicalLoading }),
  setQuarterlyLoading: (quarterlyLoading) => set({ quarterlyLoading }),
  setPerformanceLoading: (performanceLoading) => set({ performanceLoading }),

  setActiveScenario: (activeScenario) => set((s) => {
    const inputs = s.scenarios[activeScenario]
    const result = s.scenarioResults[activeScenario]
    return {
      activeScenario,
      ...(inputs ? { dcfInputs: inputs } : {}),
      ...(result ? { dcfResult: result } : {}),
    }
  }),

  setScenarioInputs: (key, inputs) => set((s) => ({
    scenarios: { ...s.scenarios, [key]: inputs },
    ...(s.activeScenario === key ? { dcfInputs: inputs } : {}),
  })),

  setScenarioResult: (key, result) => set((s) => ({
    scenarioResults: { ...s.scenarioResults, [key]: result },
    ...(s.activeScenario === key ? { dcfResult: result } : {}),
  })),

  initScenarios: (baseInputs, baseResult) => set({
    activeScenario: 'base' as ScenarioKey,
    scenarios: {
      base: baseInputs,
      bull: deriveScenario(baseInputs, 'bull'),
      bear: deriveScenario(baseInputs, 'bear'),
    },
    scenarioResults: {
      base: baseResult,
      bull: null,
      bear: null,
    },
  }),

  reset: () => set(initialState),
}))
