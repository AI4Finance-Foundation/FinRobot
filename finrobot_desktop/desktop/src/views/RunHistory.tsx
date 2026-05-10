import { useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAppStore } from '../stores/appStore'
import { BASE_URL } from '../api/client'
import type { DCFResult, DCFInputs, ResearchResult, SensitivityResult, EarningsResult } from '../stores/appStore'
import { useDcfSensitivity } from '../hooks/useCompute'

const STATUS_STYLES: Record<string, { color: string; label: string }> = {
  completed: { color: 'var(--positive)', label: 'Completed' },
  failed:    { color: 'var(--negative)', label: 'Failed' },
  running:   { color: 'var(--gold)',     label: 'Running' },
  created:   { color: 'var(--text-muted)', label: 'Created' },
}

const PIPELINE_LABELS: Record<string, string> = {
  equity_research: 'Equity Research',
  dcf: 'DCF',
  comps: 'Comps',
  earnings: 'Earnings',
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay}d ago`
  return d.toLocaleDateString()
}

interface Props {
  onBack: () => void
}

function buildSensitivityRanges(wacc: number, tg: number) {
  return {
    wacc_range: Array.from({ length: 7 }, (_, i) => Math.max(0, wacc - 0.03 + i * 0.01)),
    tg_range: Array.from({ length: 7 }, (_, i) => Math.max(0, tg - 0.015 + i * 0.005)),
  }
}

export default function RunHistory({ onBack }: Props) {
  const {
    setTicker,
    setPhase,
    setPipelineType,
    setView,
    setDcfInputs,
    setOriginalDcfInputs,
    setDcfResult,
    setSensitivityData,
    setResearchResult,
    setEarningsResult,
    setCurrentPrice,
    setWarnings,
  } = useAppStore()
  const sensitivityMut = useDcfSensitivity()

  const { data, isLoading } = useQuery({
    queryKey: ['runs'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/runs')
      if (error) throw new Error('Failed to load runs')
      return data
    },
    refetchInterval: 5000,
  })

  const handleLoadRun = useCallback(async (runId: string, runTicker: string, runPipelineType: string) => {
    // Fetch full run detail
    const resp = await fetch(`${BASE_URL}/api/runs/${runId}`)
    if (!resp.ok) return
    const detail = await resp.json()

    setTicker(runTicker)
    setPipelineType(runPipelineType as 'equity_research' | 'dcf' | 'comps' | 'earnings')
    setWarnings(detail.warnings || [])

    const structured = detail.result?.structured
    if (!structured) {
      setPhase('data_ready')
      setView('workspace')
      return
    }

    if (runPipelineType === 'earnings') {
      const earnings: EarningsResult | undefined = structured.earnings_data
      if (earnings) setEarningsResult(earnings)
      setPhase('interactive')
      setView('workspace')
      return
    }

    if (runPipelineType === 'equity_research') {
      const thesis: ResearchResult | undefined = structured.thesis
      if (thesis) setResearchResult(thesis)

      const dcfCalc: DCFResult | undefined = structured.financial_modeling
      if (dcfCalc) {
        const inputs: DCFInputs = dcfCalc.inputs
        setDcfInputs({ ...inputs })
        setOriginalDcfInputs({ ...inputs })
        setDcfResult(dcfCalc)

        const { wacc_range, tg_range } = buildSensitivityRanges(dcfCalc.wacc, inputs.terminal_growth_rate)
        sensitivityMut.mutate(
          { inputs, wacc_range, tg_range },
          { onSuccess: (data: SensitivityResult) => setSensitivityData(data) }
        )
      }

      // Try to get current price from data_collection
      const fin = structured.data_collection
      if (fin?.market?.current_price != null) {
        setCurrentPrice(fin.market.current_price)
      }
    } else {
      const dcfCalc: DCFResult | undefined = structured.dcf_calc || Object.values(structured)[0]
      if (dcfCalc) {
        const inputs: DCFInputs = dcfCalc.inputs
        setDcfInputs({ ...inputs })
        setOriginalDcfInputs({ ...inputs })
        setDcfResult(dcfCalc)

        const { wacc_range, tg_range } = buildSensitivityRanges(dcfCalc.wacc, inputs.terminal_growth_rate)
        sensitivityMut.mutate(
          { inputs, wacc_range, tg_range },
          { onSuccess: (data: SensitivityResult) => setSensitivityData(data) }
        )
      }
    }

    setPhase('interactive')
    setView('workspace')
  }, [setTicker, setPipelineType, setPhase, setView, setDcfInputs, setOriginalDcfInputs, setDcfResult, setSensitivityData, setResearchResult, setEarningsResult, setCurrentPrice, setWarnings, sensitivityMut])

  const runs = data?.runs || []

  return (
    <div style={{
      maxWidth: '720px',
      margin: '0 auto',
      padding: 'var(--sp-8) var(--sp-6)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--sp-3)',
        marginBottom: 'var(--sp-6)',
      }}>
        <button className="btn" onClick={onBack} style={{ padding: '4px 10px' }}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M9 2L4 7l5 5" />
          </svg>
          Back
        </button>
        <h2 style={{
          fontSize: '1.1rem',
          fontWeight: 700,
          color: 'var(--text-primary)',
        }}>Run History</h2>
      </div>

      {/* Loading */}
      {isLoading && (
        <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', textAlign: 'center', padding: 'var(--sp-10)' }}>
          Loading...
        </div>
      )}

      {/* Empty state */}
      {!isLoading && runs.length === 0 && (
        <div className="card">
          <div className="card-body" style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: 200,
            color: 'var(--text-muted)',
            fontSize: '0.85rem',
            flexDirection: 'column',
            gap: 'var(--sp-3)',
          }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ opacity: 0.4 }}>
              <circle cx="12" cy="12" r="10" />
              <path d="M12 6v6l4 2" />
            </svg>
            No analysis runs yet
          </div>
        </div>
      )}

      {/* Run list */}
      {!isLoading && runs.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">Recent Runs</span>
            <span className="card-badge">{runs.length}</span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            <table className="fin-table">
              <tbody>
                {runs.map((run: any) => {
                  const st = STATUS_STYLES[run.status] || STATUS_STYLES.created
                  const isClickable = run.status === 'completed'
                  return (
                    <tr
                      key={run.run_id}
                      onClick={isClickable ? () => handleLoadRun(run.run_id, run.ticker, run.pipeline_type) : undefined}
                      style={{
                        cursor: isClickable ? 'pointer' : 'default',
                        transition: 'background 0.15s',
                      }}
                      onMouseEnter={(e) => { if (isClickable) (e.currentTarget as HTMLElement).style.background = 'var(--elevated)' }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = '' }}
                    >
                      <td style={{ padding: '10px 16px', width: '80px' }}>
                        <span style={{
                          fontFamily: 'var(--font-mono)',
                          fontWeight: 700,
                          fontSize: '0.88rem',
                          color: 'var(--gold)',
                          letterSpacing: '0.03em',
                        }}>
                          {run.ticker}
                        </span>
                      </td>
                      <td style={{ padding: '10px 0' }}>
                        <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                          {PIPELINE_LABELS[run.pipeline_type] || run.pipeline_type}
                        </span>
                      </td>
                      <td style={{ padding: '10px 0', textAlign: 'center' }}>
                        <span style={{
                          fontSize: '0.7rem',
                          fontWeight: 600,
                          color: st.color,
                          padding: '2px 8px',
                          borderRadius: 'var(--r-sm)',
                          background: run.status === 'completed' ? 'var(--positive-bg)'
                            : run.status === 'failed' ? 'var(--negative-bg)'
                            : run.status === 'running' ? 'var(--gold-dim)'
                            : 'transparent',
                        }}>
                          {st.label}
                        </span>
                      </td>
                      <td className="fin-value" style={{ padding: '10px 16px', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                        {run.duration_s != null && (
                          <span style={{ marginRight: 'var(--sp-3)' }}>{run.duration_s}s</span>
                        )}
                        {formatTime(run.created_at)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
