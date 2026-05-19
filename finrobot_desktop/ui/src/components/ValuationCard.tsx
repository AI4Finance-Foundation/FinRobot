import { useState } from 'react'
import { useCountUp } from '../hooks/useCountUp'
import { useAppStore } from '../stores/appStore'
import type { DCFResult, DcfReverseResult } from '../stores/appStore'
import { fmtUsd } from '../utils/formatters'
import { TermTip } from './TermTip'

interface Props {
  dcfResult: DCFResult
  currentPrice: number | null
}

// Map the JSON field name to a 散户-friendly Chinese label used in the
// provenance panel. Anything not in this table falls back to the raw key,
// which is acceptable since seed_dcf_inputs only writes known keys.
const FIELD_LABELS: Record<string, string> = {
  revenue_base: '基准营收',
  revenue_growth_rates: '营收增速 (5y)',
  ebitda_margin: 'EBITDA 利润率',
  capex_pct_revenue: '资本开支 / 营收',
  da_pct_revenue: '折旧摊销 / 营收',
  nwc_pct_revenue: '营运资本变动 / 营收',
  tax_rate: '有效税率',
  beta: 'Beta',
  risk_free_rate: '无风险利率',
  equity_risk_premium: '股权风险溢价',
  cost_of_debt: '债务成本',
  debt_ratio: '负债 / 资本',
  terminal_growth_rate: '永续增速',
  shares_outstanding: '流通股本',
  net_debt: '净债务',
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
  const reverseGrowth = useAppStore((s) => s.dcfReverseGrowth)
  const reverseWacc = useAppStore((s) => s.dcfReverseWacc)
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

      {showDetails && <AssumptionProvenance inputs={dcfResult.inputs} />}

      <MarketImpliedPanel
        reverseGrowth={reverseGrowth}
        reverseWacc={reverseWacc}
        currentPrice={currentPrice}
      />
    </div>
  )
}

function AssumptionProvenance({ inputs }: { inputs: DCFResult['inputs'] }) {
  const prov = inputs.assumption_provenance ?? {}
  const entries = Object.entries(prov)
  if (entries.length === 0) return null

  return (
    <div
      style={{
        marginTop: 'var(--sp-4)',
        padding: '12px 14px',
        background: 'var(--bg-2)',
        borderRadius: 'var(--r-md)',
        border: '1px solid var(--border-subtle)',
      }}
    >
      <div
        style={{
          fontSize: '0.78rem',
          fontWeight: 600,
          color: 'var(--text-secondary)',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          marginBottom: 8,
        }}
      >
        每条假设的数据来源
      </div>
      <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'grid', gap: 6 }}>
        {entries.map(([key, msg]) => (
          <li
            key={key}
            style={{
              fontSize: '0.82rem',
              color: 'var(--text-primary)',
              lineHeight: 1.5,
              display: 'grid',
              gridTemplateColumns: '120px 1fr',
              gap: 12,
            }}
          >
            <span style={{ color: 'var(--text-muted)' }}>{FIELD_LABELS[key] ?? key}</span>
            <span>{msg}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

interface MarketImpliedProps {
  reverseGrowth: DcfReverseResult | null
  reverseWacc: DcfReverseResult | null
  currentPrice: number | null
}

function MarketImpliedPanel({ reverseGrowth, reverseWacc, currentPrice }: MarketImpliedProps) {
  // Only render when we actually solved at least one reverse DCF.
  const g = reverseGrowth?.implied_growth
  const w = reverseWacc?.implied_wacc
  if ((g == null || !Number.isFinite(g)) && (w == null || !Number.isFinite(w))) {
    return null
  }
  return (
    <div
      style={{
        marginTop: 'var(--sp-4)',
        padding: '12px 14px',
        background: 'rgba(99, 102, 241, 0.08)',
        borderRadius: 'var(--r-md)',
        border: '1px solid rgba(99, 102, 241, 0.25)',
      }}
    >
      <div
        style={{
          fontSize: '0.78rem',
          fontWeight: 600,
          color: 'var(--text-secondary)',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          marginBottom: 6,
        }}
      >
        市场在 price-in 什么
      </div>
      <div style={{ fontSize: '0.85rem', color: 'var(--text-primary)', lineHeight: 1.55 }}>
        要让 DCF 算出现价{currentPrice != null ? ` $${currentPrice.toFixed(2)} ` : ''}，市场需要假设：
      </div>
      <ul style={{ marginTop: 6, padding: 0, listStyle: 'none', display: 'grid', gap: 4 }}>
        {g != null && Number.isFinite(g) && (
          <li style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>
            · 营收年均增长 <strong>{(g * 100).toFixed(1)}%</strong>（每年持续 5 年）
          </li>
        )}
        {w != null && Number.isFinite(w) && (
          <li style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>
            · 或折现率 WACC <strong>{(w * 100).toFixed(2)}%</strong>
          </li>
        )}
      </ul>
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
