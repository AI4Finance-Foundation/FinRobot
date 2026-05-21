// v5 PipelineProgressPanel — 6-step pipeline progress display (spec §5.1).
// Reads the live RunState from runStreamStore (which receives backend SSE
// events; see PR4a audit for the 6-event contract). Renders one row per
// step; matches the equity_research pipeline's step names exactly.

import { useRunStreamStore } from '../stores/runStreamStore'

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
  thesis: {
    label: '投资论点',
    help: '生成 target_price + 风险因素',
  },
  report: {
    label: '整合报告',
    help: '8 段标准章节 + LLM 叙事',
  },
}

interface PipelineProgressPanelProps {
  ticker: string
}

export function PipelineProgressPanel({ ticker }: PipelineProgressPanelProps): React.ReactElement | null {
  const run = useRunStreamStore((s) => s.runs[ticker])

  if (!run || run.dismissed) {
    return null
  }

  const eta = estimateEta(run.steps)

  return (
    <div
      data-testid="pipeline-progress-panel"
      style={{
        border: '1px solid var(--border)',
        borderRadius: 10,
        padding: 20,
        background: 'var(--bg-card, #fff)',
        margin: '12px 0',
      }}
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={spinnerStyle(run.status)} />
          <span style={{ fontWeight: 600, fontSize: 13 }}>
            正在跑 {labelForPipeline(run.pipelineType)}
          </span>
          {eta && (
            <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
              · 还剩 ~{eta}s
            </span>
          )}
        </div>
        <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
          {run.steps.filter((s) => s.status === 'completed').length}/{run.steps.length}
        </span>
      </header>
      <ol style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 6 }}>
        {run.steps.map((step, idx) => {
          const meta = STEP_LABELS[step.name] || { label: step.name, help: '' }
          return (
            <li
              key={step.name}
              data-testid={`pipeline-step-${step.name}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '6px 8px',
                borderRadius: 6,
                background:
                  step.status === 'running' ? 'rgba(16, 185, 129, 0.06)' : 'transparent',
                fontSize: 12.5,
              }}
            >
              <span style={{ width: 18, color: 'var(--text-faint)' }}>{`${idx + 1}.`}</span>
              <span style={{ width: 16, textAlign: 'center' }}>
                {statusGlyph(step.status)}
              </span>
              <span style={{ flex: 1 }}>
                <strong style={{ fontWeight: 600 }}>{meta.label}</strong>
                <span style={{ color: 'var(--text-faint)', marginLeft: 8, fontSize: 11.5 }}>
                  {meta.help}
                </span>
              </span>
              {typeof step.duration_s === 'number' && (
                <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
                  {step.duration_s.toFixed(1)}s
                </span>
              )}
            </li>
          )
        })}
      </ol>
      <p style={{ marginTop: 12, fontSize: 11, color: 'var(--text-faint)' }}>
        数字由代码算出，不是 LLM 编 · 任一 step 失败整体 pipeline 失败重跑
      </p>
      {run.status === 'failed' && (
        <p
          data-testid="pipeline-failed"
          style={{ marginTop: 8, fontSize: 12, color: 'var(--red, #EF4444)' }}
        >
          ⚠️ Pipeline 失败 · {run.error ?? '查看日志'}
        </p>
      )}
    </div>
  )
}

function spinnerStyle(status: string): React.CSSProperties {
  const base: React.CSSProperties = {
    width: 10,
    height: 10,
    borderRadius: '50%',
    display: 'inline-block',
  }
  if (status === 'running') {
    return { ...base, background: 'var(--green, #10B981)', boxShadow: '0 0 0 3px rgba(16,185,129,0.18)' }
  }
  if (status === 'failed') {
    return { ...base, background: 'var(--red, #EF4444)' }
  }
  return { ...base, background: 'var(--text-faint)' }
}

function statusGlyph(status: string): string {
  if (status === 'completed') return '✓'
  if (status === 'running') return '⟳'
  if (status === 'retrying') return '⟳'
  return '⏳'
}

function labelForPipeline(pipelineType: string): string {
  switch (pipelineType) {
    case 'equity_research':
      return 'AI 完整研报'
    case 'ic_memo':
      return '投委备忘'
    case 'earnings_analysis':
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
  const completed = steps.filter((s) => s.status === 'completed' && typeof s.duration_s === 'number')
  if (completed.length === 0) return null
  const avg = completed.reduce((sum, s) => sum + (s.duration_s ?? 0), 0) / completed.length
  const remaining = steps.length - completed.length
  return Math.round(avg * remaining)
}
