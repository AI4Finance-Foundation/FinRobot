import { useAppStore } from '../stores/appStore'
import { ErrorBoundary } from '../components/ErrorBoundary'
import TickerInput from '../components/TickerInput'
import WarningBanner from '../components/WarningBanner'
import FinancialsPanel from '../components/FinancialsPanel'
import PipelineRunner from '../components/PipelineRunner'
import AssumptionsEditor from '../components/AssumptionsEditor'
import ValuationCard from '../components/ValuationCard'
import ExportBar from '../components/ExportBar'
import SensitivityHeatmap from '../components/charts/SensitivityHeatmap'
import WaterfallChart from '../components/charts/WaterfallChart'
import RevenueEbitdaChart from '../components/charts/RevenueEbitdaChart'
import MarginTrendChart from '../components/charts/MarginTrendChart'
import {
  sensitivityGridToHeatmapRows,
  dcfResultToWaterfallData,
  dcfResultToRevenueEbitdaData,
  dcfResultToMarginData,
} from '../utils/chartAdapters'

interface Props {
  onOpenSettings: () => void
}

export default function TickerWorkspace({ onOpenSettings }: Props) {
  const {
    ticker,
    phase,
    warnings,
    dcfResult,
    sensitivityData,
    currentPrice,
  } = useAppStore()

  const showDcfResults = phase === 'pipeline_done' || phase === 'interactive'

  return (
    <>
      {/* ── Top Bar ── */}
      <header className="topbar">
        <div className="topbar-logo">
          <svg viewBox="0 0 20 20" fill="none">
            <rect x="1" y="4" width="4" height="12" rx="1" fill="#C9A84C" />
            <rect x="8" y="2" width="4" height="14" rx="1" fill="#C9A84C" opacity="0.6" />
            <rect x="15" y="6" width="4" height="10" rx="1" fill="#C9A84C" opacity="0.35" />
          </svg>
          Fin<span className="brand-accent">Agent</span>
        </div>

        <div className="topbar-divider" />

        <ErrorBoundary>
          <TickerInput />
        </ErrorBoundary>

        {/* Ticker info in topbar when loaded */}
        {ticker && phase !== 'idle' && currentPrice != null && (
          <>
            <div className="topbar-divider" />
            <div className="ticker-display">
              <span className="ticker-symbol">{ticker}</span>
              <span className="ticker-price font-mono">
                ${currentPrice.toFixed(2)}
              </span>
            </div>
          </>
        )}

        <div className="topbar-spacer" />

        <button
          className="topbar-btn"
          onClick={onOpenSettings}
          title="Settings"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <circle cx="8" cy="8" r="2.5" />
            <path d="M8 1v2m0 10v2M1 8h2m10 0h2m-2.5-5L11 4.5m-6 7L3.5 13m9-1.5L11 11.5m-6-7L3.5 3" />
          </svg>
        </button>
      </header>

      {/* ── Main Body (left + right) ── */}
      <div className="app-body">
        {/* ── Left Panel: Controls ── */}
        <aside className="panel-left">
          {/* Financials */}
          {(phase === 'data_ready' ||
            phase === 'running_pipeline' ||
            showDcfResults) && (
            <ErrorBoundary>
              <FinancialsPanel />
            </ErrorBoundary>
          )}

          {/* Pipeline runner */}
          {(phase === 'data_ready' ||
            phase === 'running_pipeline' ||
            showDcfResults) && (
            <ErrorBoundary>
              <PipelineRunner />
            </ErrorBoundary>
          )}

          {/* Assumptions */}
          {showDcfResults && dcfResult && (
            <ErrorBoundary>
              <AssumptionsEditor />
            </ErrorBoundary>
          )}

          {/* Empty state */}
          {phase === 'idle' && (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              flex: 1,
              color: 'var(--text-muted)',
              gap: 'var(--sp-3)',
              textAlign: 'center',
              padding: 'var(--sp-8)',
            }}>
              <svg width="32" height="32" viewBox="0 0 20 20" fill="none" style={{ opacity: 0.4 }}>
                <rect x="1" y="4" width="4" height="12" rx="1" fill="currentColor" />
                <rect x="8" y="2" width="4" height="14" rx="1" fill="currentColor" opacity="0.6" />
                <rect x="15" y="6" width="4" height="10" rx="1" fill="currentColor" opacity="0.35" />
              </svg>
              <span style={{ fontSize: '0.85rem' }}>Enter a ticker to start analysis</span>
            </div>
          )}
        </aside>

        {/* ── Right Panel: Results ── */}
        <main className="panel-right">
          {/* Warnings */}
          <ErrorBoundary>
            <WarningBanner warnings={warnings} />
          </ErrorBoundary>

          {/* DCF Results */}
          {showDcfResults && dcfResult && (
            <>
              <ErrorBoundary>
                <ValuationCard
                  dcfResult={dcfResult}
                  currentPrice={currentPrice}
                />
              </ErrorBoundary>

              <div className="grid-2">
                {sensitivityData && (
                  <ErrorBoundary>
                    <SensitivityHeatmap
                      data={sensitivityGridToHeatmapRows(sensitivityData)}
                      title="Sensitivity Analysis"
                    />
                  </ErrorBoundary>
                )}

                <ErrorBoundary>
                  <WaterfallChart
                    data={dcfResultToWaterfallData(dcfResult)}
                    title="DCF Bridge"
                  />
                </ErrorBoundary>

                <ErrorBoundary>
                  <RevenueEbitdaChart
                    data={dcfResultToRevenueEbitdaData(dcfResult)}
                    title="Revenue & EBITDA"
                  />
                </ErrorBoundary>

                <ErrorBoundary>
                  <MarginTrendChart
                    data={dcfResultToMarginData(dcfResult)}
                    title="Margin Trends"
                  />
                </ErrorBoundary>
              </div>

              <ErrorBoundary>
                <ExportBar />
              </ErrorBoundary>
            </>
          )}

          {/* Empty chart placeholders before pipeline completes */}
          {!showDcfResults && phase !== 'idle' && (
            <div className="grid-2">
              <ChartPlaceholder title="Sensitivity Analysis" />
              <ChartPlaceholder title="DCF Bridge" />
              <ChartPlaceholder title="Revenue & EBITDA" />
              <ChartPlaceholder title="Margin Trends" />
            </div>
          )}

          {/* Right panel idle state */}
          {phase === 'idle' && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flex: 1,
              color: 'var(--text-muted)',
              fontSize: '0.85rem',
            }}>
              Analysis results will appear here
            </div>
          )}
        </main>
      </div>
    </>
  )
}

function ChartPlaceholder({ title }: { title: string }) {
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body" style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 180,
        color: 'var(--text-muted)',
        fontSize: '0.78rem',
      }}>
        Run analysis to see chart
      </div>
    </div>
  )
}
