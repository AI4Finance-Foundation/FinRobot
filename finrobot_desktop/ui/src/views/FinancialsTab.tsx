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
import EarningsCallPanel from '../components/EarningsCallPanel'

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
        <h3 className="section-title">趋势</h3>
        <div className="chart-grid-2col">
          {historicalMetrics && (
            <>
              <RevenueEbitdaChart data={historicalToRevenueEbitdaData(historicalMetrics)} title="营收 & EBITDA" />
              <MarginTrendChart data={historicalToMarginData(historicalMetrics)} title="利润率走势" />
              <RevenueYoYChart data={historicalToRevenueYoYData(historicalMetrics)} title="营收同比增速" />
            </>
          )}
        </div>
      </section>

      {/* Structure Section */}
      <section className="chart-section">
        <h3 className="section-title">结构</h3>
        <div className="chart-grid-2col">
          {historicalMetrics && historicalMetrics.operating_cash_flow.length > 0 && (
            <CashFlowChart data={historicalToCashFlowData(historicalMetrics)} title="现金流拆解" />
          )}
          {quarterlyData && !qtrLoading && (
            <QuarterlyComparisonChart data={quarterlyToComparisonData(quarterlyData)} title="季度对比" />
          )}
        </div>
      </section>

      {/* Earnings Calls Section */}
      <section className="chart-section">
        <h3 className="section-title">财报电话会</h3>
        <EarningsCallPanel />
      </section>

      {/* Insights Section — parsed from research narrative */}
      {researchResult?.narrative && (
        <section className="chart-section">
          <h3 className="section-title">AI 洞察</h3>
          <InsightBlock
            title="资产负债分析"
            content={extractNarrativeSection(researchResult.narrative, ['balance sheet', 'financial position'])}
          />
          <InsightBlock
            title="现金流分析"
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
