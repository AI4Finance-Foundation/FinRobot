import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, BASE_URL } from '../api/client'
import { useAppStore } from '../stores/appStore'
import PriceChart from './charts/PriceChart'

interface PriceHistoryItem {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

function fmtUsd(val: number | null | undefined): string {
  if (val == null) return '\u2014'
  const abs = Math.abs(val)
  if (abs >= 1e12) return `$${(val / 1e12).toFixed(1)}T`
  if (abs >= 1e9) return `$${(val / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `$${(val / 1e6).toFixed(1)}M`
  return `$${val.toLocaleString()}`
}

function fmtPct(val: number | null | undefined): string {
  if (val == null) return '\u2014'
  return `${(val * 100).toFixed(1)}%`
}

function fmtMult(val: number | null | undefined): string {
  if (val == null) return '\u2014'
  return `${val.toFixed(1)}x`
}

function fmtPrice(val: number | null | undefined): string {
  if (val == null) return '\u2014'
  return `$${val.toFixed(2)}`
}

export default function StockOverview() {
  const ticker = useAppStore((s) => s.ticker)

  const { data: financials } = useQuery({
    queryKey: ['financials', ticker],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/data/{ticker}/financials', {
        params: { path: { ticker } },
      })
      if (error) throw error
      return data
    },
    enabled: !!ticker,
  })

  const { data: priceData, isError: isPriceError } = useQuery({
    queryKey: ['price', ticker],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/${ticker}/price`)
      if (!resp.ok) throw new Error('Failed to fetch price data')
      return resp.json() as Promise<{ history: PriceHistoryItem[]; data_source?: string }>
    },
    enabled: !!ticker,
  })

  const history = priceData?.history

  // Compute price change from last 2 trading days
  const setPriceChange = useAppStore((s) => s.setPriceChange)
  useEffect(() => {
    if (!history || history.length < 2) return
    const latest = history[history.length - 1]
    const prev = history[history.length - 2]
    if (prev.close > 0) {
      const change = latest.close - prev.close
      const changePct = (change / prev.close) * 100
      setPriceChange(change, changePct)
    }
  }, [history, setPriceChange])

  const income = financials?.income
  const market = financials?.market
  const valuation = financials?.valuation

  const ebitdaMargin = income && income.revenue > 0
    ? income.ebitda / income.revenue
    : null

  const has52w = market?.price_52w_low != null && market?.price_52w_high != null

  return (
    <div className="stock-overview animate-in">
      {/* KPI Cards — Glass Panel */}
      <div className="kpi-glass">
        <div className="kpi-grid">
          <KPICard label="Market Cap" value={fmtUsd(market?.market_cap)} loading={!financials} />
          <KPICard label="P/E Ratio" value={fmtMult(market?.pe_ratio)} loading={!financials} />
          <KPICard label="EV/EBITDA" value={fmtMult(valuation?.ev_ebitda)} loading={!financials} />
          <KPICard label="Revenue" value={fmtUsd(income?.revenue)} loading={!financials} />
          <KPICard label="EBITDA Margin" value={fmtPct(ebitdaMargin)} loading={!financials} />
          {has52w ? (
            <KPICard
              label="52W Range"
              value={`${fmtPrice(market!.price_52w_low)} \u2013 ${fmtPrice(market!.price_52w_high)}`}
            />
          ) : (
            <KPICard label="EV/Revenue" value={fmtMult(valuation?.ev_revenue)} loading={!financials} />
          )}
        </div>
      </div>

      {/* Price Chart */}
      {history && history.length > 0 && (
        <PriceChart data={history} title="Price History (1Y)" />
      )}

      {(!history || history.length === 0) && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">Price History</span>
          </div>
          <div className="card-body" style={{ minHeight: 180 }}>
            {isPriceError ? (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: 160,
                color: 'var(--text-muted)',
                fontSize: '0.78rem',
              }}>
                Price data unavailable
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
                <div className="skeleton" style={{ width: '100%', height: 120, borderRadius: 'var(--r-md)' }} />
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="skeleton" style={{ width: 40, height: 10 }} />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function KPICard({ label, value, loading }: { label: string; value: string; loading?: boolean }) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      {loading ? (
        <div className="skeleton" style={{ width: 60, height: 16, marginTop: 2 }} />
      ) : (
        <div className="kpi-value">{value}</div>
      )}
    </div>
  )
}
