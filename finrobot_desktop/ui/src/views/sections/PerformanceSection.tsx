// v5 §6.9 走势分析 — 4 cards: YTD / 波动率 / 夏普 / 距 52w 高.
// Computes locally from 1y price history (GET /api/data/{ticker}/price?period=1y);
// no new backend needed. FinRobot 12 种专业图保留 [12 种走势图 ▸] 链接占位.

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../../api/client'

interface PriceHistoryPoint {
  date: string
  close: number
  open?: number
  high?: number
  low?: number
}

interface PriceResponse {
  price_history?: PriceHistoryPoint[]
  history?: PriceHistoryPoint[]
}


interface PerformanceSectionProps {
  ticker: string
}

export function PerformanceSection({ ticker }: PerformanceSectionProps): React.ReactElement {
  const { data, isLoading } = useQuery<PriceResponse, Error>({
    queryKey: ['price-1y', ticker],
    queryFn: async () => {
      const r = await fetch(`${BASE_URL}/api/data/${ticker}/price?period=1y`)
      if (!r.ok) throw new Error(`${r.status}`)
      return (await r.json()) as PriceResponse
    },
    enabled: !!ticker,
    staleTime: 15 * 60_000,
    refetchOnMount: false,
  })

  const history = data?.price_history ?? data?.history ?? []
  const metrics = history.length >= 30 ? computeMetrics(history) : null

  return (
    <section id="sec-performance" className="cosmic-card" style={{ margin: "12px 0" }}>
      <header>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>📈 走势分析</h2>
        <p style={{ margin: '2px 0 0', fontSize: 11, color: 'var(--text-faint)' }}>
          基于近 1 年日收盘价计算
        </p>
      </header>

      {isLoading && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      )}
      {!isLoading && !metrics && (
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--text-faint)' }}>
          价格历史数据不足，无法计算走势指标
        </p>
      )}

      {metrics && (
        <div
          style={{
            marginTop: 12,
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 10,
          }}
        >
          <Card label="YTD 涨幅" value={formatPct(metrics.ytdReturn)} color={metricColor(metrics.ytdReturn)} />
          <Card label="年化波动率" value={formatPct(metrics.volatility)} color="var(--text)" />
          <Card label="夏普比率" value={metrics.sharpe.toFixed(2)} color={metrics.sharpe >= 1 ? 'var(--success)' : 'var(--text)'} />
          <Card
            label="距 52w 高"
            value={formatPct(metrics.fromHigh)}
            color={metricColor(metrics.fromHigh)}
          />
        </div>
      )}
    </section>
  )
}

interface CardProps {
  label: string
  value: string
  color?: string
}

function Card({ label, value, color }: CardProps): React.ReactElement {
  return (
    <div
      style={{
        border: '1px solid var(--border-soft)',
        borderRadius: 8,
        padding: 14,
      }}
    >
      <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>{label}</div>
      <div
        style={{
          fontSize: 20,
          fontWeight: 700,
          marginTop: 4,
          color: color ?? 'var(--text)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </div>
    </div>
  )
}

interface PerfMetrics {
  ytdReturn: number
  volatility: number
  sharpe: number
  fromHigh: number
}

function computeMetrics(history: PriceHistoryPoint[]): PerfMetrics {
  const sorted = [...history].sort((a, b) => a.date.localeCompare(b.date))
  const closes = sorted.map((p) => p.close).filter((c) => Number.isFinite(c) && c > 0)
  if (closes.length < 30) {
    return { ytdReturn: 0, volatility: 0, sharpe: 0, fromHigh: 0 }
  }
  // YTD = first vs last close in current calendar year
  const year = new Date(sorted[sorted.length - 1].date).getFullYear()
  const yearStart = sorted.find((p) => new Date(p.date).getFullYear() === year)
  const ytdReturn =
    yearStart && yearStart.close > 0
      ? (closes[closes.length - 1] - yearStart.close) / yearStart.close
      : 0

  // Daily log returns → annualized volatility
  const dailyReturns: number[] = []
  for (let i = 1; i < closes.length; i++) {
    if (closes[i - 1] > 0) {
      dailyReturns.push(Math.log(closes[i] / closes[i - 1]))
    }
  }
  const mean = dailyReturns.reduce((s, x) => s + x, 0) / dailyReturns.length
  const variance =
    dailyReturns.reduce((s, x) => s + (x - mean) ** 2, 0) / dailyReturns.length
  const dailyStd = Math.sqrt(variance)
  const volatility = dailyStd * Math.sqrt(252)

  // Sharpe — geometric annualised return (exp(mean·252) - 1) less risk-free 4%
  // divided by annualised vol. Using the arithmetic `mean·252` understates
  // returns whenever there's compounding (i.e. always), which biased the
  // ratio low for momentum names and high for choppy ones.
  const annReturn = Math.exp(mean * 252) - 1
  const sharpe = volatility > 0 ? (annReturn - 0.04) / volatility : 0

  const high = Math.max(...closes)
  const fromHigh = (closes[closes.length - 1] - high) / high

  return { ytdReturn, volatility, sharpe, fromHigh }
}

function formatPct(v: number): string {
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
}

function metricColor(v: number): string {
  return v >= 0 ? 'var(--success)' : 'var(--danger)'
}
