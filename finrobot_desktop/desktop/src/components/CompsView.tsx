import { useState } from 'react'
import { usePipelineStream } from '../hooks/usePipelineStream'

interface CompanyRow {
  ticker: string
  name?: string | null
  revenue?: number
  ev_ebitda?: number | null
  ev_revenue?: number | null
  pe_ratio?: number | null
}

interface PeerCompsData {
  target: CompanyRow
  peers: CompanyRow[]
  median_ev_ebitda?: number | null
  median_pe?: number | null
  median_ev_revenue?: number | null
}

function isPeerCompsData(data: unknown): data is PeerCompsData {
  if (data == null || typeof data !== 'object') return false
  const d = data as Record<string, unknown>
  return (
    d.target != null &&
    typeof d.target === 'object' &&
    'ticker' in (d.target as Record<string, unknown>) &&
    Array.isArray(d.peers)
  )
}

export default function CompsView() {
  const [ticker, setTicker] = useState('')
  const [peers, setPeers] = useState('')
  const stream = usePipelineStream('/stream/comps', { ticker, peers })

  const completedEvents = stream.events.filter((e) => e.status === 'completed')
  const compsEvent = completedEvents.find((e) => isPeerCompsData(e.structured))
  const compsData = compsEvent && isPeerCompsData(compsEvent.structured) ? compsEvent.structured : null
  const lastText = completedEvents.map((e) => e.text).join('\n\n')

  const peersList = compsData?.peers ?? []
  const target = compsData?.target ?? null

  return (
    <div className="view-container">
      <h2 style={{ marginBottom: 16 }}>Comparable Companies</h2>
      <div className="input-row">
        <input
          type="text"
          placeholder="Ticker (e.g. AAPL)"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
        />
        <input
          type="text"
          placeholder="Peers (e.g. MSFT,GOOG,META)"
          value={peers}
          onChange={(e) => setPeers(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === 'Enter' && ticker && stream.start()}
          style={{ flex: 1 }}
        />
        <button
          className="btn-primary"
          onClick={stream.start}
          disabled={!ticker || stream.status === 'running'}
        >
          {stream.status === 'running' ? 'Running...' : 'Run Comps'}
        </button>
      </div>

      {stream.status !== 'idle' && (
        <div className="progress-bar">
          <div
            className="progress-fill"
            style={{ width: `${stream.progress * 100}%` }}
          />
        </div>
      )}

      {stream.error && <div className="error-msg">{stream.error}</div>}

      {(target || peersList.length > 0) && (
        <div className="card">
          <h3>Multiples Comparison</h3>
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>EV/EBITDA</th>
                <th>EV/Revenue</th>
                <th>P/E</th>
              </tr>
            </thead>
            <tbody>
              {target && (
                <tr style={{ fontWeight: 600 }}>
                  <td>{target.ticker}</td>
                  <td>{fmtMultiple(target.ev_ebitda)}</td>
                  <td>{fmtMultiple(target.ev_revenue)}</td>
                  <td>{fmtMultiple(target.pe_ratio)}</td>
                </tr>
              )}
              {peersList.map((p) => (
                <tr key={p.ticker}>
                  <td>{p.ticker}</td>
                  <td>{fmtMultiple(p.ev_ebitda)}</td>
                  <td>{fmtMultiple(p.ev_revenue)}</td>
                  <td>{fmtMultiple(p.pe_ratio)}</td>
                </tr>
              ))}
              {compsData && (
                <tr style={{ borderTop: '2px solid #30363d', fontWeight: 600 }}>
                  <td>Median</td>
                  <td>{fmtMultiple(compsData.median_ev_ebitda)}</td>
                  <td>{fmtMultiple(compsData.median_ev_revenue)}</td>
                  <td>{fmtMultiple(compsData.median_pe)}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {lastText && <div className="output-area">{lastText}</div>}
    </div>
  )
}

function fmtMultiple(v: number | null | undefined): string {
  if (v == null) return '-'
  return v.toFixed(1) + 'x'
}
