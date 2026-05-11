import { useAppStore } from '../stores/appStore'
import { useHistoricalData, useQuarterlyData } from '../hooks/useHistoricalData'
import {
  RevenueEbitdaChart, MarginTrendChart, CashFlowChart,
  QuarterlyComparisonChart, RevenueYoYChart,
} from '../components/charts'
import {
  historicalToRevenueEbitdaData, historicalToMarginData,
  historicalToRevenueYoYData, historicalToCashFlowData,
  quarterlyToComparisonData,
} from '../utils/chartAdapters'
import { extractNarrativeSection } from '../utils/narrativeParser'

export default function FinancialsTab() {
  const { isLoading: histLoading } = useHistoricalData()
  const { isLoading: qtrLoading } = useQuarterlyData()
  const historicalMetrics = useAppStore((s) => s.historicalMetrics)
  const quarterlyData = useAppStore((s) => s.quarterlyData)
  const researchResult = useAppStore((s) => s.researchResult)

  if (histLoading) return <div className="loading-skeleton" />

  return (
    <div className="tab-content financials-tab">
      {/* Trends Section */}
      <section className="chart-section">
        <h3 className="section-title">Trends</h3>
        <div className="chart-grid-2col">
          {historicalMetrics && (
            <>
              <RevenueEbitdaChart data={historicalToRevenueEbitdaData(historicalMetrics)} title="Revenue & EBITDA" />
              <MarginTrendChart data={historicalToMarginData(historicalMetrics)} title="Margin Trends" />
              <RevenueYoYChart data={historicalToRevenueYoYData(historicalMetrics)} title="Revenue YoY Growth" />
            </>
          )}
        </div>
      </section>

      {/* Structure Section */}
      <section className="chart-section">
        <h3 className="section-title">Structure</h3>
        <div className="chart-grid-2col">
          {historicalMetrics && historicalMetrics.operating_cash_flow.length > 0 && (
            <CashFlowChart data={historicalToCashFlowData(historicalMetrics)} title="Cash Flow Breakdown" />
          )}
          {quarterlyData && !qtrLoading && (
            <QuarterlyComparisonChart data={quarterlyToComparisonData(quarterlyData)} title="Quarterly Comparison" />
          )}
        </div>
      </section>

      {/* Insights Section — parsed from research narrative */}
      {researchResult?.narrative && (
        <section className="chart-section">
          <h3 className="section-title">AI Insights</h3>
          <InsightBlock
            title="Balance Sheet Analysis"
            content={extractNarrativeSection(researchResult.narrative, ['balance sheet', 'financial position'])}
          />
          <InsightBlock
            title="Cash Flow Analysis"
            content={extractNarrativeSection(researchResult.narrative, ['cash flow', 'liquidity'])}
          />
        </section>
      )}
    </div>
  )
}

function InsightBlock({ title, content }: { title: string; content: string | null }) {
  if (!content) return null
  return (
    <details className="insight-block">
      <summary className="insight-title">{title}</summary>
      <div className="insight-content">{content}</div>
    </details>
  )
}
