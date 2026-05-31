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
import { useLatestArtifact } from '../hooks/useV5Artifacts'

// Backend Pipeline.max_retries — mirrored here only to render "重试中 n/3".
const MAX_RETRIES = 3

const STEP_LABELS: Record<string, { label: string; help: string }> = {
  data_collection: {
    label: '数据收集',
    help: '拉取 10-K / 10-Q / 价格 / 新闻',
  },
  catalyst_analysis: {
    label: '催化剂识别',
    help: '新闻分类 + 事件提取 + 影响打分',
  },
  peer_analysis: {
    label: '同业对标',
    help: '5 家可比公司财务比较',
  },
  financial_modeling: {
    label: '财务建模',
    help: 'DCF 蒙特卡洛 + Comps + 敏感性',
  },
  ownership_governance_analysis: {
    label: '股权与治理',
    help: '内部人交易 + 机构持仓 + 高管薪酬',
  },
  technical_analysis: {
    label: '技术与高阶',
    help: '蒙特卡洛 + 狙击位 + 价格走势',
  },
  thesis: {
    label: '投资论点',
    help: '生成 target_price + 风险因素',
  },
  report: {
    label: '整合报告',
    help: '13 章研报 + LLM 叙事',
  },
}

interface PipelineProgressPanelProps {
  ticker: string
}

export function PipelineProgressPanel({
  ticker,
}: PipelineProgressPanelProps): React.ReactElement | null {
  const run = useRunStreamStore((s) => s.runs[ticker])
  const dismiss = useRunStreamStore((s) => s.dismiss)
  const navigate = useNavigate()
  // Pull the freshly-invalidated latest artifact so the "→ 打开研报" CTA can
  // route directly into the report view that just got generated.
  const { latest } = useLatestArtifact(ticker, 'equity_research')

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
              ? `${labelForPipeline(run.pipelineType)} · 完成`
              : run.status === 'failed'
                ? `${labelForPipeline(run.pipelineType)} · 失败`
                : `正在生成 ${labelForPipeline(run.pipelineType)}`}
          </span>
          {run.status === 'running' && (
            <span
              style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
            >
              · 已运行 {runElapsed}s{eta ? ` · 还剩 ~${eta}s` : ''}
            </span>
          )}
          {run.status === 'completed' && totalDuration > 0 && (
            <span
              style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
            >
              · 总耗时 {totalDuration.toFixed(1)}s
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
          {run.status === 'completed' && latest && (
            <button
              type="button"
              data-testid="pipeline-open-report"
              onClick={() => navigate(`/stocks/${ticker}/runs/${latest.id}`)}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                padding: '5px 11px',
                borderRadius: 6,
                background: 'linear-gradient(135deg, var(--secondary) 0%, var(--primary) 100%)',
                color: 'white',
                border: 'none',
                cursor: 'pointer',
                letterSpacing: '0.04em',
              }}
            >
              → 打开研报
            </button>
          )}
          {(run.status === 'completed' || run.status === 'failed') && (
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
              aria-label="关闭进度面板"
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
          const meta = STEP_LABELS[step.name] || { label: step.name, help: '' }
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
              {step.status === 'completed' && typeof step.duration_s === 'number' ? (
                <span style={numStyle}>{step.duration_s.toFixed(1)}s</span>
              ) : step.status === 'retrying' ? (
                <span style={{ ...numStyle, color: 'var(--warning)' }}>
                  重试中 {step.attempt ?? 1}/{MAX_RETRIES}
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
        数字由代码算出，不是 LLM 编 · 任一步骤失败整份研报重新生成
      </p>
      {run.status === 'failed' && (
        <p
          data-testid="pipeline-failed"
          style={{ marginTop: 8, fontSize: 12, color: 'var(--danger)' }}
        >
          ⚠️ 研报生成失败 · {run.error ?? '请稍后重试'}
        </p>
      )}
    </div>
  )
}

/** Per-step status badge. Running shows a real rotating ring (the old static
 *  "⟳" made a live run look frozen); pending is a hollow dim dot, not a ⏳. */
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
      return 'AI 完整研报'
    case 'ic-memo':
      return '投委备忘'
    case 'earnings':
      return '财报电话会分析'
    case 'lbo':
      return 'LBO 估值'
    case 'ddm':
      return '股息折现'
    case 'comps':
      return '同业对标'
    case 'dcf':
      return 'DCF 估值'
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
