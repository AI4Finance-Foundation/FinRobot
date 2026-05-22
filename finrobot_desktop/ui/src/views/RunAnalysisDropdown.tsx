// v5 RunAnalysisDropdown — the 6-item「+ 跑分析 ▾」menu (spec §4).
// All six entries trigger POST /api/runs via runStreamStore.startRun.
// No disabled placeholder items, no "我手调假设" entry — those were
// explicitly cut in spec §4 to avoid dead-button drift.

import { useRunStreamStore } from '../stores/runStreamStore'
import { useToastStore } from '../stores/toastStore'

interface MenuItem {
  pipelineType: string
  title: string
  duration: string
  group: string
  recommended?: boolean
}

// pipelineType 必须和 finagent/engine/pipelines/registry.py 的 key 一字不差。
// 历史踩坑：UI 曾用 equity_research / ic_memo / earnings_analysis，后端返
// "Invalid pipeline" 把整条 + 跑分析 ▾ 打死。
const MENU: MenuItem[] = [
  // AI 研报 group
  {
    pipelineType: 'research',
    title: 'AI 完整研报',
    duration: '60s',
    group: 'AI 研报',
    recommended: true,
  },
  { pipelineType: 'ic-memo', title: '投委备忘 (IC Memo)', duration: '60s', group: 'AI 研报' },
  { pipelineType: 'earnings', title: '财报电话会分析', duration: '45s', group: 'AI 研报' },
  // 估值模型 group
  { pipelineType: 'dcf', title: 'DCF 现金流折现', duration: '45s', group: '估值模型' },
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
  const addToast = useToastStore((s) => s.addToast)

  async function launch(item: MenuItem) {
    if (existingRun?.status === 'running') {
      // Surface why the click did nothing — silent-return looked broken.
      addToast({
        type: 'info',
        title: `${ticker} 已有分析在跑`,
        description: `当前 pipeline: ${existingRun.pipelineType} · 等当前 run 结束再起新的`,
      })
      onLaunched?.()
      return
    }
    console.log('[run-analysis] launch', { ticker, pipelineType: item.pipelineType })
    try {
      const runId = await startRun(item.pipelineType, ticker)
      console.log('[run-analysis] startRun resolved', { runId, ticker })
      // Always pop a confirmation toast — the in-page PipelineProgressPanel
      // can be missed if it renders above the fold while the user is reading
      // a section card lower down.
      addToast({
        type: 'success',
        title: `${ticker} ${item.title} 已启动`,
        description: `run_id: ${runId.slice(0, 12)} · 顶部进度面板会逐步更新`,
      })
      onLaunched?.()
    } catch (err) {
      console.error('[run-analysis] startRun failed', err)
      const msg = err instanceof Error ? err.message : String(err)
      addToast({
        type: 'error',
        title: `${ticker} 跑分析失败`,
        description:
          msg.includes('Failed to fetch') || msg.includes('NetworkError')
            ? '后端未响应 — 检查 sidecar 是否启动（StatusBar 应显示「已连接」）'
            : msg,
      })
      onLaunched?.()
    }
  }

  const groups = Array.from(new Set(MENU.map((m) => m.group)))

  return (
    <div
      data-testid="run-analysis-dropdown"
      style={{
        background: 'var(--bg-card)',
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
                      color: 'var(--success)',
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
