// v5 §6.7 数据快照. Four cards: 市值 / 当前 PE / 7d mini chart / 下次财报.
// All come from already-cached hooks; no new endpoints.

import { useTickerPrice, useTickerFinancials } from '../../hooks/useTickerData'

interface DataSnapshotProps {
  ticker: string
}

export function DataSnapshot({ ticker }: DataSnapshotProps): React.ReactElement {
  const { data: price } = useTickerPrice(ticker)
  const { data: financials } = useTickerFinancials(ticker)

  const marketCap = (financials as { market_cap?: number } | undefined)?.market_cap ?? null
  const peRatio = (financials as { pe_ratio?: number } | undefined)?.pe_ratio ?? null
  const current = price?.current_price ?? null
  const changePct = price?.change_pct ?? null

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
        value="待接 §6.13"
        sub="财报日历待 PR14 接入"
        subColor="var(--text-faint)"
      />
    </section>
  )
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
        background: 'var(--bg-card, #fff)',
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
