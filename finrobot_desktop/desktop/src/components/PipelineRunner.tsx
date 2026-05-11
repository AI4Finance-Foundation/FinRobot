import { useCallback, useEffect, useRef, useState } from 'react'
import { useRunStream } from '../hooks/useRunStream'
import { useAppStore } from '../stores/appStore'
import { useToastStore } from '../stores/toastStore'
import { useDcfSensitivity } from '../hooks/useCompute'
import { BASE_URL } from '../api/client'
import type { DCFResult, DCFInputs, SensitivityResult, ResearchResult, CompsResult, EarningsResult, LBOResult, ICMemoResult, ActiveTab } from '../stores/appStore'

const PIPELINE_TAB_MAP: Record<string, { tab: ActiveTab; label: string }> = {
  research: { tab: 'overview', label: 'Overview' },
  dcf: { tab: 'valuation', label: 'Valuation' },
  comps: { tab: 'peers', label: 'Peers' },
  earnings: { tab: 'valuation', label: 'Valuation' },
  lbo: { tab: 'valuation', label: 'Valuation' },
  'ic-memo': { tab: 'valuation', label: 'Valuation' },
}

function buildSensitivityRanges(wacc: number, tg: number) {
  const waccRange = Array.from({ length: 7 }, (_, i) => Math.max(0, wacc - 0.03 + i * 0.01))
  const tgRange = Array.from({ length: 7 }, (_, i) => Math.max(0, tg - 0.015 + i * 0.005))
  return { wacc_range: waccRange, tg_range: tgRange }
}

const STATUS_MAP: Record<string, string> = {
  completed: 'done',
  running: 'active',
  pending: 'pending',
  retrying: 'retrying',
}

const PIPELINE_LABELS: Record<string, string> = {
  research: 'Equity Research',
  dcf: 'DCF Analysis',
  comps: 'Comps Analysis',
  earnings: 'Earnings Analysis',
  lbo: 'LBO Analysis',
  'ic-memo': 'IC Memo',
}

export default function PipelineRunner() {
  const { steps, status, error, progress, startRun } = useRunStream()
  const {
    ticker,
    phase,
    pipelineType,
    setPhase,
    setDcfInputs,
    setOriginalDcfInputs,
    setDcfResult,
    setSensitivityData,
    setResearchResult,
    setCompsResult,
    setEarningsResult,
    setLboResult,
    setIcMemoResult,
  } = useAppStore()
  const sensitivityMut = useDcfSensitivity()
  const [runId, setRunId] = useState<string | null>(null)
  const fetchingRef = useRef(false)
  // Track which pipeline type was used for the current run
  const runPipelineTypeRef = useRef(pipelineType)

  const addToast = useToastStore((s) => s.addToast)

  const handleRun = useCallback(async () => {
    if (!ticker) return
    runPipelineTypeRef.current = pipelineType
    setPhase('running_pipeline')
    try {
      const id = await startRun(pipelineType, ticker)
      setRunId(id)
    } catch {
      setPhase('data_ready')
      addToast({ type: 'error', title: 'Pipeline failed to start', description: `Could not run ${PIPELINE_LABELS[pipelineType]}` })
    }
  }, [ticker, pipelineType, startRun, setPhase, addToast])

  useEffect(() => {
    if (status !== 'completed' || phase !== 'running_pipeline' || !runId) return
    if (fetchingRef.current) return
    fetchingRef.current = true

    setPhase('pipeline_done')

    const fetchResult = async () => {
      try {
        const resp = await fetch(`${BASE_URL}/api/runs/${runId}`)
        if (!resp.ok) return
        const detail = await resp.json()
        const structured = detail.result?.structured
        if (!structured) return

        if (runPipelineTypeRef.current === 'research') {
          // Extract thesis result
          const thesis: ResearchResult | undefined = structured.thesis
          if (thesis) {
            setResearchResult(thesis)
          }

          // Also extract DCF if present (financial_modeling step)
          const dcfCalc: DCFResult | undefined = structured.financial_modeling
          if (dcfCalc) {
            const inputs: DCFInputs = dcfCalc.inputs
            setDcfInputs({ ...inputs })
            setOriginalDcfInputs({ ...inputs })
            setDcfResult(dcfCalc)

            const { wacc_range, tg_range } = buildSensitivityRanges(
              dcfCalc.wacc,
              inputs.terminal_growth_rate
            )
            sensitivityMut.mutate(
              { inputs, wacc_range, tg_range },
              { onSuccess: (data: SensitivityResult) => setSensitivityData(data) }
            )
          }
        } else if (runPipelineTypeRef.current === 'comps') {
          // Comps pipeline — look for statistical_bench (PeerComps output)
          const comps: CompsResult | undefined =
            structured.statistical_bench || structured.peer_comps
          if (comps) {
            setCompsResult(comps)
          }
        } else if (runPipelineTypeRef.current === 'earnings') {
          // Earnings pipeline — look for earnings_data (EarningsResult)
          const earnings: EarningsResult | undefined = structured.earnings_data
          if (earnings) {
            setEarningsResult(earnings)
          }
        } else if (runPipelineTypeRef.current === 'lbo') {
          // LBO pipeline — look for lbo_calculation (LBOResult)
          const lbo: LBOResult | undefined = structured.lbo_calculation
          if (lbo) {
            setLboResult(lbo)
          }
        } else if (runPipelineTypeRef.current === 'ic-memo') {
          // IC Memo pipeline — assemble from step text outputs + structured financial_analysis
          const steps: Record<string, string> = detail.steps || {}
          const financialAnalysis = structured.financial_analysis
          const recommendationText = steps.recommendation || ''

          // Extract IRR from ICFinancials structured data
          let irr: number | null = null
          if (typeof financialAnalysis === 'object' && financialAnalysis) {
            const fa = financialAnalysis as Record<string, unknown>
            if (fa.lbo_result && typeof fa.lbo_result === 'object') {
              irr = (fa.lbo_result as Record<string, unknown>).irr as number | null
            }
          }

          // Determine verdict from recommendation text (code gate prefixes PASS)
          let verdict = 'INVEST'
          if (recommendationText.includes('[CODE GATE') || recommendationText.toUpperCase().includes('PASS')) {
            verdict = 'PASS'
          } else if (recommendationText.toUpperCase().includes('HOLD')) {
            verdict = 'HOLD'
          }

          const icMemo: ICMemoResult = {
            situation_overview: steps.situation_overview || '',
            financial_summary: steps.financial_analysis || '',
            investment_thesis: steps.investment_thesis || '',
            risk_factors: steps.risk_factors || '',
            recommendation: {
              verdict,
              irr,
              rationale: recommendationText,
            },
          }
          setIcMemoResult(icMemo)
        } else {
          // DCF-only pipeline
          const dcfCalc: DCFResult | undefined =
            structured.dcf_calc || Object.values(structured)[0]
          if (!dcfCalc) return

          const inputs: DCFInputs = dcfCalc.inputs
          setDcfInputs({ ...inputs })
          setOriginalDcfInputs({ ...inputs })
          setDcfResult(dcfCalc)

          const { wacc_range, tg_range } = buildSensitivityRanges(
            dcfCalc.wacc,
            inputs.terminal_growth_rate
          )
          sensitivityMut.mutate(
            { inputs, wacc_range, tg_range },
            { onSuccess: (data: SensitivityResult) => setSensitivityData(data) }
          )
        }

        setPhase('interactive')

        // Auto-switch to the relevant tab and show contextual toast
        const mapping = PIPELINE_TAB_MAP[runPipelineTypeRef.current]
        if (mapping) {
          useAppStore.getState().setActiveTab(mapping.tab)
          addToast({
            type: 'success',
            title: `${PIPELINE_LABELS[runPipelineTypeRef.current]} complete`,
            description: `${ticker} analysis ready — viewing ${mapping.label} tab`,
          })
        } else {
          addToast({
            type: 'success',
            title: `${PIPELINE_LABELS[runPipelineTypeRef.current]} complete`,
            description: `${ticker} analysis ready`,
          })
        }
      } finally {
        fetchingRef.current = false
      }
    }

    fetchResult()
  }, [status, phase, runId, ticker, setPhase, setDcfInputs, setOriginalDcfInputs, setDcfResult, setSensitivityData, setResearchResult, setCompsResult, setEarningsResult, setLboResult, setIcMemoResult, sensitivityMut, addToast])

  const canRun = (phase === 'data_ready' || phase === 'pipeline_done' || phase === 'interactive') && !!ticker
  const isRunning = phase === 'running_pipeline' || phase === 'pipeline_done'
  const label = PIPELINE_LABELS[pipelineType] || pipelineType

  const doneCount = steps.filter(s => s.status === 'completed').length
  const totalCount = steps.length
  const allDone = totalCount > 0 && doneCount === totalCount
  const countCls = allDone ? 'done' : isRunning ? 'running' : ''

  // Fire toast on stream error
  const prevStatusRef = useRef(status)
  useEffect(() => {
    if (prevStatusRef.current !== 'failed' && status === 'failed' && error) {
      addToast({ type: 'error', title: 'Pipeline error', description: error })
    }
    prevStatusRef.current = status
  }, [status, error, addToast])

  const cardCls = `card animate-in${allDone ? ' pipeline-all-done' : ''}`

  return (
    <div className={cardCls}>
      <div className="card-header">
        <span className="card-title">{label} Pipeline</span>
        {totalCount > 0 && (
          <span className={`pipeline-count ${countCls}`}>
            {doneCount}/{totalCount}
          </span>
        )}
      </div>
      <div className="card-body">
        {/* Run button */}
        {canRun && (
          <button className="btn-run" onClick={handleRun}>
            Run {label}
          </button>
        )}
        {status === 'failed' && (
          <button className="btn-run" onClick={handleRun}>
            Retry
          </button>
        )}

        {/* Pipeline steps */}
        {steps.length > 0 && (
          <div className="pipeline-steps" style={{ marginTop: canRun || status === 'failed' ? 'var(--sp-4)' : 0 }}>
            {steps.map((step, i) => {
              const cls = STATUS_MAP[step.status] || 'pending'
              return (
                <div key={i} className={`step ${cls}`}>
                  <div className="step-indicator">
                    {step.status === 'completed' && (
                      <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                        <path d="M8.5 3L4.25 7.25 2 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    )}
                    {step.status === 'running' && (
                      <svg width="8" height="8" viewBox="0 0 8 8" fill="currentColor"><circle cx="4" cy="4" r="3" /></svg>
                    )}
                    {step.status === 'pending' && (
                      <svg width="8" height="8" viewBox="0 0 8 8" fill="currentColor"><circle cx="4" cy="4" r="2" opacity="0.4" /></svg>
                    )}
                    {step.status === 'retrying' && (
                      <span style={{ fontSize: '0.6rem' }}>{'\u21BB'}</span>
                    )}
                  </div>
                  <span className="step-name">{step.name}</span>
                  {step.duration_s != null && (
                    <span className="step-time">{step.duration_s}s</span>
                  )}
                </div>
              )
            })}
            {isRunning && steps.some(s => s.status === 'running') && (
              <div className="step-progress-bar">
                <div
                  className={progress > 0 ? '' : 'step-progress-fill'}
                  style={progress > 0
                    ? {
                        height: '100%',
                        background: 'var(--gold)',
                        borderRadius: '1px',
                        width: `${Math.min(progress * 100, 100)}%`,
                        transition: 'width 0.3s ease',
                      }
                    : undefined
                  }
                />
              </div>
            )}
          </div>
        )}

        {error && <div className="error-msg" style={{ marginTop: 'var(--sp-3)' }}>{error}</div>}
      </div>
    </div>
  )
}
