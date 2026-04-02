import { useState } from 'react'
import { usePipelineStream } from '../hooks/usePipelineStream'

export default function ResearchView() {
  const [ticker, setTicker] = useState('')
  const stream = usePipelineStream('/stream/research', { ticker })

  const completedEvents = stream.events.filter((e) => e.status === 'completed')
  const lastText = completedEvents.map((e) => e.text).join('\n\n')

  return (
    <div className="view-container">
      <h2 style={{ marginBottom: 16 }}>Equity Research</h2>
      <div className="input-row">
        <input
          type="text"
          placeholder="Ticker (e.g. AAPL)"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === 'Enter' && ticker && stream.start()}
        />
        <button
          className="btn-primary"
          onClick={stream.start}
          disabled={!ticker || stream.status === 'running'}
        >
          {stream.status === 'running' ? 'Running...' : 'Run Analysis'}
        </button>
      </div>

      {stream.status !== 'idle' && (
        <>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${stream.progress * 100}%` }}
            />
          </div>

          <ul className="step-list">
            {stream.events.map((e, i) => (
              <li key={i} className={`step-item ${e.status}`}>
                {e.status === 'completed' ? '\u2713' : e.status === 'running' ? '\u25CB' : '\u2717'}{' '}
                {e.step.replace(/_/g, ' ')}
              </li>
            ))}
          </ul>
        </>
      )}

      {stream.error && <div className="error-msg">{stream.error}</div>}

      {lastText && <div className="output-area">{lastText}</div>}
    </div>
  )
}
