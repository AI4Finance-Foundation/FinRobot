// PipelineProgressPanel — live 8-step equity_research progress.
// Reads the RunState from runStreamStore (fed by backend SSE events) and
// renders a progress bar + one row per step. Step names/order MUST mirror
// equity_research.py create_*_pipeline().steps; STEP_LABELS below maps each
// backend step name to its Chinese label + one-line help.
//
// Header switches running / completed / failed so the panel isn't a stale
// "正在跑" forever. Colours are design tokens (涨绿跌红 only for status); the
// running step shows a real rotating spinner, not a static glyph.

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useRunStreamStore } from '../stores/runStreamStore'
import { useI18n, tSync } from '../i18n'

// Backend Pipeline.max_retries — mirrored here only to render "重试中 n/3".
const MAX_RETRIES = 3

// Backend step names → i18n key suffixes. Labels/help resolved via t() at render.
const STEP_KEYS: Record<string, string> = {
  data_collection: 'dataCollection',
  catalyst_analysis: 'catalystAnalysis',
  peer_analysis: 'peerAnalysis',
  financial_modeling: 'financialModeling',
  ownership_governance_analysis: 'ownershipGovernance',
  technical_analysis: 'technicalAnalysis',
  thesis: 'thesis',
  report: 'report',
}

// Steps that only appear in non-research pipelines (dcf/lbo/ddm/comps/earnings/
// ic-memo) have no i18n entry yet. Rather than leak raw snake_case
// (lbo_modeling), title-case the name so the panel reads cleanly. Acronyms stay
// upper-cased. SSE always sends the real step name, so this is purely cosmetic.
const STEP_ACRONYMS = new Set(['lbo', 'ddm', 'dcf', 'ic', 'ebitda', 'wacc'])
function prettyStepName(name: string): string {
  return name
    .split('_')
    .map((w) =>
      STEP_ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1),
    )
    .join(' ')
}

interface PipelineProgressPanelProps {
  ticker: string
}

export function PipelineProgressPanel({
  ticker,
}: PipelineProgressPanelProps): React.ReactElement | null {
  const run = useRunStreamStore((s) => s.runs[ticker])
  const dismiss = useRunStreamStore((s) => s.dismiss)
  const cancelRun = useRunStreamStore((s) => s.cancelRun)
  const navigate = useNavigate()
  const { t } = useI18n()

  // 1s heartbeat while running — re-renders so the elapsed counters tick. This
  // is the core "is it alive or hung?" signal: a long step (SEC fetches run
  // 60-90s) now shows a climbing clock instead of a static spinner. Hooks must
  // run unconditionally, so this sits above the early return.
  const isActive = run?.status === 'running'
  const [nowTick, setNowTick] = useState(() => Date.now())
  useEffect(() => {
    if (!isActive) return
    const id = window.setInterval(() => setNowTick(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [isActive])

  if (!run || run.dismissed) {
    return null
  }

  const runElapsed =
    run.status === 'running' ? Math.max(0, Math.round((nowTick - run.startedAt) / 1000)) : null

  const numStyle: React.CSSProperties = {
    fontSize: 11,
    color: 'var(--text-muted)',
    fontFamily: 'var(--font-mono)',
    fontVariantNumeric: 'tabular-nums',
  }
  const stepElapsed = (s: { startedAt?: number }): number | null =>
    typeof s.startedAt === 'number' ? Math.max(0, Math.round((nowTick - s.startedAt) / 1000)) : null

  const eta = estimateEta(run.steps)
  const completedCount = run.steps.filter((s) => s.status === 'completed').length
  const totalSteps = run.steps.length
  const totalDuration = run.steps.reduce((sum, s) => sum + (s.duration_s ?? 0), 0)
  const pct = totalSteps > 0 ? Math.round((completedCount / totalSteps) * 100) : 0

  const accent =
    run.status === 'completed'
      ? 'var(--success)'
      : run.status === 'failed'
        ? 'var(--danger)'
        : run.status === 'cancelled'
          ? 'var(--text-muted)'
          : 'var(--secondary)'
  const borderColor =
    run.status === 'completed'
      ? 'var(--success-glow-soft)'
      : run.status === 'failed'
        ? 'var(--danger-glow-soft)'
        : 'var(--border-soft)'

  return (
    <div
      data-testid="pipeline-progress-panel"
      style={{
        border: `1px solid ${borderColor}`,
        borderRadius: 'var(--radius-md)',
        padding: 18,
        background: 'var(--bg-card)',
        margin: '12px 0',
      }}
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          marginBottom: 12,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          <span
            className={run.status === 'running' ? 'cosmic-pulse-dot' : undefined}
            style={{
              width: 9,
              height: 9,
              borderRadius: '50%',
              display: 'inline-block',
              background: accent,
              flexShrink: 0,
            }}
          />
          <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)' }}>
            {run.status === 'completed'
              ? t('workspace.pipeline.statusDone', { name: labelForPipeline(run.pipelineType) })
              : run.status === 'failed'
                ? t('workspace.pipeline.statusFailed', { name: labelForPipeline(run.pipelineType) })
                : run.status === 'cancelled'
                  ? t('workspace.pipeline.statusCancelled', {
                      name: labelForPipeline(run.pipelineType),
                    })
                  : t('workspace.pipeline.statusGenerating', {
                      name: labelForPipeline(run.pipelineType),
                    })}
          </span>
          {run.status === 'running' && (
            <span
              style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
            >
              {t('workspace.pipeline.elapsed', { s: runElapsed ?? 0 })}
              {eta ? t('workspace.pipeline.eta', { s: eta }) : ''}
            </span>
          )}
          {run.status === 'completed' && totalDuration > 0 && (
            <span
              style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
            >
              {t('workspace.pipeline.totalDuration', { s: totalDuration.toFixed(1) })}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              fontSize: 11,
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {completedCount}/{totalSteps}
          </span>
          {run.status === 'completed' && run.artifactId && (
            <button
              type="button"
              data-testid="pipeline-open-report"
              // Open THIS run's artifact by id (from the run.completed event),
              // not the latest equity_research for the ticker — that opened the
              // wrong report on same-ticker re-runs or non-research pipelines.
              onClick={() => navigate(`/stocks/${ticker}/runs/${run.artifactId}`)}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                padding: '5px 11px',
                borderRadius: 6,
                background: 'linear-gradient(135deg, var(--secondary) 0%, var(--primary) 100%)',
                color: 'var(--text-on-primary)',
                border: 'none',
                cursor: 'pointer',
                letterSpacing: '0.04em',
              }}
            >
              {t('workspace.pipeline.openReport')}
            </button>
          )}
          {run.status === 'running' && (
            <button
              type="button"
              data-testid="pipeline-cancel"
              disabled={run.cancelling || !run.runId}
              onClick={() => {
                // Errors surface in the run card itself if the run later
                // fails; a failed cancel POST simply re-enables the button.
                void cancelRun(ticker).catch(() => {})
              }}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                padding: '5px 11px',
                borderRadius: 6,
                background: 'transparent',
                color: run.cancelling ? 'var(--text-dim)' : 'var(--danger)',
                border: `1px solid ${run.cancelling ? 'var(--border-soft)' : 'var(--danger-glow-soft)'}`,
                cursor: run.cancelling ? 'default' : 'pointer',
                letterSpacing: '0.04em',
              }}
            >
              {run.cancelling ? t('workspace.pipeline.cancelling') : t('workspace.pipeline.cancel')}
            </button>
          )}
          {(run.status === 'completed' ||
            run.status === 'failed' ||
            run.status === 'cancelled') && (
            <button
              type="button"
              data-testid="pipeline-dismiss"
              onClick={() => dismiss(ticker)}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                padding: '5px 10px',
                borderRadius: 6,
                background: 'transparent',
                color: 'var(--text-muted)',
                border: '1px solid var(--border-soft)',
                cursor: 'pointer',
              }}
              aria-label={t('workspace.pipeline.dismissAria')}
            >
              ✕
            </button>
          )}
        </div>
      </header>

      {/* Progress bar — the at-a-glance "how far" the text count alone couldn't give. */}
      <div
        style={{
          height: 4,
          borderRadius: 'var(--radius-pill)',
          background: 'var(--bg-elevated)',
          overflow: 'hidden',
          marginBottom: 14,
        }}
      >
        <div
          className="pipeline-bar-fill"
          style={{
            height: '100%',
            width: `${pct}%`,
            borderRadius: 'var(--radius-pill)',
            background:
              run.status === 'failed'
                ? 'var(--danger)'
                : 'linear-gradient(90deg, var(--secondary) 0%, var(--primary) 100%)',
          }}
        />
      </div>

      <ol style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 4 }}>
        {run.steps.map((step, idx) => {
          const keySuffix = STEP_KEYS[step.name]
          const meta = keySuffix
            ? {
                label: t(`workspace.pipeline.step.${keySuffix}.label`),
                help: t(`workspace.pipeline.step.${keySuffix}.help`),
              }
            : { label: prettyStepName(step.name), help: '' }
          const isRunning = step.status === 'running' || step.status === 'retrying'
          return (
            <li
              key={step.name}
              data-testid={`pipeline-step-${step.name}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '7px 9px',
                borderRadius: 6,
                background: isRunning ? 'var(--secondary-soft)' : 'transparent',
                borderLeft: `2px solid ${isRunning ? 'var(--secondary)' : 'transparent'}`,
                fontSize: 12.5,
                transition: 'background 0.2s',
              }}
            >
              <span
                style={{
                  width: 16,
                  fontSize: 10.5,
                  color: 'var(--text-dim)',
                  fontFamily: 'var(--font-mono)',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {idx + 1}
              </span>
              <StepIndicator status={step.status} />
              <span style={{ flex: 1, minWidth: 0 }}>
                <strong
                  style={{
                    fontWeight: 600,
                    color: step.status === 'pending' ? 'var(--text-muted)' : 'var(--text-primary)',
                  }}
                >
                  {meta.label}
                </strong>
                <span style={{ color: 'var(--text-dim)', marginLeft: 8, fontSize: 11.5 }}>
                  {meta.help}
                </span>
              </span>
              {step.status === 'degraded' ? (
                <span
                  style={{ ...numStyle, color: 'var(--warning)' }}
                  title={step.degradeReason ?? undefined}
                >
                  {t('workspace.pipeline.degraded')}
                  {typeof step.duration_s === 'number' ? ` · ${step.duration_s.toFixed(1)}s` : ''}
                </span>
              ) : step.status === 'completed' && typeof step.duration_s === 'number' ? (
                <span style={numStyle}>{step.duration_s.toFixed(1)}s</span>
              ) : step.status === 'retrying' ? (
                <span style={{ ...numStyle, color: 'var(--warning)' }}>
                  {t('workspace.pipeline.retrying', {
                    attempt: step.attempt ?? 1,
                    max: MAX_RETRIES,
                  })}
                  {stepElapsed(step) !== null ? ` · ${stepElapsed(step)}s` : ''}
                </span>
              ) : step.status === 'running' && stepElapsed(step) !== null ? (
                <span style={numStyle}>{stepElapsed(step)}s</span>
              ) : null}
            </li>
          )
        })}
      </ol>

      <p style={{ marginTop: 12, fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.5 }}>
        {t('workspace.pipeline.footer')}
      </p>
      {run.status === 'failed' && (
        <p
          data-testid="pipeline-failed"
          style={{ marginTop: 8, fontSize: 12, color: 'var(--danger)' }}
        >
          {t('workspace.pipeline.failedMsg', {
            error: run.error ?? t('workspace.pipeline.retryLater'),
          })}
        </p>
      )}
    </div>
  )
}

/** Per-step status badge. Running shows a rotating ring (a static glyph makes
 *  a live run look frozen); pending is a hollow dim dot. */
function StepIndicator({ status }: { status: string }): React.ReactElement {
  const base: React.CSSProperties = {
    width: 16,
    height: 16,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  }
  if (status === 'completed') {
    return (
      <span
        style={{
          ...base,
          borderRadius: '50%',
          background: 'var(--success)',
          color: 'var(--bg-deep)',
          fontSize: 10,
          fontWeight: 700,
        }}
      >
        ✓
      </span>
    )
  }
  if (status === 'running' || status === 'retrying') {
    return (
      <span style={base}>
        <span className="pipeline-spinner" />
      </span>
    )
  }
  if (status === 'degraded') {
    // The step finished but failed validation after all retries (non-critical
    // degrade). Amber ⚠ — NOT a green ✓ on a step that actually failed (BUG-058).
    return (
      <span
        style={{
          ...base,
          borderRadius: '50%',
          background: 'var(--warning)',
          color: 'var(--bg-deep)',
          fontSize: 10,
          fontWeight: 700,
        }}
      >
        !
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span
        style={{
          ...base,
          borderRadius: '50%',
          background: 'var(--danger)',
          color: 'var(--bg-deep)',
          fontSize: 10,
          fontWeight: 700,
        }}
      >
        ✕
      </span>
    )
  }
  // pending — hollow dim ring
  return (
    <span style={base}>
      <span
        style={{
          width: 9,
          height: 9,
          borderRadius: '50%',
          border: '1.5px solid var(--text-dim)',
        }}
      />
    </span>
  )
}

function labelForPipeline(pipelineType: string): string {
  // 这里的 key 是 pipeline 注册名（registry.py），不是 artifact.type。
  switch (pipelineType) {
    case 'research':
      return tSync('workspace.pipeline.type.research')
    case 'ic-memo':
      return tSync('workspace.pipeline.type.icMemo')
    case 'earnings':
      return tSync('workspace.pipeline.type.earnings')
    case 'lbo':
      return tSync('workspace.pipeline.type.lbo')
    case 'ddm':
      return tSync('workspace.pipeline.type.ddm')
    case 'comps':
      return tSync('workspace.pipeline.type.comps')
    case 'dcf':
      return tSync('workspace.pipeline.type.dcf')
    default:
      return pipelineType
  }
}

function estimateEta(steps: { status: string; duration_s?: number }[]): number | null {
  const completed = steps.filter(
    (s) => s.status === 'completed' && typeof s.duration_s === 'number',
  )
  if (completed.length === 0) return null
  const avg = completed.reduce((sum, s) => sum + (s.duration_s ?? 0), 0) / completed.length
  const remaining = steps.length - completed.length
  return Math.round(avg * remaining)
}
