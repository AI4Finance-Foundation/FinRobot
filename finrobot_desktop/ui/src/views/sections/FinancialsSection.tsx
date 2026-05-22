// v5 §6.8 财务报表 — 4 季度趋势表 (营收 / 毛利率 / 净利润 / YoY).
// Reads existing GET /api/data/{ticker}/quarterly so this section ships
// without touching the user's in-flight FinancialsTab refactor.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../../api/client'

// Mirror of finagent.engine.services.market_data.fetch_quarterly_data —
// yfinance only consistently exposes revenue / operating_income / net_income
// / operating_cash_flow per quarter; gross_profit / gross_margin are NOT
// reliable across tickers, so we surface operating margin instead.
interface QuarterRow {
  quarter?: string
  revenue?: number | null
  operating_income?: number | null
  net_income?: number | null
  operating_cash_flow?: number | null
}

interface QuarterlyResponse {
  ticker?: string
  quarters?: QuarterRow[]
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

  // YoY needs the quarter 4 rows back, so keep up to 8 and slice for display.
  const allRows = (data?.quarters ?? []).slice(0, 8)
  const enriched = computeYoY(allRows).slice(0, 4)
  const sparseYoY =
    allRows.length > 0 && allRows.length < 8 && enriched.length > 1

  return (
    <section id="sec-financials" className="cosmic-card" style={{ margin: "12px 0" }}>
      <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>💰 财务报表</h2>
      <p style={{ marginTop: 2, fontSize: 11, color: 'var(--text-faint)' }}>
        近 4 季度趋势 · 完整三表抽屉 待 v2.1
        {sparseYoY && ' · YoY 需 8 季度才能算齐，yfinance 当前只给出 ' + allRows.length + ' 季度'}
      </p>

      {isLoading && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      )}
      {isError && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--danger)' }}>
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
              <th style={cellStyle('right')}>经营利润率</th>
              <th style={cellStyle('right')}>净利润</th>
              <th style={cellStyle('right')}>YoY 营收</th>
            </tr>
          </thead>
          <tbody>
            {enriched.map((r, i) => {
              const opMargin =
                typeof r.operating_income === 'number' &&
                typeof r.revenue === 'number' &&
                r.revenue > 0
                  ? r.operating_income / r.revenue
                  : null
              return (
                <tr key={i}>
                  <td style={cellStyle('left')}>{r.quarter ?? '—'}</td>
                  <td style={cellStyle('right')}>{formatMoney(r.revenue)}</td>
                  <td style={cellStyle('right')}>{formatPct(opMargin)}</td>
                  <td style={cellStyle('right')}>{formatMoney(r.net_income)}</td>
                  <td style={{ ...cellStyle('right'), color: yoyColor(r.yoy) }}>
                    {formatPct(r.yoy)}
                  </td>
                </tr>
              )
            })}
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
  return v >= 0 ? 'var(--success)' : 'var(--danger)'
}
