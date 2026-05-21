// v5 RunAnalysisDropdown — the 6-item「+ 跑分析 ▾」menu (spec §4).
// All six entries trigger POST /api/runs via runStreamStore.startRun.
// No disabled placeholder items, no "我手调假设" entry — those were
// explicitly cut in spec §4 to avoid dead-button drift.

import { useRunStreamStore } from '../stores/runStreamStore'

interface MenuItem {
  pipelineType: string
  title: string
  duration: string
  group: string
  recommended?: boolean
}

const MENU: MenuItem[] = [
  // AI 研报 group
  {
    pipelineType: 'equity_research',
    title: 'AI 完整研报',
    duration: '60s',
    group: 'AI 研报',
    recommended: true,
  },
  { pipelineType: 'ic_memo', title: '投委备忘 (IC Memo)', duration: '60s', group: 'AI 研报' },
  { pipelineType: 'earnings_analysis', title: '财报电话会分析', duration: '45s', group: 'AI 研报' },
  // 估值模型 group
  { pipelineType: 'lbo', title: 'LBO 估值', duration: '45s', group: '估值模型' },
  { pipelineType: 'ddm', title: '股息折现 (DDM)', duration: '45s', group: '估值模型' },
  { pipelineType: 'comps', title: '单独同业对标', duration: '45s', group: '估值模型' },
]

interface RunAnalysisDropdownProps {
  ticker: string
  /** Called after the run is queued so the trigger can close itself. */
  onLaunched?: () => void
}

export function RunAnalysisDropdown({ ticker, onLaunched }: RunAnalysisDropdownProps): React.ReactElement {
  const startRun = useRunStreamStore((s) => s.startRun)
  const existingRun = useRunStreamStore((s) => s.runs[ticker])

  async function launch(item: MenuItem) {
    if (existingRun?.status === 'running') {
      return // one active run per ticker
    }
    await startRun(item.pipelineType, ticker)
    onLaunched?.()
  }

  const groups = Array.from(new Set(MENU.map((m) => m.group)))

  return (
    <div
      data-testid="run-analysis-dropdown"
      style={{
        background: 'var(--bg-card, #fff)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: 6,
        minWidth: 260,
        boxShadow: '0 8px 24px rgba(0, 0, 0, 0.10)',
        fontSize: 13,
      }}
    >
      {groups.map((g) => (
        <div key={g} style={{ padding: '4px 0' }}>
          <div
            style={{
              fontSize: 11,
              color: 'var(--text-faint)',
              letterSpacing: 0.4,
              textTransform: 'uppercase',
              padding: '4px 10px',
            }}
          >
            {g}
          </div>
          {MENU.filter((m) => m.group === g).map((item) => (
            <button
              key={item.pipelineType}
              type="button"
              data-testid={`run-${item.pipelineType}`}
              onClick={() => launch(item)}
              disabled={existingRun?.status === 'running'}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                width: '100%',
                padding: '8px 10px',
                border: 'none',
                background: item.recommended ? 'rgba(16, 185, 129, 0.06)' : 'transparent',
                color: 'var(--text)',
                cursor: existingRun?.status === 'running' ? 'not-allowed' : 'pointer',
                textAlign: 'left',
                borderRadius: 6,
              }}
            >
              <span style={{ fontWeight: item.recommended ? 600 : 400 }}>
                {item.title}
                {item.recommended && (
                  <span
                    style={{
                      marginLeft: 6,
                      fontSize: 10,
                      color: 'var(--green, #10B981)',
                      fontWeight: 500,
                    }}
                  >
                    · 推荐
                  </span>
                )}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>{item.duration}</span>
            </button>
          ))}
        </div>
      ))}
      {existingRun?.status === 'running' && (
        <div
          style={{
            padding: '6px 10px',
            color: 'var(--text-faint)',
            fontSize: 11,
            borderTop: '1px solid var(--border-soft)',
            marginTop: 4,
          }}
        >
          当前已有 {existingRun.pipelineType} 运行中 — 等待完成
        </div>
      )}
    </div>
  )
}
