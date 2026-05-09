import type { DCFResult } from '../stores/appStore'

interface Props {
  dcfResult: DCFResult
  currentPrice: number | null
}

function fmtUsd(val: number): string {
  const abs = Math.abs(val)
  if (abs >= 1e12) return `$${(val / 1e12).toFixed(1)}T`
  if (abs >= 1e9) return `$${(val / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `$${(val / 1e6).toFixed(1)}M`
  return `$${val.toFixed(2)}`
}

export default function ValuationCard({ dcfResult, currentPrice }: Props) {
  const upside =
    currentPrice && currentPrice > 0
      ? ((dcfResult.implied_price - currentPrice) / currentPrice) * 100
      : null

  const isPositive = upside !== null && upside >= 0

  return (
    <div className="valuation-hero animate-in">
      <div className="valuation-label">DCF Implied Share Price</div>
      <div className="valuation-price">
        <span className="currency">$</span>
        {dcfResult.implied_price.toFixed(2)}
      </div>

      {upside !== null && (
        <div className={`valuation-upside ${isPositive ? 'positive' : 'negative'}`}>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
            {isPositive ? (
              <path d="M6 2v8M3 5l3-3 3 3" />
            ) : (
              <path d="M6 10V2M3 7l3 3 3-3" />
            )}
          </svg>
          {isPositive ? '+' : ''}{upside.toFixed(1)}% vs ${currentPrice!.toFixed(2)}
        </div>
      )}

      <div className="valuation-metrics">
        <Metric label="WACC" value={`${(dcfResult.wacc * 100).toFixed(2)}%`} />
        <Metric label="Terminal Value" value={fmtUsd(dcfResult.terminal_value)} />
        <Metric label="EV / EBITDA" value={
          dcfResult.enterprise_value && dcfResult.inputs?.ebitda_margin
            ? `${(dcfResult.enterprise_value / (dcfResult.inputs.revenue_base * dcfResult.inputs.ebitda_margin)).toFixed(1)}x`
            : '\u2014'
        } />
        <Metric label="PV of FCF" value={fmtUsd(dcfResult.pv_fcf_total)} />
        <Metric label="Enterprise Value" value={fmtUsd(dcfResult.enterprise_value)} />
        <Metric label="Equity Value" value={fmtUsd(dcfResult.equity_value)} />
      </div>

      {dcfResult.fcf_formula_warning && (
        <div style={{
          marginTop: 'var(--sp-4)',
          fontSize: '0.75rem',
          color: 'var(--warning)',
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--sp-2)',
        }}>
          <span>&#9888;</span> {dcfResult.fcf_formula_warning}
        </div>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  )
}
