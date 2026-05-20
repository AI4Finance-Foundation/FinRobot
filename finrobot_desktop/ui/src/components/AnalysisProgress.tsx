/**
 * AnalysisProgress — full-screen progress overlay for the research pipeline.
 *
 * Shows: SVG progress ring + percentage, ticker name, step list with
 * status icons and elapsed time per step.
 *
 * Props:
 *   ticker          — the stock being analyzed
 *   steps           — step array from runStreamStore
 *   progress        — 0-1 from runStreamStore
 *   status          — 'running' | 'completed' | 'failed'
 *   error           — error message if failed
 *   onViewReport    — callback when user clicks "view report" after completion
 */

import type { RunStep } from '../stores/runStreamStore'

// Pipeline step names in Chinese (aligned to research pipeline order)
const STEP_LABELS: Record<string, string> = {
  'Step 1':  '拉取财务数据',
  'Step 2':  '选择可比公司',
  'Step 3':  'DCF 参数估计',
  'Step 4':  'LBO 参数估计',
  'Step 5':  'DCF 计算',
  'Step 6':  'LBO 计算',
  'Step 7':  '催化剂分析',
  'Step 8':  '投资论点',
  'Step 9':  '生成报告',
  // Backend may send Chinese names already — pass through
}

function localizeStepName(name: string): string {
  return STEP_LABELS[name] ?? name
}

// ── SVG Progress Ring ──────────────────────────────────────────────────────

function ProgressRing({ progress }: { progress: number }) {
  const size = 120
  const strokeWidth = 6
  const r = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * r
  const offset = circumference * (1 - Math.min(Math.max(progress, 0), 1))
  const pct = Math.round(progress * 100)

  return (
    <div style={{ position: 'relative', width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {/* Track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--border)"
          strokeWidth={strokeWidth}
        />
        {/* Progress arc */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{
            transition: 'stroke-dashoffset 0.4s ease',
            transform: 'rotate(-90deg)',
            transformOrigin: '50% 50%',
          }}
        />
      </svg>
      {/* Center text */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'var(--font-mono)',
          fontSize: 28,
          fontWeight: 700,
          color: 'var(--accent)',
          letterSpacing: '-0.02em',
        }}
      >
        {pct}%
      </div>
    </div>
  )
}

// ── Step list icons ────────────────────────────────────────────────────────

function StepIcon({ status }: { status: string }) {
  if (status === 'completed') {
    return (
      <span style={{ color: 'var(--positive)', fontSize: 14, lineHeight: 1 }}>
        &#10003;
      </span>
    )
  }
  if (status === 'running') {
    return (
      <span
        style={{
          display: 'inline-block',
          width: 10,
          height: 10,
          borderRadius: '50%',
          background: 'var(--accent)',
          animation: 'pulse-dot 1.2s ease infinite',
        }}
      />
    )
  }
  // pending / retrying
  return (
    <span
      style={{
        display: 'inline-block',
        width: 10,
        height: 10,
        borderRadius: '50%',
        border: '2px solid var(--border)',
        background: 'transparent',
      }}
    />
  )
}

// ── Main Component ─────────────────────────────────────────────────────────

interface AnalysisProgressProps {
  ticker: string
  steps: RunStep[]
  progress: number
  status: 'running' | 'completed' | 'failed'
  error: string | null
  /** Completed → view report. */
  onViewReport?: () => void
  /** Failed → start a fresh research run for the same ticker. */
  onRetry?: () => void
  /** Failed → dismiss the overlay without retrying (lets the user navigate
   *  to other tabs). Without this the user is trapped until they refresh. */
  onDismiss?: () => void
}

export default function AnalysisProgress({
  ticker,
  steps,
  progress,
  status,
  error,
  onViewReport,
  onRetry,
  onDismiss,
}: AnalysisProgressProps) {
  const isComplete = status === 'completed'
  const isFailed = status === 'failed'

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 24,
        padding: '40px 20px',
        minHeight: 400,
      }}
    >
      {/* Progress ring */}
      <ProgressRing progress={progress} />

      {/* Title */}
      <div style={{ textAlign: 'center' }}>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 16,
            fontWeight: 700,
            color: 'var(--text-primary)',
            letterSpacing: '-0.01em',
            marginBottom: 4,
          }}
        >
          {isComplete ? '分析完成' : isFailed ? '分析失败' : `正在分析 ${ticker}`}
        </div>
        {isFailed && error && (
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--negative)',
              marginTop: 4,
            }}
          >
            {error}
          </div>
        )}
      </div>

      {/* Step list */}
      {steps.length > 0 && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            width: '100%',
            maxWidth: 360,
          }}
        >
          {steps.map((step, idx) => (
            <div
              key={idx}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '6px 12px',
                background: step.status === 'running' ? 'var(--bg-2)' : 'transparent',
                borderRadius: 'var(--r-sm)',
                transition: 'background 0.2s',
              }}
            >
              <StepIcon status={step.status} />
              <span
                style={{
                  flex: 1,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  color:
                    step.status === 'completed'
                      ? 'var(--text-secondary)'
                      : step.status === 'running'
                        ? 'var(--text-primary)'
                        : 'var(--text-muted)',
                  fontWeight: step.status === 'running' ? 600 : 400,
                }}
              >
                {localizeStepName(step.name)}
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  color: 'var(--text-muted)',
                  minWidth: 36,
                  textAlign: 'right',
                }}
              >
                {step.status === 'completed' && step.duration_s != null
                  ? `${step.duration_s}s`
                  : step.status === 'running'
                    ? '...'
                    : ''}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Complete action */}
      {isComplete && onViewReport && (
        <button
          onClick={onViewReport}
          style={{
            marginTop: 8,
            padding: '10px 28px',
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            fontWeight: 700,
            color: '#000',
            background: 'var(--accent)',
            border: '1px solid transparent',
            borderRadius: 'var(--r-sm)',
            cursor: 'pointer',
            letterSpacing: '0.02em',
            transition: 'background 0.15s',
          }}
        >
          查看报告
        </button>
      )}

      {/* Failed actions — retry + dismiss so the user can leave the overlay
          without a hard refresh. */}
      {isFailed && (onRetry || onDismiss) && (
        <div style={{ marginTop: 8, display: 'flex', gap: 10 }}>
          {onRetry && (
            <button
              onClick={onRetry}
              style={{
                padding: '10px 24px',
                fontFamily: 'var(--font-mono)',
                fontSize: 13,
                fontWeight: 700,
                color: '#000',
                background: 'var(--accent)',
                border: '1px solid transparent',
                borderRadius: 'var(--r-sm)',
                cursor: 'pointer',
                letterSpacing: '0.02em',
              }}
            >
              重试
            </button>
          )}
          {onDismiss && (
            <button
              onClick={onDismiss}
              style={{
                padding: '10px 24px',
                fontFamily: 'var(--font-mono)',
                fontSize: 13,
                fontWeight: 600,
                color: 'var(--text-secondary)',
                background: 'transparent',
                border: '1px solid var(--border)',
                borderRadius: 'var(--r-sm)',
                cursor: 'pointer',
                letterSpacing: '0.02em',
              }}
            >
              关闭
            </button>
          )}
        </div>
      )}

      {/* Pulse animation for active step dot */}
      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(0.8); }
        }
      `}</style>
    </div>
  )
}
