import { useState } from 'react'
import { usePipelineStream } from '../hooks/usePipelineStream'

interface SensitivityData {
  wacc_values: number[]
  tg_values: number[]
  implied_prices: (number | null)[][]
}

interface DCFResultData {
  implied_price: number
  wacc: number
  enterprise_value: number
  equity_value?: number
  pv_fcf_total?: number
  pv_terminal?: number
  terminal_value?: number
  sensitivity_table?: SensitivityData
}

function isDCFResult(data: unknown): data is DCFResultData {
  return (
    data != null &&
    typeof data === 'object' &&
    'implied_price' in data &&
    typeof (data as Record<string, unknown>).implied_price === 'number' &&
    'wacc' in data &&
    typeof (data as Record<string, unknown>).wacc === 'number' &&
    'enterprise_value' in data &&
    typeof (data as Record<string, unknown>).enterprise_value === 'number'
  )
}

function isSensitivityData(data: unknown): data is SensitivityData {
  if (data == null || typeof data !== 'object') return false
  const d = data as Record<string, unknown>
  return (
    Array.isArray(d.wacc_values) &&
    Array.isArray(d.tg_values) &&
    Array.isArray(d.implied_prices)
  )
}

export default function DCFView() {
  const [ticker, setTicker] = useState('')
  const stream = usePipelineStream('/stream/dcf', { ticker })

  const completedEvents = stream.events.filter((e) => e.status === 'completed')
  const dcfEvent = completedEvents.find((e) => isDCFResult(e.structured))
  const dcfData = dcfEvent && isDCFResult(dcfEvent.structured) ? dcfEvent.structured : null
  const sensitivity =
    dcfData && isSensitivityData(dcfData.sensitivity_table) ? dcfData.sensitivity_table : null
  const lastText = completedEvents.map((e) => e.text).join('\n\n')

  return (
    <div className="view-container">
      <h2 style={{ marginBottom: 16 }}>DCF Valuation</h2>
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
          {stream.status === 'running' ? 'Running...' : 'Run DCF'}
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

      {dcfData && (
        <div className="card">
          <h3>DCF Result</h3>
          <table>
            <tbody>
              <tr>
                <td>WACC</td>
                <td>{(dcfData.wacc * 100).toFixed(2)}%</td>
              </tr>
              <tr>
                <td>Enterprise Value</td>
                <td>${(dcfData.enterprise_value / 1e9).toFixed(2)}B</td>
              </tr>
              <tr>
                <td>Implied Share Price</td>
                <td>${dcfData.implied_price.toFixed(2)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {sensitivity && <SensitivityTable data={sensitivity} />}

      {lastText && <div className="output-area">{lastText}</div>}
    </div>
  )
}

function SensitivityTable({ data }: { data: SensitivityData }) {
  return (
    <div className="card">
      <h3>Sensitivity Analysis (WACC vs Terminal Growth)</h3>
      <table>
        <thead>
          <tr>
            <th>WACC \ TG</th>
            {data.tg_values.map((tg) => (
              <th key={tg}>{(tg * 100).toFixed(1)}%</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.wacc_values.map((wacc, wi) => (
            <tr key={wacc}>
              <td style={{ fontWeight: 600 }}>{(wacc * 100).toFixed(1)}%</td>
              {data.implied_prices[wi].map((price, ti) => (
                <td key={ti}>{price != null ? `$${price.toFixed(2)}` : '-'}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
