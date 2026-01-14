'use client'

import { Activity, TrendingDown, Target, AlertTriangle, PieChart as PieChartIcon, Percent, BarChart3, Shield } from 'lucide-react'
import { PortfolioId, ALL_PORTFOLIOS } from '@/lib/portfolioData'
import { useRiskMetrics } from '@/lib/useRiskMetrics'
import {
  getRiskColor,
  getRiskEmoji,
  getRiskInterpretation,
  getVolatilityInterpretation,
  getSharpeInterpretation,
  getBetaInterpretation,
  getConcentrationInterpretation,
  RiskCategory,
} from '@/lib/riskAnalysis'
import DistributionPieChart from './DistributionPieChart'

interface Props {
  portfolioId: PortfolioId
}

export default function RiskAnalysis({ portfolioId }: Props) {
  const portfolio = ALL_PORTFOLIOS[portfolioId]
  const { riskMetrics, loading, error } = useRiskMetrics(portfolioId)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4" />
          <p className="text-gray-600">Calculating risk metrics...</p>
        </div>
      </div>
    )
  }

  if (error || !riskMetrics) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-6">
        <h3 className="font-semibold text-red-900 mb-2">Error calculating risk metrics</h3>
        <p className="text-red-800">{error || 'Unable to calculate metrics'}</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-gradient-to-r from-blue-50 to-purple-50 rounded-lg p-6 border border-blue-100">
        <h2 className="text-2xl font-bold text-slate-800 mb-1">Risk Analysis</h2>
        <p className="text-slate-600">
          Portfolio: <strong>{portfolio.nombre}</strong> ({portfolio.titular})
        </p>
      </div>

      {/* Risk Score Card - Large */}
      <RiskScoreCard
        score={riskMetrics.riskScore}
        category={riskMetrics.riskCategory}
      />

      {/* Metric Cards Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          title="Annual Volatility"
          value={`${riskMetrics.annualVolatility.toFixed(1)}%`}
          interpretation={getVolatilityInterpretation(riskMetrics.annualVolatility)}
          icon={<Activity className="w-5 h-5" />}
          iconColor="text-blue-500"
        />
        <MetricCard
          title="Sharpe Ratio"
          value={riskMetrics.sharpeRatio.toFixed(2)}
          interpretation={getSharpeInterpretation(riskMetrics.sharpeRatio)}
          icon={<BarChart3 className="w-5 h-5" />}
          iconColor="text-green-500"
        />
        <MetricCard
          title="Beta"
          value={riskMetrics.beta.toFixed(2)}
          interpretation={getBetaInterpretation(riskMetrics.beta)}
          icon={<Target className="w-5 h-5" />}
          iconColor="text-purple-500"
        />
        <MetricCard
          title="VaR 95% (Daily)"
          value={`${riskMetrics.var95.toFixed(2)}%`}
          interpretation="Max daily loss"
          icon={<AlertTriangle className="w-5 h-5" />}
          iconColor="text-orange-500"
        />
        <MetricCard
          title="Max Drawdown Est."
          value={`${riskMetrics.maxDrawdown.toFixed(1)}%`}
          interpretation="Expected max decline"
          icon={<TrendingDown className="w-5 h-5" />}
          iconColor="text-red-500"
        />
        <MetricCard
          title="Top 3 Concentration"
          value={`${riskMetrics.concentrationTop3.toFixed(1)}%`}
          interpretation={getConcentrationInterpretation(riskMetrics.concentrationTop3)}
          icon={<PieChartIcon className="w-5 h-5" />}
          iconColor="text-indigo-500"
        />
        <MetricCard
          title="Risk Score"
          value={`${riskMetrics.riskScore}/10`}
          interpretation={riskMetrics.riskCategory}
          icon={<Shield className="w-5 h-5" />}
          iconColor="text-amber-500"
        />
        <MetricCard
          title="Risk-Free Rate"
          value="3.5%"
          interpretation="ECB Reference"
          icon={<Percent className="w-5 h-5" />}
          iconColor="text-gray-500"
        />
      </div>

      {/* Distribution & Interpretation */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Distribution Pie Chart */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <PieChartIcon className="w-5 h-5 text-blue-600" />
            Asset Distribution
          </h3>
          <DistributionPieChart
            distribution={portfolio.distribucion}
            size="medium"
          />
        </div>

        {/* Risk Interpretation */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Shield className="w-5 h-5 text-amber-600" />
            Risk Interpretation
          </h3>
          <RiskInterpretationCard
            score={riskMetrics.riskScore}
            category={riskMetrics.riskCategory}
            volatility={riskMetrics.annualVolatility}
            sharpe={riskMetrics.sharpeRatio}
            beta={riskMetrics.beta}
          />
        </div>
      </div>

      {/* Detailed Metrics Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="text-lg font-semibold">Detailed Risk Metrics</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Metric</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Value</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Interpretation</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              <MetricRow
                metric="Annual Volatility"
                value={`${riskMetrics.annualVolatility.toFixed(2)}%`}
                interpretation={getVolatilityInterpretation(riskMetrics.annualVolatility)}
                description="Annualized standard deviation of returns"
              />
              <MetricRow
                metric="Sharpe Ratio"
                value={riskMetrics.sharpeRatio.toFixed(2)}
                interpretation={getSharpeInterpretation(riskMetrics.sharpeRatio)}
                description="Risk-adjusted return (higher is better)"
              />
              <MetricRow
                metric="Beta"
                value={riskMetrics.beta.toFixed(2)}
                interpretation={getBetaInterpretation(riskMetrics.beta)}
                description="Market sensitivity (1 = market average)"
              />
              <MetricRow
                metric="VaR 95%"
                value={`${riskMetrics.var95.toFixed(2)}%`}
                interpretation="Daily loss limit"
                description="Max expected daily loss at 95% confidence"
              />
              <MetricRow
                metric="Max Drawdown Est."
                value={`${riskMetrics.maxDrawdown.toFixed(2)}%`}
                interpretation="Potential decline"
                description="Estimated max peak-to-trough decline"
              />
              <MetricRow
                metric="Top 3 Concentration"
                value={`${riskMetrics.concentrationTop3.toFixed(2)}%`}
                interpretation={getConcentrationInterpretation(riskMetrics.concentrationTop3)}
                description="Portfolio weight in largest positions"
              />
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function RiskScoreCard({
  score,
  category,
}: {
  score: number
  category: RiskCategory
}) {
  const color = getRiskColor(category)
  const emoji = getRiskEmoji(category)
  const percentage = (score / 10) * 100

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">Overall Risk Score</h3>
        <span className="text-2xl">{emoji}</span>
      </div>

      {/* Score Gauge */}
      <div className="relative h-4 bg-gray-200 rounded-full overflow-hidden mb-4">
        <div
          className="absolute h-full rounded-full transition-all duration-500"
          style={{ width: `${percentage}%`, backgroundColor: color }}
        />
        {/* Markers */}
        <div className="absolute inset-0 flex">
          <div className="w-[30%] border-r border-white/50" />
          <div className="w-[20%] border-r border-white/50" />
          <div className="w-[20%] border-r border-white/50" />
          <div className="w-[30%]" />
        </div>
      </div>

      {/* Labels */}
      <div className="flex justify-between text-xs text-gray-500 mb-4">
        <span>Low (1-3)</span>
        <span>Moderate (4-5)</span>
        <span>High (6-7)</span>
        <span>Very High (8-10)</span>
      </div>

      {/* Score Display */}
      <div className="text-center">
        <div className="text-5xl font-bold" style={{ color }}>
          {score}
          <span className="text-2xl text-gray-400">/10</span>
        </div>
        <div className="text-lg font-medium mt-2" style={{ color }}>
          {category} Risk
        </div>
      </div>
    </div>
  )
}

function MetricCard({
  title,
  value,
  interpretation,
  icon,
  iconColor,
}: {
  title: string
  value: string
  interpretation: string
  icon: React.ReactNode
  iconColor: string
}) {
  return (
    <div className="bg-white rounded-lg shadow p-4 hover:shadow-md transition-shadow">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-600">{title}</span>
        <div className={iconColor}>{icon}</div>
      </div>
      <div className="text-2xl font-bold text-gray-900">{value}</div>
      <div className="text-xs text-gray-500 mt-1">{interpretation}</div>
    </div>
  )
}

function MetricRow({
  metric,
  value,
  interpretation,
  description,
}: {
  metric: string
  value: string
  interpretation: string
  description: string
}) {
  return (
    <tr className="hover:bg-gray-50">
      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
        {metric}
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-sm text-right font-bold text-gray-900">
        {value}
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
        {interpretation}
      </td>
      <td className="px-6 py-4 text-sm text-gray-500">
        {description}
      </td>
    </tr>
  )
}

function RiskInterpretationCard({
  score,
  category,
  volatility,
  sharpe,
  beta,
}: {
  score: number
  category: RiskCategory
  volatility: number
  sharpe: number
  beta: number
}) {
  const interpretation = getRiskInterpretation(score)
  const color = getRiskColor(category)

  return (
    <div className="space-y-4">
      <div
        className="p-4 rounded-lg border-l-4"
        style={{ borderColor: color, backgroundColor: `${color}10` }}
      >
        <p className="text-sm text-gray-700">{interpretation}</p>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-600">Volatility Assessment:</span>
          <span className="font-medium">
            {volatility < 10 ? 'Low volatility, stable returns' :
             volatility < 20 ? 'Moderate volatility, normal fluctuations' :
             'High volatility, significant swings expected'}
          </span>
        </div>

        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-600">Return Efficiency:</span>
          <span className="font-medium">
            {sharpe > 1 ? 'Excellent risk-adjusted returns' :
             sharpe > 0.5 ? 'Good risk-adjusted returns' :
             sharpe > 0 ? 'Returns barely compensate for risk' :
             'Negative returns relative to risk-free rate'}
          </span>
        </div>

        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-600">Market Sensitivity:</span>
          <span className="font-medium">
            {beta < 0.8 ? 'Defensive - less volatile than market' :
             beta < 1.2 ? 'Neutral - moves with market' :
             'Aggressive - more volatile than market'}
          </span>
        </div>
      </div>

      {score <= 3 && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-3 mt-4">
          <p className="text-sm text-green-800">
            <strong>Recommendation:</strong> Portfolio is well-suited for capital preservation.
            Consider if you want slightly higher returns with minimal additional risk.
          </p>
        </div>
      )}

      {score > 3 && score <= 5 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mt-4">
          <p className="text-sm text-yellow-800">
            <strong>Recommendation:</strong> Balanced approach appropriate for most investors.
            Monitor periodically and rebalance when allocation drifts significantly.
          </p>
        </div>
      )}

      {score > 5 && (
        <div className="bg-orange-50 border border-orange-200 rounded-lg p-3 mt-4">
          <p className="text-sm text-orange-800">
            <strong>Recommendation:</strong> Higher risk portfolio suitable for long-term horizon.
            Ensure you can withstand significant short-term losses without needing to liquidate.
          </p>
        </div>
      )}
    </div>
  )
}
