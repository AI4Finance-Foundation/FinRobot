import { useState } from 'react'
import { usePipelineStream, PipelineEvent } from '../hooks/usePipelineStream'
import Layout from './Layout'
import DataPanel from './DataPanel'
import ReportActions from './ReportActions'
import {
  RevenueEbitdaChart,
  MarginTrendChart,
  SensitivityHeatmap,
  FootballField,
  PriceChart,
  EpsPeChart,
  WaterfallChart,
  CompanyRadarChart,
  PeerComparisonChart,
} from './charts'

interface ChartEntry {
  chart_type: string
  title: string
  data: Record<string, number | string | boolean | null>[]
}

function extractCharts(events: PipelineEvent[]): ChartEntry[] {
  return events
    .filter((e) => {
      const s = e.structured as Record<string, unknown> | null
      return s?.chart_data && typeof s.chart_data === 'object'
    })
    .flatMap((e) => {
      const cd = (e.structured as Record<string, unknown>).chart_data as Record<string, unknown>
      return Array.isArray(cd.charts) ? (cd.charts as ChartEntry[]) : []
    })
}

function renderChart(chart: ChartEntry, key: number) {
  switch (chart.chart_type) {
    case 'revenue_ebitda':
      return <RevenueEbitdaChart key={key} data={chart.data} title={chart.title} />
    case 'margin_trend':
      return <MarginTrendChart key={key} data={chart.data} title={chart.title} />
    case 'sensitivity':
      return <SensitivityHeatmap key={key} data={chart.data} title={chart.title} />
    case 'football_field':
      return <FootballField key={key} data={chart.data} title={chart.title} />
    case 'price':
      return <PriceChart key={key} data={chart.data} title={chart.title} />
    case 'eps_pe':
      return <EpsPeChart key={key} data={chart.data} title={chart.title} />
    case 'waterfall':
      return <WaterfallChart key={key} data={chart.data} title={chart.title} />
    case 'radar':
      return <CompanyRadarChart key={key} data={chart.data} title={chart.title} />
    case 'peer_comparison':
      return <PeerComparisonChart key={key} data={chart.data} title={chart.title} />
    default:
      return null
  }
}

export default function ResearchView() {
  const [ticker, setTicker] = useState('')
  const stream = usePipelineStream('/stream/research', { ticker })

  const completedEvents = stream.events.filter((e) => e.status === 'completed')
  const lastText = completedEvents.map((e) => e.text).join('\n\n')
  const chartData = extractCharts(stream.events)

  const currentStep = stream.events.length > 0
    ? stream.events[stream.events.length - 1].step.replace(/_/g, ' ')
    : undefined

  const leftContent = (
    <>
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
        <ul className="step-list">
          {stream.events.map((e, i) => (
            <li key={i} className={`step-item ${e.status}`}>
              {e.status === 'completed' ? '\u2713' : e.status === 'running' ? '\u25CB' : '\u2717'}{' '}
              {e.step.replace(/_/g, ' ')}
            </li>
          ))}
        </ul>
      )}

      {stream.error && <div className="error-msg">{stream.error}</div>}

      {lastText && <div className="output-area">{lastText}</div>}

      {stream.status === 'completed' && ticker && (
        <ReportActions ticker={ticker} />
      )}
    </>
  )

  const rightContent = chartData.length > 0 ? (
    <DataPanel title="Analysis Charts">
      {chartData.map((chart, i) => renderChart(chart, i))}
    </DataPanel>
  ) : null

  return (
    <Layout
      leftPanel={leftContent}
      rightPanel={rightContent}
      progress={stream.status !== 'idle' ? stream.progress : undefined}
      progressLabel={currentStep}
    />
  )
}
