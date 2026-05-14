// PipelinePage — Phase 3 wrapper: maps pipelineId → StocksPage (empty-state).
// Full pipeline runner UI is Phase 4.

import { useEffect } from 'react'
import { StocksPage } from '../pages/StocksPage'
import { useStocksStore } from '../stores/stocksStore'
import { getPipeline } from '../lib/pipelines'

interface PipelinePageProps {
  pipelineId: string
}

export function PipelinePage({ pipelineId }: PipelinePageProps): React.ReactElement {
  const pipeline = getPipeline(pipelineId)

  // If there's no meaningful pipeline mapping, show a placeholder card.
  // Full pipeline runner: TODO Phase 4
  if (!pipeline) {
    return (
      <div className="editor-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <div
          style={{
            border: '1px dashed var(--border)',
            borderRadius: 8,
            padding: 32,
            textAlign: 'center',
            color: 'var(--text-2)',
            maxWidth: 400,
          }}
        >
          <div style={{ fontSize: '0.9rem', marginBottom: 8 }}>Pipeline 详情页</div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-3)' }}>
            Pipeline ID: <code style={{ fontFamily: 'var(--font-mono)' }}>{pipelineId}</code>
          </div>
          <div style={{ marginTop: 12, fontSize: '0.75rem', color: 'var(--text-3)' }}>
            TODO Phase 4: 运行面板 + 参数配置
          </div>
        </div>
      </div>
    )
  }

  return <PipelineView pipelineId={pipelineId} />
}

// Inner view: syncs pipeline type then renders StocksPage (empty state is fine here).
function PipelineView({ pipelineId }: { pipelineId: string }) {
  const setActiveTab = useStocksStore((s) => s.setActiveTab)

  useEffect(() => {
    // Map pipeline to a sensible default stocks tab
    if (pipelineId === 'PL-002') {
      setActiveTab('history')
    } else {
      setActiveTab('financials')
    }
  }, [pipelineId, setActiveTab])

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Placeholder header showing which pipeline is selected */}
      <div
        style={{
          padding: '10px 20px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-1)',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.72rem',
            color: 'var(--amber)',
            background: 'rgba(245, 166, 35, 0.08)',
            padding: '2px 8px',
            borderRadius: 4,
          }}
        >
          {pipelineId}
        </span>
        <span style={{ fontSize: '0.85rem', color: 'var(--text-1)' }}>
          {getPipeline(pipelineId)?.name}
        </span>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-3)', marginLeft: 'auto' }}>
          TODO Phase 4: 运行面板
        </span>
      </div>
      <div style={{ flex: 1, overflow: 'hidden' }}>
        <StocksPage />
      </div>
    </div>
  )
}
