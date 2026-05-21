// v5 §6.x 利润率趋势 — gross / EBITDA / operating margin overlayed
// from /api/data/{ticker}/historical. Reveals margin expansion or
// compression that the raw revenue bar chart hides.

import { useHistoricalData } from '../../hooks/useHistoricalData'
import MarginTrendChart from '../../components/charts/MarginTrendChart'

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card, #fff)',
}

interface MarginsTrendSectionProps {
  ticker: string
}

export function MarginsTrendSection({
  ticker: _ticker,
}: MarginsTrendSectionProps): React.ReactElement {
  const { data, isLoading, isError } = useHistoricalData()
  const chartData = transformToChartData(data)

  return (
    <section id="sec-margins" style={SECTION_STYLE}>
      <header style={{ marginBottom: 10 }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>📈 利润率趋势</h2>
        <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
          毛利 · EBITDA · 营业利润率多年走势
        </span>
      </header>

      {isLoading && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      )}
      {isError && (
        <p style={{ fontSize: 12, color: 'var(--red, #EF4444)' }}>加载失败</p>
      )}
      {chartData.length > 0 && <MarginTrendChart data={chartData} title="" />}
      {!isLoading && chartData.length === 0 && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>暂无利润率历史数据</p>
      )}
    </section>
  )
}

interface HistoricalShape {
  years?: number[]
  gross_margin?: number[]
  ebitda_margin?: number[]
  operating_margin?: number[]
}

function transformToChartData(
  data: HistoricalShape | undefined | null,
): Record<string, number | string | boolean | null>[] {
  if (!data?.years) return []
  const rows: Record<string, number | string | boolean | null>[] = []
  for (let i = 0; i < data.years.length; i++) {
    rows.push({
      year: String(data.years[i]),
      gross_margin: data.gross_margin?.[i] ?? null,
      ebitda_margin: data.ebitda_margin?.[i] ?? null,
      operating_margin: data.operating_margin?.[i] ?? null,
    })
  }
  return rows
}
