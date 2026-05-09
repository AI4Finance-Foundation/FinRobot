import { create } from 'zustand'

type Phase =
  | 'idle'
  | 'loading_data'
  | 'data_ready'
  | 'running_pipeline'
  | 'pipeline_done'
  | 'interactive'

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

  // Financial data warnings
  warnings: string[]

  // DCF state (filled after pipeline, updated on slider changes)
  dcfInputs: DCFInputs | null
  originalDcfInputs: DCFInputs | null
  dcfResult: DCFResult | null
  sensitivityData: SensitivityResult | null
  currentPrice: number | null

  // Settings UI
  showSettings: boolean

  // Actions
  setTicker: (t: string) => void
  setPhase: (p: Phase) => void
  setWarnings: (w: string[]) => void
  setDcfInputs: (inputs: DCFInputs) => void
  setOriginalDcfInputs: (inputs: DCFInputs) => void
  setDcfResult: (result: DCFResult) => void
  setSensitivityData: (data: SensitivityResult) => void
  setCurrentPrice: (price: number) => void
  setShowSettings: (show: boolean) => void
  reset: () => void
}

const initialState = {
  ticker: '',
  phase: 'idle' as Phase,
  warnings: [] as string[],
  dcfInputs: null,
  originalDcfInputs: null,
  dcfResult: null,
  sensitivityData: null,
  currentPrice: null,
  showSettings: false,
}

export const useAppStore = create<WorkspaceState>((set) => ({
  ...initialState,

  setTicker: (ticker) => set({ ticker }),
  setPhase: (phase) => set({ phase }),
  setWarnings: (warnings) => set({ warnings }),
  setDcfInputs: (dcfInputs) => set({ dcfInputs }),
  setOriginalDcfInputs: (originalDcfInputs) => set({ originalDcfInputs }),
  setDcfResult: (dcfResult) => set({ dcfResult }),
  setSensitivityData: (sensitivityData) => set({ sensitivityData }),
  setCurrentPrice: (currentPrice) => set({ currentPrice }),
  setShowSettings: (showSettings) => set({ showSettings }),
  reset: () => set(initialState),
}))
