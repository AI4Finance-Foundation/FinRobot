import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAppStore } from '../stores/appStore'

export default function StatusBar() {
  const ticker = useAppStore((s) => s.ticker)
  const phase = useAppStore((s) => s.phase)
  const pipelineType = useAppStore((s) => s.pipelineType)

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/settings')
      if (error) throw new Error('Failed to load settings')
      return data
    },
  })

  const modelLabel = settings?.model_name ?? '—'

  const phaseLabel = (() => {
    switch (phase) {
      case 'idle': return 'Ready'
      case 'loading_data': return 'Loading data…'
      case 'data_ready': return 'Data loaded'
      case 'running_pipeline': return 'Running pipeline…'
      case 'pipeline_done': return 'Complete'
      case 'interactive': return 'Interactive'
      default: return 'Ready'
    }
  })()

  const isRunning = phase === 'running_pipeline' || phase === 'loading_data'

  return (
    <footer className="statusbar">
      {/* Left: connection + model */}
      <div className="statusbar-group">
        <span className={`statusbar-dot${isRunning ? ' running' : ''}`} />
        <span className="statusbar-text">{phaseLabel}</span>
        <span className="statusbar-divider" />
        <span className="statusbar-text statusbar-mono">{modelLabel}</span>
      </div>

      {/* Center: ticker + pipeline */}
      <div className="statusbar-group">
        {ticker && phase !== 'idle' && (
          <>
            <span className="statusbar-text statusbar-mono statusbar-gold">{ticker}</span>
            <span className="statusbar-divider" />
            <span className="statusbar-text">{pipelineType.toUpperCase()}</span>
          </>
        )}
      </div>

      {/* Right: shortcuts */}
      <div className="statusbar-group">
        <span className="statusbar-hint">
          <kbd className="statusbar-kbd">⌘K</kbd> Commands
        </span>
        <span className="statusbar-hint">
          <kbd className="statusbar-kbd">⌘/</kbd> Shortcuts
        </span>
      </div>
    </footer>
  )
}
