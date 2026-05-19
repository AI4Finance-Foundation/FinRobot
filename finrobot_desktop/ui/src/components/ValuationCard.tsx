import { useState } from 'react'
import { useCountUp } from '../hooks/useCountUp'
import type { DCFResult } from '../stores/appStore'
import { fmtUsd } from '../utils/formatters'
import { TermTip } from './TermTip'

interface Props {
  dcfResult: DCFResult
  currentPrice: number | null
}

function verdict(upside: number | null): { tag: string; tone: 'positive' | 'negative' | 'neutral' } {
  if (upside === null) return { tag: '估值已计算', tone: 'neutral' }
  if (upside >= 15) return { tag: '明显低估', tone: 'positive' }
  if (upside >= 3) return { tag: '估值合理偏低', tone: 'positive' }
  if (upside > -3) return { tag: '估值合理', tone: 'neutral' }
  if (upside > -15) return { tag: '估值合理偏高', tone: 'negative' }
  return { tag: '明显高估', tone: 'negative' }
}

export default function ValuationCard({ dcfResult, currentPrice }: Props) {
  const [showDetails, setShowDetails] = useState(false)
  const animatedPrice = useCountUp(dcfResult.implied_price)

  const upside =
    currentPrice && currentPrice > 0
      ? ((dcfResult.implied_price - currentPrice) / currentPrice) * 100
      : null
  const animatedUpside = useCountUp(upside ?? 0, 700, 1)

  const isPositive = upside !== null && upside >= 0
  const { tag, tone } = verdict(upside)

  return (
    <div className="valuation-hero animate-in">
      <div className="valuation-label">
        DCF 模型测算合理价
        <span
          className="source-badge source-calc"
          data-tooltip="由 FinAgent 代码确定性算出（不是 LLM 猜的）"
          style={{ marginLeft: 8 }}
        >
          CALC
        </span>
      </div>

      <div className="valuation-price">
        <span className="currency">$</span>
        {animatedPrice.toFixed(2)}
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
          比现价{isPositive ? '高' : '低'} {Math.abs(animatedUpside).toFixed(1)}% · 现价 ${currentPrice!.toFixed(2)}
        </div>
      )}

      <div
        style={{
          marginTop: 'var(--sp-3)',
          padding: '6px 12px',
          display: 'inline-block',
          borderRadius: 'var(--r-md)',
          fontSize: '0.875rem',
          fontWeight: 600,
          background:
            tone === 'positive'
              ? 'rgba(34, 197, 94, 0.12)'
              : tone === 'negative'
                ? 'rgba(239, 68, 68, 0.12)'
                : 'var(--bg-2)',
          color:
            tone === 'positive'
              ? 'var(--success)'
              : tone === 'negative'
                ? 'var(--danger)'
                : 'var(--text-secondary)',
        }}
      >
        {tag}
      </div>

      <button
        type="button"
        onClick={() => setShowDetails((s) => !s)}
        style={{
          marginTop: 'var(--sp-4)',
          background: 'transparent',
          border: 'none',
          color: 'var(--text-muted)',
          fontSize: '0.8rem',
          cursor: 'pointer',
          padding: 0,
          textDecoration: 'underline',
        }}
      >
        {showDetails ? '收起专家详情 ▲' : '展开专家详情（WACC / 终值 / EV…） ▼'}
      </button>

      {showDetails && (
        <div className="valuation-metrics" style={{ marginTop: 'var(--sp-3)' }}>
          <Metric label={<TermTip term="WACC">折现率 WACC</TermTip>} value={`${(dcfResult.wacc * 100).toFixed(2)}%`} />
          <Metric label={<TermTip term="Terminal Value">终值 Terminal Value</TermTip>} value={fmtUsd(dcfResult.terminal_value)} />
          <Metric
            label={<TermTip term="EV/EBITDA">EV / EBITDA</TermTip>}
            value={
              dcfResult.enterprise_value && dcfResult.inputs?.ebitda_margin
                ? `${(dcfResult.enterprise_value / (dcfResult.inputs.revenue_base * dcfResult.inputs.ebitda_margin)).toFixed(1)}x`
                : '—'
            }
          />
          <Metric label={<TermTip term="PV of FCF">现金流现值 PV of FCF</TermTip>} value={fmtUsd(dcfResult.pv_fcf_total)} />
          <Metric label={<TermTip term="Enterprise Value">企业价值 EV</TermTip>} value={fmtUsd(dcfResult.enterprise_value)} />
          <Metric label={<TermTip term="Equity Value">股权价值</TermTip>} value={fmtUsd(dcfResult.equity_value)} />
        </div>
      )}

    </div>
  )
}

function Metric({ label, value }: { label: React.ReactNode; value: string }) {
  return (
    <div>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  )
}
