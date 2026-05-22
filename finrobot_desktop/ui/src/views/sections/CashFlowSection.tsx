// v5 §6.x 现金流分布 — operating / investing / financing CF bars +
// net cash-flow line. Reveals whether earnings turn into actual cash:
// reported profits with chronically negative operating CF are a red flag
// the income statement hides.

import { useHistoricalData } from '../../hooks/useHistoricalData'
import CashFlowChart from '../../components/charts/CashFlowChart'

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card)',
}

interface CashFlowSectionProps {
  ticker: string
}

export function CashFlowSection({
  ticker: _ticker,
}: CashFlowSectionProps): React.ReactElement {
  const { data, isLoading, isError } = useHistoricalData()
  const chartData = transformToChartData(data)

  return (
    <section id="sec-cashflow" style={SECTION_STYLE}>
      <header style={{ marginBottom: 10 }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>💧 现金流分布</h2>
        <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
          营业 / 投资 / 融资 + 净现金（柱+折线）
        </span>
      </header>

      {isLoading && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      )}
      {isError && (
        <p style={{ fontSize: 12, color: 'var(--danger)' }}>加载失败</p>
      )}
      {chartData.length > 0 && <CashFlowChart data={chartData} title="" />}
      {!isLoading && chartData.length === 0 && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>该公司未披露分项现金流</p>
      )}
    </section>
  )
}

interface HistoricalShape {
  years?: number[]
  operating_cash_flow?: number[]
  investing_cash_flow?: number[]
  financing_cash_flow?: number[]
}

function transformToChartData(
  data: HistoricalShape | undefined | null,
): { year: string; operating: number; investing: number; financing: number }[] {
  if (
    !data?.years ||
    !data.operating_cash_flow?.length ||
    data.operating_cash_flow.length !== data.years.length
  ) {
    return []
  }
  const rows: { year: string; operating: number; investing: number; financing: number }[] = []
  for (let i = 0; i < data.years.length; i++) {
    rows.push({
      year: String(data.years[i]),
      operating: data.operating_cash_flow[i] ?? 0,
      investing: data.investing_cash_flow?.[i] ?? 0,
      financing: data.financing_cash_flow?.[i] ?? 0,
    })
  }
  return rows
}
