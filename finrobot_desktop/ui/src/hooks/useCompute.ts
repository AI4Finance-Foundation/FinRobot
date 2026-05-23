import { useMutation } from '@tanstack/react-query'
import { api, BASE_URL } from '../api/client'
import { FetchHttpError } from '../utils/errorMessage'
import type { DCFInputs, DCFResult, SensitivityResult, MonteCarloResult } from '../stores/appStore'

export function useDcfCompute() {
  return useMutation({
    mutationFn: async (inputs: DCFInputs): Promise<DCFResult> => {
      const { data, error } = await api.POST('/api/compute/dcf', {
        body: inputs as never,
      })
      if (error) throw new Error('DCF compute failed')
      return data as unknown as DCFResult
    },
  })
}

export function useDcfSensitivity() {
  return useMutation({
    mutationFn: async (req: {
      inputs: DCFInputs
      wacc_range: number[]
      tg_range: number[]
    }): Promise<SensitivityResult> => {
      const { data, error } = await api.POST('/api/compute/dcf-sensitivity', {
        body: req as never,
      })
      if (error) throw new Error('Sensitivity compute failed')
      return data as unknown as SensitivityResult
    },
  })
}

export function useWaccCompute() {
  return useMutation({
    mutationFn: async (params: {
      risk_free_rate: number
      beta: number
      equity_risk_premium: number
      cost_of_debt: number
      tax_rate: number
      debt_ratio: number
    }): Promise<{ cost_of_equity: number; wacc: number }> => {
      const { data, error } = await api.POST('/api/compute/wacc', {
        body: params as never,
      })
      if (error) throw new Error('WACC compute failed')
      return data as unknown as { cost_of_equity: number; wacc: number }
    },
  })
}

export function useMonteCarloCompute() {
  return useMutation({
    mutationFn: async (req: {
      inputs: DCFInputs
      current_price: number
      n_simulations?: number
      n_bins?: number
      revenue_growth_std?: number
      ebitda_margin_std?: number
      wacc_std?: number
      terminal_growth_std?: number
    }): Promise<MonteCarloResult> => {
      // Use direct fetch since this endpoint is not yet in the generated schema
      const res = await fetch(`${BASE_URL}/api/compute/monte-carlo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
      })
      if (!res.ok) {
        throw new FetchHttpError(res.status, res.statusText)
      }
      return res.json() as Promise<MonteCarloResult>
    },
  })
}
