/**
 * Risk Analysis Utilities
 * TypeScript port of mi_patrimonio/risk_analyzer.py
 * Calculates portfolio risk metrics: Sharpe Ratio, Volatility, VaR, etc.
 */

// Types
export type RiskCategory = 'Low' | 'Moderate' | 'High' | 'Very High'

export interface RiskMetrics {
  annualVolatility: number      // Annualized standard deviation (%)
  sharpeRatio: number           // (Return - Risk-free rate) / Volatility
  maxDrawdown: number           // Maximum estimated drawdown (%)
  beta: number                  // Market sensitivity
  var95: number                 // Value at Risk 95% daily (%)
  concentrationTop3: number     // % of portfolio in top 3 positions
  riskScore: number             // 1-10 (1=very low, 10=very high)
  riskCategory: RiskCategory    // Category label
}

export interface DistributionData {
  actual: number   // Current percentage
  objetivo: number // Target percentage
  valor: number    // Value in EUR
}

export interface PositionData {
  valor: number
  nombre?: string
  ticker?: string
}

// Constants (from Python RiskAnalyzer)
const VOLATILITY_BY_CLASS: Record<string, number> = {
  renta_variable: 18.0,
  renta_fija: 5.0,
  oro: 15.0,
  cripto: 60.0,
  liquidez: 0.5,
}

const BETA_BY_CLASS: Record<string, number> = {
  renta_variable: 1.0,
  renta_fija: 0.1,
  oro: 0.0,
  cripto: 1.5,
  liquidez: 0.0,
}

const RISK_FREE_RATE = 3.5 // % annual (ECB approximation)
const Z_SCORE_95 = 1.645   // For 95% confidence
const TRADING_DAYS = 252   // Days per year

/**
 * Calculate weighted portfolio volatility
 */
export function calculatePortfolioVolatility(
  distribution: Record<string, DistributionData>
): number {
  let volatilitySquared = 0

  for (const [assetClass, data] of Object.entries(distribution)) {
    const weight = (data.actual || 0) / 100 // Convert to decimal
    const classVolatility = VOLATILITY_BY_CLASS[assetClass] ?? 15.0
    // Simplified: sum variances (assuming partial correlation)
    volatilitySquared += Math.pow(weight * classVolatility, 2)
  }

  // Add approximate correlation factor (0.5 between assets)
  const volatility = Math.sqrt(volatilitySquared) * 1.3

  return volatility
}

/**
 * Calculate Sharpe Ratio
 */
export function calculateSharpeRatio(
  returnPct: number,
  volatility: number
): number {
  if (volatility <= 0) return 0
  return (returnPct - RISK_FREE_RATE) / volatility
}

/**
 * Calculate weighted portfolio beta
 */
export function calculatePortfolioBeta(
  distribution: Record<string, DistributionData>
): number {
  let totalBeta = 0

  for (const [assetClass, data] of Object.entries(distribution)) {
    const weight = (data.actual || 0) / 100
    const classBeta = BETA_BY_CLASS[assetClass] ?? 1.0
    totalBeta += weight * classBeta
  }

  return totalBeta
}

/**
 * Calculate Value at Risk at 95% confidence (daily)
 */
export function calculateVaR95(volatility: number): number {
  // Parametric VaR with normal distribution
  const dailyVolatility = volatility / Math.sqrt(TRADING_DAYS)
  const var95 = dailyVolatility * Z_SCORE_95
  return var95
}

/**
 * Calculate concentration in top 3 positions
 */
export function calculateConcentration(
  positions: Record<string, PositionData>
): number {
  if (!positions || Object.keys(positions).length === 0) return 0

  const values = Object.values(positions).map(p => p.valor || 0)
  const total = values.reduce((sum, v) => sum + v, 0)

  if (total <= 0) return 0

  // Sort descending and take top 3
  const top3 = values.sort((a, b) => b - a).slice(0, 3)
  const concentration = (top3.reduce((sum, v) => sum + v, 0) / total) * 100

  return concentration
}

/**
 * Estimate maximum drawdown based on volatility
 */
export function estimateMaxDrawdown(volatility: number, beta: number): number {
  // Empirical rule: Max Drawdown ~ 3-5x monthly volatility
  // Adjusted by beta
  const monthlyVolatility = volatility / Math.sqrt(12)
  const maxDrawdown = monthlyVolatility * 4 * (0.5 + 0.5 * beta)
  return Math.min(maxDrawdown, 80) // Cap at 80%
}

/**
 * Calculate risk score (1-10) and category
 */
export function calculateRiskScore(
  volatility: number,
  beta: number,
  concentration: number
): { score: number; category: RiskCategory } {
  // Weighting: 50% volatility, 30% beta, 20% concentration
  const volatilityScore = Math.min(volatility / 5, 10) // 50% vol = score 10
  const betaScore = Math.min(beta * 5, 10)             // Beta 2 = score 10
  const concentrationScore = Math.min(concentration / 10, 10) // 100% = score 10

  const totalScore = volatilityScore * 0.5 + betaScore * 0.3 + concentrationScore * 0.2
  const score = Math.max(1, Math.min(10, Math.round(totalScore)))

  let category: RiskCategory
  if (score <= 3) {
    category = 'Low'
  } else if (score <= 5) {
    category = 'Moderate'
  } else if (score <= 7) {
    category = 'High'
  } else {
    category = 'Very High'
  }

  return { score, category }
}

/**
 * Calculate all risk metrics for a portfolio
 */
export function calculateRiskMetrics(
  distribution: Record<string, DistributionData>,
  positions: Record<string, PositionData>,
  ytdReturn: number = 0
): RiskMetrics {
  // 1. Calculate weighted portfolio volatility
  const volatility = calculatePortfolioVolatility(distribution)

  // 2. Calculate Sharpe Ratio
  const sharpe = calculateSharpeRatio(ytdReturn, volatility)

  // 3. Calculate weighted beta
  const beta = calculatePortfolioBeta(distribution)

  // 4. Calculate VaR 95%
  const var95 = calculateVaR95(volatility)

  // 5. Calculate concentration
  const concentration = calculateConcentration(positions)

  // 6. Estimate max drawdown
  const maxDrawdown = estimateMaxDrawdown(volatility, beta)

  // 7. Calculate risk score
  const { score, category } = calculateRiskScore(volatility, beta, concentration)

  return {
    annualVolatility: Math.round(volatility * 100) / 100,
    sharpeRatio: Math.round(sharpe * 100) / 100,
    maxDrawdown: Math.round(maxDrawdown * 100) / 100,
    beta: Math.round(beta * 100) / 100,
    var95: Math.round(var95 * 100) / 100,
    concentrationTop3: Math.round(concentration * 100) / 100,
    riskScore: score,
    riskCategory: category,
  }
}

/**
 * Get interpretation text for a metric
 */
export function getVolatilityInterpretation(volatility: number): string {
  if (volatility < 10) return 'Low'
  if (volatility < 20) return 'Medium'
  return 'High'
}

export function getSharpeInterpretation(sharpe: number): string {
  if (sharpe > 1) return 'Excellent'
  if (sharpe > 0.5) return 'Good'
  if (sharpe > 0) return 'Fair'
  return 'Negative'
}

export function getBetaInterpretation(beta: number): string {
  if (beta < 0.8) return 'Defensive'
  if (beta < 1.2) return 'Neutral'
  return 'Aggressive'
}

export function getConcentrationInterpretation(concentration: number): string {
  if (concentration < 50) return 'Diversified'
  if (concentration < 70) return 'Concentrated'
  return 'Very Concentrated'
}

/**
 * Get emoji for risk category
 */
export function getRiskEmoji(category: RiskCategory): string {
  const emojis: Record<RiskCategory, string> = {
    'Low': '🟢',
    'Moderate': '🟡',
    'High': '🟠',
    'Very High': '🔴',
  }
  return emojis[category]
}

/**
 * Get color for risk category (Tailwind classes)
 */
export function getRiskColor(category: RiskCategory): string {
  const colors: Record<RiskCategory, string> = {
    'Low': '#22C55E',      // green-500
    'Moderate': '#F59E0B', // amber-500
    'High': '#F97316',     // orange-500
    'Very High': '#EF4444', // red-500
  }
  return colors[category]
}

/**
 * Get interpretation paragraph for risk score
 */
export function getRiskInterpretation(score: number): string {
  if (score <= 3) {
    return 'Conservative Portfolio: Low risk of significant losses. Suitable for investors with low risk tolerance or short horizon.'
  } else if (score <= 5) {
    return 'Balanced Portfolio: Moderate risk with reasonable growth potential. Suitable for most investors with medium-long horizon.'
  } else if (score <= 7) {
    return 'Aggressive Portfolio: Higher exposure to volatility and potential losses. Suitable for investors with high tolerance and long horizon (+10 years).'
  } else {
    return 'Very Aggressive Portfolio: High risk of significant losses. Only recommended for experienced investors with capital they can afford to lose.'
  }
}
