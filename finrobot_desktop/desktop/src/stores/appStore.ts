import { create } from 'zustand'

type Phase =
  | 'idle'
  | 'loading_data'
  | 'data_ready'
  | 'running_pipeline'
  | 'pipeline_done'
  | 'interactive'

export type PipelineType = 'equity_research' | 'dcf' | 'comps' | 'earnings' | 'lbo'
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
  sensitivityData: SensitivityResult | null
  currentPrice: number | null

  // Equity Research state
  researchResult: ResearchResult | null

  // Comps state
  compsResult: CompsResult | null

  // Earnings state
  earningsResult: EarningsResult | null

  // LBO state
  lboResult: LBOResult | null

  // UI navigation
  view: ViewMode
  showSettings: boolean

  // Actions
  setTicker: (t: string) => void
  setPhase: (p: Phase) => void
  setPipelineType: (t: PipelineType) => void
  setView: (v: ViewMode) => void
  setWarnings: (w: string[]) => void
  setDcfInputs: (inputs: DCFInputs) => void
  setOriginalDcfInputs: (inputs: DCFInputs) => void
  setDcfResult: (result: DCFResult) => void
  setSensitivityData: (data: SensitivityResult) => void
  setCurrentPrice: (price: number) => void
  setResearchResult: (result: ResearchResult) => void
  setCompsResult: (result: CompsResult) => void
  setEarningsResult: (result: EarningsResult) => void
  setLboResult: (result: LBOResult) => void
  setShowSettings: (show: boolean) => void
  reset: () => void
}

const initialState = {
  ticker: '',
  phase: 'idle' as Phase,
  pipelineType: 'equity_research' as PipelineType,
  warnings: [] as string[],
  dcfInputs: null,
  originalDcfInputs: null,
  dcfResult: null,
  sensitivityData: null,
  currentPrice: null,
  researchResult: null,
  compsResult: null,
  earningsResult: null,
  lboResult: null,
  view: 'workspace' as ViewMode,
  showSettings: false,
}

export const useAppStore = create<WorkspaceState>((set) => ({
  ...initialState,

  setTicker: (ticker) => set({ ticker }),
  setPhase: (phase) => set({ phase }),
  setPipelineType: (pipelineType) => set({ pipelineType }),
  setView: (view) => set({ view }),
  setWarnings: (warnings) => set({ warnings }),
  setDcfInputs: (dcfInputs) => set({ dcfInputs }),
  setOriginalDcfInputs: (originalDcfInputs) => set({ originalDcfInputs }),
  setDcfResult: (dcfResult) => set({ dcfResult }),
  setSensitivityData: (sensitivityData) => set({ sensitivityData }),
  setCurrentPrice: (currentPrice) => set({ currentPrice }),
  setResearchResult: (researchResult) => set({ researchResult }),
  setCompsResult: (compsResult) => set({ compsResult }),
  setEarningsResult: (earningsResult) => set({ earningsResult }),
  setLboResult: (lboResult) => set({ lboResult }),
  setShowSettings: (showSettings) => set({ showSettings }),
  reset: () => set(initialState),
}))
