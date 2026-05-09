import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import type { DCFInputs, DCFResult, SensitivityResult } from '../stores/appStore'

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
