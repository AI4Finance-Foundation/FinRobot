import { useCallback } from 'react'
import type { ICMemoResult } from '../stores/appStore'
import { useAppStore } from '../stores/appStore'
import { BASE_URL } from '../api/client'
import { fmtPct } from '../utils/formatters'

interface Props {
  result: ICMemoResult
}

const VERDICT_STYLES: Record<string, { color: string; bg: string }> = {
  INVEST: { color: 'var(--positive)', bg: 'var(--positive-bg)' },
  PASS:   { color: 'var(--negative)', bg: 'var(--negative-bg)' },
  HOLD:   { color: 'var(--accent)',     bg: 'var(--accent-dim)' },
}

function getVerdictStyle(verdict: string) {
  const key = verdict.toUpperCase().trim()
  return VERDICT_STYLES[key] || VERDICT_STYLES.HOLD
}

export default function ICMemoSummary({ result }: Props) {
  const ticker = useAppStore((s) => s.ticker)

  const handleExportPdf = useCallback(async () => {
    const resp = await fetch(`${BASE_URL}/api/report/pdf?ticker=${ticker}`)
    if (!resp.ok) return
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${ticker}_ic_memo.pdf`
    a.click()
    URL.revokeObjectURL(url)
  }, [ticker])

  const verdictStyle = getVerdictStyle(result.recommendation.verdict)

  return (
    <>
      {/* Hero — Verdict + IRR */}
      <div className="valuation-hero animate-in">
        <div className="hero-header hero-header--lg">
          <div>
            <div className="valuation-label">Investment Committee Memo</div>
            <div className="hero-ticker">{ticker}</div>
          </div>
          <div className="text-right">
            <div className="valuation-label">IC Recommendation</div>
            <span
              className="status-badge status-badge--lg"
              style={{ background: verdictStyle.bg, color: verdictStyle.color }}
            >
              {result.recommendation.verdict}
            </span>
          </div>
        </div>

        {/* IRR big number (if available) */}
        {result.recommendation.irr != null && (
          <div className="metrics-row">
            <div className="metric-stack">
              <div className="big-number" style={{
                color: result.recommendation.irr >= 0.15 ? 'var(--positive)' : 'var(--negative)',
              }}>
                {fmtPct(result.recommendation.irr)}
              </div>
              <div className="metric-sub">LBO IRR</div>
            </div>
            <div className="flex-1" />
            <span
              className="status-badge"
              style={{
                color: result.recommendation.irr >= 0.15 ? 'var(--positive)' : 'var(--negative)',
                background: result.recommendation.irr >= 0.15 ? 'var(--positive-bg)' : 'var(--negative-bg)',
              }}
            >
              {result.recommendation.irr >= 0.25 ? 'STRONG' :
               result.recommendation.irr >= 0.20 ? 'ATTRACTIVE' :
               result.recommendation.irr >= 0.15 ? 'MEETS HURDLE' : 'BELOW HURDLE'}
            </span>
          </div>
        )}
      </div>

      {/* Situation Overview */}
      {result.situation_overview && (
        <div className="card animate-in">
          <div className="card-header">
            <span className="card-title">Situation Overview</span>
          </div>
          <div className="card-body">
            <p className="body-text">{result.situation_overview}</p>
          </div>
        </div>
      )}

      {/* Financial Summary */}
      {result.financial_summary && (
        <div className="card animate-in">
          <div className="card-header">
            <span className="card-title">Financial Analysis</span>
            <span className="source-badge source-code" data-tooltip="Deterministic DCF + LBO">
              CODE
            </span>
          </div>
          <div className="card-body">
            <p className="body-text">{result.financial_summary}</p>
          </div>
        </div>
      )}

      {/* Investment Thesis */}
      {result.investment_thesis && (
        <div className="card animate-in">
          <div className="card-header">
            <span className="card-title">Investment Thesis</span>
          </div>
          <div className="card-body">
            <p className="body-text">{result.investment_thesis}</p>
          </div>
        </div>
      )}

      {/* Risk Factors */}
      {result.risk_factors && (
        <div className="card animate-in">
          <div className="card-header">
            <span className="card-title">Risk Factors</span>
          </div>
          <div className="card-body">
            <p className="body-text">{result.risk_factors}</p>
          </div>
        </div>
      )}

      {/* Recommendation (highlighted with accent border) */}
      {result.recommendation.rationale && (
        <div className="card animate-in" style={{ borderColor: 'var(--accent)', borderWidth: '1px', borderStyle: 'solid' }}>
          <div className="card-header">
            <span className="card-title" style={{ color: 'var(--accent)' }}>Recommendation</span>
            <span
              className="status-badge"
              style={{ background: verdictStyle.bg, color: verdictStyle.color }}
            >
              {result.recommendation.verdict}
            </span>
          </div>
          <div className="card-body">
            <p className="body-text">{result.recommendation.rationale}</p>
          </div>
        </div>
      )}

      {/* Export + New Analysis */}
      <div className="export-bar animate-in">
        <button className="btn" onClick={handleExportPdf}>
          <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 10v2h10v-2M7 2v7m-3-3l3 3 3-3" />
          </svg>
          Export PDF
        </button>
        <div className="flex-1" />
        <button className="btn btn-primary" onClick={() => useAppStore.getState().reset()}>
          <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M7 1v12M1 7h12" />
          </svg>
          New Analysis
        </button>
      </div>
    </>
  )
}
