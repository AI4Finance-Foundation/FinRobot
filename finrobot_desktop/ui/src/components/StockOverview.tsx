import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, BASE_URL } from '../api/client'
import { useAppStore } from '../stores/appStore'
import { fmtUsd, fmtPct, fmtMult, fmtPrice } from '../utils/formatters'
import PriceChart from './charts/PriceChart'

interface PriceHistoryItem {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
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

  // Derive sparkline data from price history (last 20 data points, sampled)
  const priceSpark = useMemo(() => {
    if (!history || history.length < 5) return undefined
    const step = Math.max(1, Math.floor(history.length / 20))
    const sampled: number[] = []
    for (let i = 0; i < history.length; i += step) {
      sampled.push(history[i].close)
    }
    // Always include the last point
    if (sampled[sampled.length - 1] !== history[history.length - 1].close) {
      sampled.push(history[history.length - 1].close)
    }
    return sampled
  }, [history])

  const volumeSpark = useMemo(() => {
    if (!history || history.length < 5) return undefined
    const recent = history.slice(-20)
    return recent.map((h) => h.volume)
  }, [history])

  // 52W range position (0..1)
  const rangePosition = has52w && history?.length
    ? (history[history.length - 1].close - market!.price_52w_low!) /
      (market!.price_52w_high! - market!.price_52w_low!)
    : null

  return (
    <div className="stock-overview animate-in">
      {/* KPI Cards — Glass Panel */}
      <div className="kpi-glass">
        <div className="kpi-grid">
          <KPICard label="Market Cap" value={fmtUsd(market?.market_cap)} loading={!financials} trend={priceSpark} />
          <KPICard label="P/E Ratio" value={fmtMult(market?.pe_ratio)} loading={!financials} />
          <KPICard label="EV/EBITDA" value={fmtMult(valuation?.ev_ebitda)} loading={!financials} />
          <KPICard label="Revenue" value={fmtUsd(income?.revenue)} loading={!financials} trend={volumeSpark} trendColor="var(--gold)" />
          <KPICard label="EBITDA Margin" value={fmtPct(ebitdaMargin)} loading={!financials} />
          {has52w ? (
            <KPICard
              label="52W Range"
              value={`${fmtPrice(market!.price_52w_low)} \u2013 ${fmtPrice(market!.price_52w_high)}`}
              rangePosition={rangePosition}
            />
          ) : (
            <KPICard label="EV/Revenue" value={fmtMult(valuation?.ev_revenue)} loading={!financials} />
          )}
        </div>
      </div>

      {/* Price Chart */}
      {history && history.length > 0 && (
        <PriceChart data={history} title="Price History" />
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

function KPICard({
  label,
  value,
  loading,
  trend,
  trendColor,
  rangePosition,
}: {
  label: string
  value: string
  loading?: boolean
  trend?: number[]
  trendColor?: string
  rangePosition?: number | null
}) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      {loading ? (
        <div className="skeleton" style={{ width: 60, height: 16, marginTop: 2 }} />
      ) : (
        <div className="kpi-row">
          <div className="kpi-value">{value}</div>
          {trend && trend.length > 2 && <Sparkline data={trend} color={trendColor} />}
          {rangePosition != null && <RangeBar position={rangePosition} />}
        </div>
      )}
    </div>
  )
}

/** Tiny 48x16 SVG sparkline */
function Sparkline({ data, color }: { data: number[]; color?: string }) {
  const w = 48
  const h = 16
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1

  // Determine color from trend direction
  const isUp = data[data.length - 1] >= data[0]
  const stroke = color ?? (isUp ? 'var(--positive)' : 'var(--negative)')

  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w
      const y = h - ((v - min) / range) * (h - 2) - 1
      return `${x},${y}`
    })
    .join(' ')

  return (
    <svg className="kpi-sparkline" width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** 52W range position indicator */
function RangeBar({ position }: { position: number }) {
  const clamped = Math.max(0, Math.min(1, position))
  return (
    <div className="kpi-range-bar">
      <div className="kpi-range-track">
        <div
          className="kpi-range-dot"
          style={{ left: `${clamped * 100}%` }}
        />
      </div>
    </div>
  )
}
