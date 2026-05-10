import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAppStore } from '../stores/appStore'

function fmt(val: number | null | undefined, style: 'usd' | 'pct' | 'mult' | 'num'): string {
  if (val == null) return '\u2014' // em dash
  if (style === 'usd') {
    const abs = Math.abs(val)
    if (abs >= 1e12) return `$${(val / 1e12).toFixed(1)}T`
    if (abs >= 1e9) return `$${(val / 1e9).toFixed(1)}B`
    if (abs >= 1e6) return `$${(val / 1e6).toFixed(1)}M`
    return `$${val.toLocaleString()}`
  }
  if (style === 'pct') return `${(val * 100).toFixed(1)}%`
  if (style === 'mult') return `${val.toFixed(1)}x`
  return val.toLocaleString()
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <tr>
      <td className="fin-label">{label}</td>
      <td className={`fin-value${highlight ? ' highlight' : ''}`}>{value}</td>
    </tr>
  )
}

export default function FinancialsPanel() {
  const ticker = useAppStore((s) => s.ticker)

  const { data } = useQuery({
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

  if (!data) {
    return (
      <div className="card animate-in">
        <div className="card-header">
          <span className="card-title">Fundamentals</span>
          <span className="card-badge" style={{ opacity: 0.5 }}>Loading...</span>
        </div>
        <div className="card-body">
          <table className="fin-table">
            <tbody>
              {['Revenue', 'EBITDA', 'Net Income', 'Market Cap', 'Enterprise Value'].map((label) => (
                <tr key={label}>
                  <td className="fin-label">{label}</td>
                  <td className="fin-value" style={{ opacity: 0.3 }}>{'\u2014'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  const { income, balance, market, valuation, data_source } = data

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">Fundamentals</span>
        {data_source && <span className="card-badge">{data_source}</span>}
      </div>
      <div className="card-body">
        <table className="fin-table">
          <tbody>
            <Row label="Revenue" value={fmt(income?.revenue, 'usd')} />
            <Row label="EBITDA" value={fmt(income?.ebitda, 'usd')} />
            <Row label="Net Income" value={fmt(income?.net_income, 'usd')} />
            <Row label="Gross Margin" value={fmt(income?.gross_margin, 'pct')} />
            <Row label="Operating Margin" value={fmt(income?.operating_margin, 'pct')} />
            <Row label="Market Cap" value={fmt(market?.market_cap, 'usd')} highlight />
            <Row
              label="Current Price"
              value={market?.current_price != null ? `$${market.current_price.toFixed(2)}` : '\u2014'}
            />
            <Row label="P/E Ratio" value={fmt(market?.pe_ratio, 'mult')} />
            <Row label="Total Debt" value={fmt(balance?.total_debt, 'usd')} />
            <Row label="Total Cash" value={fmt(balance?.total_cash, 'usd')} />
            <Row label="Enterprise Value" value={fmt(valuation?.enterprise_value, 'usd')} highlight />
            <Row label="EV/EBITDA" value={fmt(valuation?.ev_ebitda, 'mult')} />
          </tbody>
        </table>
      </div>
    </div>
  )
}
