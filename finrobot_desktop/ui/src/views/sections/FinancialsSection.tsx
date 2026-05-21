// v5 §6.8 财务报表 — 4 季度趋势表 (营收 / 毛利率 / 净利润 / YoY).
// Reads existing GET /api/data/{ticker}/quarterly so this section ships
// without touching the user's in-flight FinancialsTab refactor.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../../api/client'

interface QuarterRow {
  period?: string
  fiscal_period?: string
  date?: string
  revenue?: number | null
  gross_profit?: number | null
  gross_margin?: number | null
  net_income?: number | null
}

interface QuarterlyResponse {
  quarters?: QuarterRow[]
  data?: QuarterRow[]
  income_statement?: QuarterRow[]
}

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card, #fff)',
}

interface FinancialsSectionProps {
  ticker: string
}

export function FinancialsSection({ ticker }: FinancialsSectionProps): React.ReactElement {
  const { data, isLoading, isError } = useQuery<QuarterlyResponse, Error>({
    queryKey: ['quarterly', ticker],
    queryFn: async () => {
      const r = await fetch(`${BASE_URL}/api/data/${ticker}/quarterly`)
      if (!r.ok) throw new Error(`${r.status}`)
      return (await r.json()) as QuarterlyResponse
    },
    enabled: !!ticker,
    staleTime: 24 * 60 * 60_000,
    refetchOnMount: false,
  })

  const rows = (data?.quarters ?? data?.data ?? data?.income_statement ?? []).slice(0, 4)
  const enriched = computeYoY(rows)

  return (
    <section id="sec-financials" style={SECTION_STYLE}>
      <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>💰 财务报表</h2>
      <p style={{ marginTop: 2, fontSize: 11, color: 'var(--text-faint)' }}>
        近 4 季度趋势 · 完整三表抽屉 待 v2.1
      </p>

      {isLoading && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      )}
      {isError && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--red, #EF4444)' }}>
          财务数据加载失败
        </p>
      )}

      {enriched.length > 0 && (
        <table
          data-testid="financials-table"
          style={{
            marginTop: 12,
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: 12,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          <thead>
            <tr style={{ color: 'var(--text-faint)' }}>
              <th style={cellStyle('left')}>季度</th>
              <th style={cellStyle('right')}>营收</th>
              <th style={cellStyle('right')}>毛利率</th>
              <th style={cellStyle('right')}>净利润</th>
              <th style={cellStyle('right')}>YoY 营收</th>
            </tr>
          </thead>
          <tbody>
            {enriched.map((r, i) => (
              <tr key={i}>
                <td style={cellStyle('left')}>{r.period ?? r.fiscal_period ?? r.date ?? '—'}</td>
                <td style={cellStyle('right')}>{formatMoney(r.revenue)}</td>
                <td style={cellStyle('right')}>{formatPct(r.gross_margin)}</td>
                <td style={cellStyle('right')}>{formatMoney(r.net_income)}</td>
                <td style={{ ...cellStyle('right'), color: yoyColor(r.yoy) }}>
                  {formatPct(r.yoy)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function computeYoY(rows: QuarterRow[]): (QuarterRow & { yoy: number | null })[] {
  return rows.map((row, idx) => {
    const yearAgo = rows[idx + 4]
    const yoy =
      row.revenue && yearAgo?.revenue && yearAgo.revenue > 0
        ? (row.revenue - yearAgo.revenue) / yearAgo.revenue
        : null
    return { ...row, yoy }
  })
}

function cellStyle(align: 'left' | 'right'): React.CSSProperties {
  return {
    padding: '6px 8px',
    borderBottom: '1px solid var(--border-soft)',
    textAlign: align,
  }
}

function formatMoney(v?: number | null): string {
  if (v === undefined || v === null) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  return `$${v.toLocaleString()}`
}

function formatPct(v: number | null | undefined): string {
  if (v === undefined || v === null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function yoyColor(v: number | null): string {
  if (v === null) return 'var(--text-faint)'
  return v >= 0 ? 'var(--green, #10B981)' : 'var(--red, #EF4444)'
}
