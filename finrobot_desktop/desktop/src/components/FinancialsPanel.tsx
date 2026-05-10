import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAppStore } from '../stores/appStore'
import { fmt } from '../utils/formatters'
import { relativeTime } from '../utils/time'

type SourceType = 'api' | 'calc' | 'llm'

function Row({ label, value, highlight, source, sourceLabel }: {
  label: string; value: string; highlight?: boolean;
  source?: SourceType; sourceLabel?: string
}) {
  const tooltips: Record<SourceType, string> = {
    api: 'Live market data from provider',
    calc: 'Computed by FinAgent — deterministic',
    llm: 'AI-generated estimate',
  }
  return (
    <tr>
      <td className="fin-label">{label}</td>
      <td className={`fin-value${highlight ? ' highlight' : ''}`}>
        {value}
        {source && (
          <span
            className={`source-badge source-${source}`}
            data-tooltip={tooltips[source]}
          >
            {sourceLabel ?? source.toUpperCase()}
          </span>
        )}
      </td>
    </tr>
  )
}

export default function FinancialsPanel() {
  const ticker = useAppStore((s) => s.ticker)
  const dataFetchedAt = useAppStore((s) => s.dataFetchedAt)

  // Refresh relative time display every 30s
  const [, setTimeTick] = useState(0)
  useEffect(() => {
    if (!dataFetchedAt) return
    const id = setInterval(() => setTimeTick((t) => t + 1), 30_000)
    return () => clearInterval(id)
  }, [dataFetchedAt])

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
        </div>
        <div className="card-body">
          <table className="fin-table">
            <tbody>
              {['Revenue', 'EBITDA', 'Net Income', 'Market Cap', 'Enterprise Value'].map((label) => (
                <tr key={label}>
                  <td className="fin-label">{label}</td>
                  <td className="fin-value">
                    <div className="skeleton" style={{ width: 64, height: 14, display: 'inline-block' }} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  const { income, balance, market, valuation, data_source } = data
  const srcLabel = (data_source ?? 'API').toUpperCase()

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">Fundamentals</span>
        <span className="card-header-right">
          {dataFetchedAt && (
            <span
              className="data-freshness"
              title={new Date(dataFetchedAt).toLocaleString()}
            >
              {relativeTime(dataFetchedAt)}
            </span>
          )}
          {data_source && <span className="card-badge">{data_source}</span>}
        </span>
      </div>
      <div className="card-body">
        <table className="fin-table">
          <tbody>
            <Row label="Revenue" value={fmt(income?.revenue, 'usd')} source="api" sourceLabel={srcLabel} />
            <Row label="EBITDA" value={fmt(income?.ebitda, 'usd')} source="api" sourceLabel={srcLabel} />
            <Row label="Net Income" value={fmt(income?.net_income, 'usd')} source="api" sourceLabel={srcLabel} />
            <Row label="Gross Margin" value={fmt(income?.gross_margin, 'pct')} source="api" sourceLabel={srcLabel} />
            <Row label="Operating Margin" value={fmt(income?.operating_margin, 'pct')} source="api" sourceLabel={srcLabel} />
            <Row label="Market Cap" value={fmt(market?.market_cap, 'usd')} highlight source="api" sourceLabel={srcLabel} />
            <Row
              label="Current Price"
              value={market?.current_price != null ? `$${market.current_price.toFixed(2)}` : '\u2014'}
              source="api" sourceLabel={srcLabel}
            />
            <Row label="P/E Ratio" value={fmt(market?.pe_ratio, 'mult')} source="api" sourceLabel={srcLabel} />
            <Row label="Total Debt" value={fmt(balance?.total_debt, 'usd')} source="api" sourceLabel={srcLabel} />
            <Row label="Total Cash" value={fmt(balance?.total_cash, 'usd')} source="api" sourceLabel={srcLabel} />
            <Row label="Enterprise Value" value={fmt(valuation?.enterprise_value, 'usd')} highlight source="calc" />
            <Row label="EV/EBITDA" value={fmt(valuation?.ev_ebitda, 'mult')} source="calc" />
          </tbody>
        </table>
      </div>
    </div>
  )
}
