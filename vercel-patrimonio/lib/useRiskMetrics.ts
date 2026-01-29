'use client'

import { useMemo } from 'react'
import { Portfolio, PortfolioId, ALL_PORTFOLIOS } from './portfolioData'
import { usePerformanceMetrics } from './usePerformanceMetrics'
import {
  calculateRiskMetrics,
  RiskMetrics,
  DistributionData,
  PositionData,
} from './riskAnalysis'

interface UseRiskMetricsResult {
  riskMetrics: RiskMetrics | null
  loading: boolean
  error: string | null
}

/**
 * Hook to calculate risk metrics for a portfolio
 */
export function useRiskMetrics(portfolioId: PortfolioId): UseRiskMetricsResult {
  const portfolio = ALL_PORTFOLIOS[portfolioId]
  const { metrics: performanceMetrics, loading, error } = usePerformanceMetrics()

  const riskMetrics = useMemo(() => {
    if (!portfolio) return null

    // Convert portfolio distribution to the format expected by riskAnalysis
    const distribution: Record<string, DistributionData> = {}
    const dist = portfolio.distribucion

    if (dist.renta_variable) {
      distribution['renta_variable'] = dist.renta_variable
    }
    if (dist.renta_fija) {
      distribution['renta_fija'] = dist.renta_fija
    }
    if (dist.oro) {
      distribution['oro'] = dist.oro
    }
    if (dist.liquidez) {
      distribution['liquidez'] = dist.liquidez
    }

    // Create positions data from distribution
    // In a real implementation, this would come from actual position data
    const positions: Record<string, PositionData> = {}

    // Use distribution values as position values for concentration calculation
    // This is a simplification - ideally we'd have individual position data
    let posIndex = 0
    for (const [key, data] of Object.entries(distribution)) {
      if (data.valor > 0) {
        positions[`pos_${posIndex}`] = { valor: data.valor, nombre: key }
        posIndex++
      }
    }

    // Get YTD return from performance metrics, or use portfolio pnl_pct as fallback
    const ytdReturn = performanceMetrics?.ytdReturnPct ?? portfolio.pnl_pct

    return calculateRiskMetrics(distribution, positions, ytdReturn)
  }, [portfolio, performanceMetrics])

  return {
    riskMetrics,
    loading,
    error,
  }
}

/**
 * Hook to get risk metrics for all portfolios at once
 */
export function useAllRiskMetrics(): Record<PortfolioId, RiskMetrics | null> {
  const salvaMetrics = useRiskMetrics('salva')
  const madreMetrics = useRiskMetrics('madre')
  const consolidadoMetrics = useRiskMetrics('consolidado')

  return {
    salva: salvaMetrics.riskMetrics,
    madre: madreMetrics.riskMetrics,
    consolidado: consolidadoMetrics.riskMetrics,
  }
}

/**
 * Get static risk metrics without hooks (useful for server-side or initial render)
 */
export function getStaticRiskMetrics(portfolio: Portfolio, ytdReturn: number = 0): RiskMetrics {
  const distribution: Record<string, DistributionData> = {}
  const dist = portfolio.distribucion

  if (dist.renta_variable) {
    distribution['renta_variable'] = dist.renta_variable
  }
  if (dist.renta_fija) {
    distribution['renta_fija'] = dist.renta_fija
  }
  if (dist.oro) {
    distribution['oro'] = dist.oro
  }
  if (dist.liquidez) {
    distribution['liquidez'] = dist.liquidez
  }

  const positions: Record<string, PositionData> = {}
  let posIndex = 0
  for (const [key, data] of Object.entries(distribution)) {
    if (data.valor > 0) {
      positions[`pos_${posIndex}`] = { valor: data.valor, nombre: key }
      posIndex++
    }
  }

  return calculateRiskMetrics(distribution, positions, ytdReturn)
}
