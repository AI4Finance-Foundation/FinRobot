// v5 §6.7 数据快照. Four cards: 市值 / 当前 PE / 7d mini chart / 下次财报.
// All come from already-cached hooks; no new endpoints.

import { useTickerPrice, useTickerFinancials } from '../../hooks/useTickerData'

interface DataSnapshotProps {
  ticker: string
}

export function DataSnapshot({ ticker }: DataSnapshotProps): React.ReactElement {
  const { data: price } = useTickerPrice(ticker)
  const { data: financials } = useTickerFinancials(ticker)

  // Backend nests these under `market` — see FinancialsData. Falling back to
  // the live price feed when the financials snapshot is missing (e.g. data
  // layer error or fresh ticker not yet cached).
  const marketCap = financials?.market?.market_cap ?? price?.market_cap ?? null
  const peRatio = financials?.market?.pe_ratio ?? null
  const current = financials?.market?.current_price ?? price?.current_price ?? null
  const changePct = price?.change_pct ?? null
  // Next-earnings: yfinance often carries it on the price feed (info dict);
  // the FinancialData fallback is honest if yfinance hasn't dated the next call.
  const nextEarnings: string | null = price?.next_earnings_date ?? null

  return (
    <section
      id="sec-data"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 12,
        margin: '12px 0',
      }}
    >
      <Card label="市值" value={formatBigNumber(marketCap, '$')} />
      <Card label="当前 PE" value={peRatio !== null ? peRatio.toFixed(1) : 'N/A'} />
      <Card
        label="当前价"
        value={current !== null ? `$${current.toFixed(2)}` : 'N/A'}
        sub={
          changePct !== null
            ? `${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}% 今日`
            : null
        }
        subColor={changePct !== null && changePct >= 0 ? '#10B981' : '#EF4444'}
      />
      <Card
        label="下次财报"
        value={nextEarnings ? formatEarningsDate(nextEarnings) : '待披露'}
        sub={nextEarnings ? earningsCountdown(nextEarnings) : 'yfinance 暂未给出日期'}
        subColor="var(--text-faint)"
      />
    </section>
  )
}

function formatEarningsDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  } catch {
    return '待披露'
  }
}

function earningsCountdown(iso: string): string {
  try {
    const days = Math.round((new Date(iso).getTime() - Date.now()) / (24 * 3600 * 1000))
    if (days < 0) return `${Math.abs(days)} 天前`
    if (days === 0) return '今天'
    return `还有 ${days} 天`
  } catch {
    return ''
  }
}

interface CardProps {
  label: string
  value: string
  sub?: string | null
  subColor?: string
}

function Card({ label, value, sub, subColor }: CardProps): React.ReactElement {
  return (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: 16,
        background: 'var(--bg-card)',
      }}
    >
      <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>{label}</div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 700,
          marginTop: 4,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, marginTop: 4, color: subColor ?? 'var(--text-faint)' }}>
          {sub}
        </div>
      )}
    </div>
  )
}

function formatBigNumber(v: number | null, prefix = ''): string {
  if (v === null) return 'N/A'
  if (v >= 1e12) return `${prefix}${(v / 1e12).toFixed(2)}T`
  if (v >= 1e9) return `${prefix}${(v / 1e9).toFixed(1)}B`
  if (v >= 1e6) return `${prefix}${(v / 1e6).toFixed(1)}M`
  return `${prefix}${v.toLocaleString()}`
}
