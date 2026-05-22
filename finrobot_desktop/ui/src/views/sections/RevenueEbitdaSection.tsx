// v5 §6.x 多年营收 + EBITDA — 5-year revenue/EBITDA bars from
// /api/data/{ticker}/historical. Forecast years (is_forecast=true) render
// at reduced opacity so users can tell hindsight from projection.

import { useHistoricalData } from '../../hooks/useHistoricalData'
import RevenueEbitdaChart from '../../components/charts/RevenueEbitdaChart'

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card)',
}

interface RevenueEbitdaSectionProps {
  ticker: string
}

export function RevenueEbitdaSection({
  ticker: _ticker,
}: RevenueEbitdaSectionProps): React.ReactElement {
  // useHistoricalData reads ticker from appStore. StockWorkspace mirrors
  // the URL param into appStore at mount, so by the time this section
  // renders the store ticker matches the prop.
  const { data, isLoading, isError } = useHistoricalData()

  const chartData = transformToChartData(data)

  return (
    <section id="sec-revenue" style={SECTION_STYLE}>
      <header style={{ marginBottom: 10 }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>📊 营收 & EBITDA 多年趋势</h2>
        {data?.cagr_revenue !== undefined && data?.cagr_revenue !== null && (
          <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
            收入 CAGR {(data.cagr_revenue * 100).toFixed(1)}%
          </span>
        )}
      </header>

      {isLoading && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>历史财务加载中…</p>
      )}
      {isError && (
        <p style={{ fontSize: 12, color: 'var(--danger)' }}>历史财务加载失败</p>
      )}
      {chartData.length > 0 && <RevenueEbitdaChart data={chartData} title="" />}
      {!isLoading && chartData.length === 0 && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>暂无多年财务数据</p>
      )}
    </section>
  )
}

// Mirrors HistoricalMetrics shape — backend returns parallel arrays, recharts
// wants array of objects keyed by `year`.
interface HistoricalShape {
  years?: number[]
  revenue?: number[]
  ebitda?: number[]
}

function transformToChartData(
  data: HistoricalShape | undefined | null,
): Record<string, number | string | boolean | null>[] {
  if (!data?.years || !data.revenue || !data.ebitda) return []
  const rows: Record<string, number | string | boolean | null>[] = []
  for (let i = 0; i < data.years.length; i++) {
    rows.push({
      year: String(data.years[i]),
      revenue: data.revenue[i] ?? null,
      ebitda: data.ebitda[i] ?? null,
      is_forecast: false,
    })
  }
  return rows
}
