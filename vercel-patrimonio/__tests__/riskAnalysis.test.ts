/**
 * Tests for riskAnalysis.ts module.
 *
 * Tests cover all risk calculation functions and interpretation helpers.
 */
import { describe, it, expect } from 'vitest'
import {
  calculatePortfolioVolatility,
  calculateSharpeRatio,
  calculatePortfolioBeta,
  calculateVaR95,
  calculateConcentration,
  estimateMaxDrawdown,
  calculateRiskScore,
  calculateRiskMetrics,
  getVolatilityInterpretation,
  getSharpeInterpretation,
  getBetaInterpretation,
  getConcentrationInterpretation,
  getRiskEmoji,
  getRiskColor,
  getRiskInterpretation,
  DistributionData,
  PositionData,
} from '../lib/riskAnalysis'

describe('calculatePortfolioVolatility', () => {
  it('should calculate volatility for equity-only portfolio', () => {
    const distribution: Record<string, DistributionData> = {
      renta_variable: { actual: 100, objetivo: 100, valor: 100000 },
    }
    const volatility = calculatePortfolioVolatility(distribution)
    // 100% equity = 18% volatility * 1.3 correlation factor
    expect(volatility).toBeCloseTo(18 * 1.3, 1)
  })

  it('should calculate lower volatility for bond-heavy portfolio', () => {
    const distribution: Record<string, DistributionData> = {
      renta_fija: { actual: 80, objetivo: 80, valor: 80000 },
      liquidez: { actual: 20, objetivo: 20, valor: 20000 },
    }
    const volatility = calculatePortfolioVolatility(distribution)
    // Should be much lower than equity portfolio
    expect(volatility).toBeLessThan(10)
  })

  it('should calculate high volatility for crypto-heavy portfolio', () => {
    const distribution: Record<string, DistributionData> = {
      cripto: { actual: 50, objetivo: 50, valor: 50000 },
      renta_variable: { actual: 50, objetivo: 50, valor: 50000 },
    }
    const volatility = calculatePortfolioVolatility(distribution)
    // Should be higher due to crypto
    expect(volatility).toBeGreaterThan(30)
  })

  it('should handle empty distribution', () => {
    const distribution: Record<string, DistributionData> = {}
    const volatility = calculatePortfolioVolatility(distribution)
    expect(volatility).toBe(0)
  })

  it('should handle mixed balanced portfolio', () => {
    const distribution: Record<string, DistributionData> = {
      renta_variable: { actual: 60, objetivo: 60, valor: 60000 },
      renta_fija: { actual: 30, objetivo: 30, valor: 30000 },
      oro: { actual: 10, objetivo: 10, valor: 10000 },
    }
    const volatility = calculatePortfolioVolatility(distribution)
    // Balanced portfolio should have moderate volatility
    expect(volatility).toBeGreaterThan(10)
    expect(volatility).toBeLessThan(20)
  })
})

describe('calculateSharpeRatio', () => {
  it('should calculate positive Sharpe for returns above risk-free rate', () => {
    const sharpe = calculateSharpeRatio(10, 15) // 10% return, 15% vol
    // (10 - 3.5) / 15 = 0.433
    expect(sharpe).toBeCloseTo(0.43, 2)
  })

  it('should calculate negative Sharpe for returns below risk-free rate', () => {
    const sharpe = calculateSharpeRatio(2, 10) // 2% return, 10% vol
    // (2 - 3.5) / 10 = -0.15
    expect(sharpe).toBeCloseTo(-0.15, 2)
  })

  it('should return 0 for zero volatility', () => {
    const sharpe = calculateSharpeRatio(10, 0)
    expect(sharpe).toBe(0)
  })

  it('should return 0 for negative volatility', () => {
    const sharpe = calculateSharpeRatio(10, -5)
    expect(sharpe).toBe(0)
  })

  it('should calculate excellent Sharpe for high returns', () => {
    const sharpe = calculateSharpeRatio(25, 15) // 25% return, 15% vol
    // (25 - 3.5) / 15 = 1.43
    expect(sharpe).toBeCloseTo(1.43, 2)
    expect(sharpe).toBeGreaterThan(1) // Excellent
  })
})

describe('calculatePortfolioBeta', () => {
  it('should calculate beta 1 for equity-only portfolio', () => {
    const distribution: Record<string, DistributionData> = {
      renta_variable: { actual: 100, objetivo: 100, valor: 100000 },
    }
    const beta = calculatePortfolioBeta(distribution)
    expect(beta).toBeCloseTo(1.0, 2)
  })

  it('should calculate low beta for bond portfolio', () => {
    const distribution: Record<string, DistributionData> = {
      renta_fija: { actual: 100, objetivo: 100, valor: 100000 },
    }
    const beta = calculatePortfolioBeta(distribution)
    expect(beta).toBeCloseTo(0.1, 2) // Bonds have 0.1 beta
  })

  it('should calculate zero beta for gold/cash portfolio', () => {
    const distribution: Record<string, DistributionData> = {
      oro: { actual: 50, objetivo: 50, valor: 50000 },
      liquidez: { actual: 50, objetivo: 50, valor: 50000 },
    }
    const beta = calculatePortfolioBeta(distribution)
    expect(beta).toBe(0)
  })

  it('should calculate high beta for crypto portfolio', () => {
    const distribution: Record<string, DistributionData> = {
      cripto: { actual: 100, objetivo: 100, valor: 100000 },
    }
    const beta = calculatePortfolioBeta(distribution)
    expect(beta).toBeCloseTo(1.5, 2) // Crypto has 1.5 beta
  })

  it('should calculate weighted beta for mixed portfolio', () => {
    const distribution: Record<string, DistributionData> = {
      renta_variable: { actual: 60, objetivo: 60, valor: 60000 },
      renta_fija: { actual: 40, objetivo: 40, valor: 40000 },
    }
    const beta = calculatePortfolioBeta(distribution)
    // 0.6 * 1.0 + 0.4 * 0.1 = 0.64
    expect(beta).toBeCloseTo(0.64, 2)
  })
})

describe('calculateVaR95', () => {
  it('should calculate daily VaR from annual volatility', () => {
    const var95 = calculateVaR95(15) // 15% annual vol
    // Daily vol = 15 / sqrt(252) ≈ 0.945%
    // VaR 95 = 0.945 * 1.645 ≈ 1.55%
    expect(var95).toBeCloseTo(1.55, 1)
  })

  it('should return 0 for zero volatility', () => {
    const var95 = calculateVaR95(0)
    expect(var95).toBe(0)
  })

  it('should calculate higher VaR for higher volatility', () => {
    const var95Low = calculateVaR95(10)
    const var95High = calculateVaR95(30)
    expect(var95High).toBeGreaterThan(var95Low)
    expect(var95High).toBeCloseTo(var95Low * 3, 1) // Linear relationship
  })
})

describe('calculateConcentration', () => {
  it('should calculate 100% concentration for single position', () => {
    const positions: Record<string, PositionData> = {
      pos1: { valor: 100000, nombre: 'Single' },
    }
    const concentration = calculateConcentration(positions)
    expect(concentration).toBe(100)
  })

  it('should calculate concentration for top 3 positions', () => {
    const positions: Record<string, PositionData> = {
      pos1: { valor: 40000 },
      pos2: { valor: 30000 },
      pos3: { valor: 20000 },
      pos4: { valor: 10000 },
    }
    const concentration = calculateConcentration(positions)
    // Top 3: 40k + 30k + 20k = 90k out of 100k = 90%
    expect(concentration).toBe(90)
  })

  it('should return 0 for empty positions', () => {
    const concentration = calculateConcentration({})
    expect(concentration).toBe(0)
  })

  it('should return 0 for positions with zero values', () => {
    const positions: Record<string, PositionData> = {
      pos1: { valor: 0 },
      pos2: { valor: 0 },
    }
    const concentration = calculateConcentration(positions)
    expect(concentration).toBe(0)
  })

  it('should handle 2 positions correctly', () => {
    const positions: Record<string, PositionData> = {
      pos1: { valor: 60000 },
      pos2: { valor: 40000 },
    }
    const concentration = calculateConcentration(positions)
    expect(concentration).toBe(100) // Both positions = 100%
  })
})

describe('estimateMaxDrawdown', () => {
  it('should estimate max drawdown based on volatility and beta', () => {
    const drawdown = estimateMaxDrawdown(15, 1.0) // 15% vol, beta 1
    // Monthly vol = 15 / sqrt(12) ≈ 4.33
    // Max DD = 4.33 * 4 * (0.5 + 0.5 * 1) = 17.3%
    expect(drawdown).toBeCloseTo(17.3, 0)
  })

  it('should estimate lower drawdown for defensive beta', () => {
    const drawdown = estimateMaxDrawdown(15, 0.5)
    expect(drawdown).toBeLessThan(15)
  })

  it('should estimate higher drawdown for aggressive beta', () => {
    const drawdown = estimateMaxDrawdown(15, 1.5)
    expect(drawdown).toBeGreaterThan(20)
  })

  it('should cap max drawdown at 80%', () => {
    const drawdown = estimateMaxDrawdown(100, 2) // Extreme case
    expect(drawdown).toBe(80)
  })

  it('should return 0 for zero volatility', () => {
    const drawdown = estimateMaxDrawdown(0, 1)
    expect(drawdown).toBe(0)
  })
})

describe('calculateRiskScore', () => {
  it('should return low risk for conservative portfolio', () => {
    const { score, category } = calculateRiskScore(5, 0.2, 30)
    expect(score).toBeLessThanOrEqual(3)
    expect(category).toBe('Low')
  })

  it('should return moderate risk for balanced portfolio', () => {
    // Using higher inputs to get score 4-5
    // volatilityScore = min(20/5, 10) = 4
    // betaScore = min(0.8*5, 10) = 4
    // concentrationScore = min(60/10, 10) = 6
    // total = 4*0.5 + 4*0.3 + 6*0.2 = 2 + 1.2 + 1.2 = 4.4 → rounds to 4
    const { score, category } = calculateRiskScore(20, 0.8, 60)
    expect(score).toBeGreaterThanOrEqual(4)
    expect(score).toBeLessThanOrEqual(5)
    expect(category).toBe('Moderate')
  })

  it('should return high risk for aggressive portfolio', () => {
    const { score, category } = calculateRiskScore(25, 1.2, 70)
    expect(score).toBeGreaterThanOrEqual(6)
    expect(score).toBeLessThanOrEqual(7)
    expect(category).toBe('High')
  })

  it('should return very high risk for extreme portfolio', () => {
    const { score, category } = calculateRiskScore(50, 1.5, 90)
    expect(score).toBeGreaterThanOrEqual(8)
    expect(category).toBe('Very High')
  })

  it('should clamp score to minimum of 1', () => {
    const { score } = calculateRiskScore(0, 0, 0)
    expect(score).toBeGreaterThanOrEqual(1)
  })

  it('should clamp score to maximum of 10', () => {
    const { score } = calculateRiskScore(100, 10, 100)
    expect(score).toBeLessThanOrEqual(10)
  })
})

describe('calculateRiskMetrics', () => {
  it('should calculate all metrics for balanced portfolio', () => {
    const distribution: Record<string, DistributionData> = {
      renta_variable: { actual: 60, objetivo: 60, valor: 60000 },
      renta_fija: { actual: 30, objetivo: 30, valor: 30000 },
      oro: { actual: 10, objetivo: 10, valor: 10000 },
    }
    const positions: Record<string, PositionData> = {
      pos1: { valor: 60000 },
      pos2: { valor: 30000 },
      pos3: { valor: 10000 },
    }

    const metrics = calculateRiskMetrics(distribution, positions, 8)

    expect(metrics.annualVolatility).toBeGreaterThan(0)
    expect(metrics.sharpeRatio).toBeDefined()
    expect(metrics.beta).toBeGreaterThan(0)
    expect(metrics.beta).toBeLessThan(1)
    expect(metrics.var95).toBeGreaterThan(0)
    expect(metrics.concentrationTop3).toBe(100) // Only 3 positions
    expect(metrics.riskScore).toBeGreaterThanOrEqual(1)
    expect(metrics.riskScore).toBeLessThanOrEqual(10)
    expect(['Low', 'Moderate', 'High', 'Very High']).toContain(metrics.riskCategory)
  })

  it('should handle empty inputs', () => {
    const metrics = calculateRiskMetrics({}, {}, 0)

    expect(metrics.annualVolatility).toBe(0)
    expect(metrics.sharpeRatio).toBe(0)
    expect(metrics.beta).toBe(0)
    expect(metrics.var95).toBe(0)
    expect(metrics.concentrationTop3).toBe(0)
    expect(metrics.riskScore).toBe(1) // Minimum score
    expect(metrics.riskCategory).toBe('Low')
  })

  it('should round values to 2 decimal places', () => {
    const distribution: Record<string, DistributionData> = {
      renta_variable: { actual: 33.333, objetivo: 30, valor: 33333 },
      renta_fija: { actual: 66.667, objetivo: 70, valor: 66667 },
    }
    const positions: Record<string, PositionData> = {
      pos1: { valor: 33333 },
      pos2: { valor: 66667 },
    }

    const metrics = calculateRiskMetrics(distribution, positions, 5.5555)

    // Check that values are rounded (no more than 2 decimal places)
    expect(String(metrics.annualVolatility).split('.')[1]?.length || 0).toBeLessThanOrEqual(2)
    expect(String(metrics.sharpeRatio).split('.')[1]?.length || 0).toBeLessThanOrEqual(2)
    expect(String(metrics.beta).split('.')[1]?.length || 0).toBeLessThanOrEqual(2)
  })
})

describe('getVolatilityInterpretation', () => {
  it('should return Low for volatility under 10', () => {
    expect(getVolatilityInterpretation(5)).toBe('Low')
    expect(getVolatilityInterpretation(9.9)).toBe('Low')
  })

  it('should return Medium for volatility 10-20', () => {
    expect(getVolatilityInterpretation(10)).toBe('Medium')
    expect(getVolatilityInterpretation(15)).toBe('Medium')
    expect(getVolatilityInterpretation(19.9)).toBe('Medium')
  })

  it('should return High for volatility 20+', () => {
    expect(getVolatilityInterpretation(20)).toBe('High')
    expect(getVolatilityInterpretation(50)).toBe('High')
  })
})

describe('getSharpeInterpretation', () => {
  it('should return Excellent for Sharpe > 1', () => {
    expect(getSharpeInterpretation(1.5)).toBe('Excellent')
    expect(getSharpeInterpretation(2.0)).toBe('Excellent')
  })

  it('should return Good for Sharpe > 0.5 and <= 1', () => {
    // Note: boundary is exclusive (>), so 0.5 returns 'Fair', not 'Good'
    expect(getSharpeInterpretation(0.51)).toBe('Good')
    expect(getSharpeInterpretation(0.8)).toBe('Good')
    expect(getSharpeInterpretation(1.0)).toBe('Good')
  })

  it('should return Fair for Sharpe > 0 and <= 0.5', () => {
    // Note: boundary is exclusive (>), so 0 returns 'Negative', not 'Fair'
    expect(getSharpeInterpretation(0.01)).toBe('Fair')
    expect(getSharpeInterpretation(0.3)).toBe('Fair')
    expect(getSharpeInterpretation(0.5)).toBe('Fair') // Exactly 0.5 is Fair, not Good
  })

  it('should return Negative for Sharpe <= 0', () => {
    expect(getSharpeInterpretation(0)).toBe('Negative')  // Zero returns Negative
    expect(getSharpeInterpretation(-0.5)).toBe('Negative')
    expect(getSharpeInterpretation(-1)).toBe('Negative')
  })
})

describe('getBetaInterpretation', () => {
  it('should return Defensive for beta < 0.8', () => {
    expect(getBetaInterpretation(0)).toBe('Defensive')
    expect(getBetaInterpretation(0.5)).toBe('Defensive')
    expect(getBetaInterpretation(0.79)).toBe('Defensive')
  })

  it('should return Neutral for beta 0.8-1.2', () => {
    expect(getBetaInterpretation(0.8)).toBe('Neutral')
    expect(getBetaInterpretation(1.0)).toBe('Neutral')
    expect(getBetaInterpretation(1.19)).toBe('Neutral')
  })

  it('should return Aggressive for beta >= 1.2', () => {
    expect(getBetaInterpretation(1.2)).toBe('Aggressive')
    expect(getBetaInterpretation(1.5)).toBe('Aggressive')
  })
})

describe('getConcentrationInterpretation', () => {
  it('should return Diversified for concentration < 50', () => {
    expect(getConcentrationInterpretation(30)).toBe('Diversified')
    expect(getConcentrationInterpretation(49)).toBe('Diversified')
  })

  it('should return Concentrated for concentration 50-70', () => {
    expect(getConcentrationInterpretation(50)).toBe('Concentrated')
    expect(getConcentrationInterpretation(69)).toBe('Concentrated')
  })

  it('should return Very Concentrated for concentration >= 70', () => {
    expect(getConcentrationInterpretation(70)).toBe('Very Concentrated')
    expect(getConcentrationInterpretation(100)).toBe('Very Concentrated')
  })
})

describe('getRiskEmoji', () => {
  it('should return correct emoji for each category', () => {
    expect(getRiskEmoji('Low')).toBe('🟢')
    expect(getRiskEmoji('Moderate')).toBe('🟡')
    expect(getRiskEmoji('High')).toBe('🟠')
    expect(getRiskEmoji('Very High')).toBe('🔴')
  })
})

describe('getRiskColor', () => {
  it('should return correct color for each category', () => {
    expect(getRiskColor('Low')).toBe('#22C55E')
    expect(getRiskColor('Moderate')).toBe('#F59E0B')
    expect(getRiskColor('High')).toBe('#F97316')
    expect(getRiskColor('Very High')).toBe('#EF4444')
  })
})

describe('getRiskInterpretation', () => {
  it('should return conservative interpretation for score 1-3', () => {
    expect(getRiskInterpretation(1)).toContain('Conservative')
    expect(getRiskInterpretation(3)).toContain('Conservative')
  })

  it('should return balanced interpretation for score 4-5', () => {
    expect(getRiskInterpretation(4)).toContain('Balanced')
    expect(getRiskInterpretation(5)).toContain('Balanced')
  })

  it('should return aggressive interpretation for score 6-7', () => {
    expect(getRiskInterpretation(6)).toContain('Aggressive')
    expect(getRiskInterpretation(7)).toContain('Aggressive')
  })

  it('should return very aggressive interpretation for score 8-10', () => {
    expect(getRiskInterpretation(8)).toContain('Very Aggressive')
    expect(getRiskInterpretation(10)).toContain('Very Aggressive')
  })
})
