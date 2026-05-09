import { useAppStore } from '../stores/appStore'
import { ErrorBoundary } from '../components/ErrorBoundary'
import TickerInput from '../components/TickerInput'
import WarningBanner from '../components/WarningBanner'
import FinancialsPanel from '../components/FinancialsPanel'
import PipelineRunner from '../components/PipelineRunner'
import AssumptionsEditor from '../components/AssumptionsEditor'
import ValuationCard from '../components/ValuationCard'
import ExportBar from '../components/ExportBar'
import ResearchSummary from '../components/ResearchSummary'
import CompsSummary from '../components/CompsSummary'
import SensitivityHeatmap from '../components/charts/SensitivityHeatmap'
import WaterfallChart from '../components/charts/WaterfallChart'
import RevenueEbitdaChart from '../components/charts/RevenueEbitdaChart'
import MarginTrendChart from '../components/charts/MarginTrendChart'
import PeerComparisonChart from '../components/charts/PeerComparisonChart'
import {
  sensitivityGridToHeatmapRows,
  dcfResultToWaterfallData,
  dcfResultToRevenueEbitdaData,
  dcfResultToMarginData,
  compsResultToPeerChartData,
} from '../utils/chartAdapters'
import type { PipelineType } from '../stores/appStore'

interface Props {
  onOpenSettings: () => void
}

const PIPELINE_OPTIONS: { value: PipelineType; label: string }[] = [
  { value: 'equity_research', label: 'Research' },
  { value: 'dcf', label: 'DCF' },
  { value: 'comps', label: 'Comps' },
]

export default function TickerWorkspace({ onOpenSettings }: Props) {
  const {
    ticker,
    phase,
    pipelineType,
    warnings,
    dcfResult,
    sensitivityData,
    currentPrice,
    researchResult,
    compsResult,
    setPipelineType,
  } = useAppStore()

  const showResults = phase === 'pipeline_done' || phase === 'interactive'
  const showControls = phase === 'data_ready' || phase === 'running_pipeline' || showResults
  const isResearch = pipelineType === 'equity_research'
  const isComps = pipelineType === 'comps'

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
          onClick={() => useAppStore.getState().setView('history')}
          title="Run History"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="8" cy="8" r="6" />
            <path d="M8 4.5V8l2.5 1.5" />
          </svg>
        </button>

        <button
          className="topbar-btn"
          onClick={onOpenSettings}
          title="Settings"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="8" cy="8" r="2.5" />
            <path d="M8 1v2m0 10v2M1 8h2m10 0h2m-2.5-5L11 4.5m-6 7L3.5 13m9-1.5L11 11.5m-6-7L3.5 3" />
          </svg>
        </button>
      </header>

      {/* ── Main Body ── */}
      <div className="app-body">
        {/* ── Left Panel ── */}
        <aside className="panel-left">
          {/* Pipeline type selector */}
          {showControls && (
            <div className="segmented">
              {PIPELINE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  className={`segmented-btn${pipelineType === opt.value ? ' active' : ''}`}
                  onClick={() => setPipelineType(opt.value)}
                  disabled={phase === 'running_pipeline'}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}

          {/* Financials */}
          {showControls && (
            <ErrorBoundary>
              <FinancialsPanel />
            </ErrorBoundary>
          )}

          {/* Pipeline runner */}
          {showControls && (
            <ErrorBoundary>
              <PipelineRunner />
            </ErrorBoundary>
          )}

          {/* DCF Assumptions (only for DCF mode or when equity_research also has DCF data) */}
          {showResults && dcfResult && !isResearch && (
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

        {/* ── Right Panel ── */}
        <main className="panel-right">
          <ErrorBoundary>
            <WarningBanner warnings={warnings} />
          </ErrorBoundary>

          {/* ── Equity Research Results ── */}
          {showResults && isResearch && researchResult && (
            <>
              <ErrorBoundary>
                <ResearchSummary
                  result={researchResult}
                  currentPrice={currentPrice}
                />
              </ErrorBoundary>

              {/* DCF charts from equity research pipeline (if available) */}
              {dcfResult && (
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
              )}
            </>
          )}

          {/* ── Comps Results ── */}
          {showResults && isComps && compsResult && (
            <>
              <ErrorBoundary>
                <CompsSummary
                  result={compsResult}
                  currentPrice={currentPrice}
                />
              </ErrorBoundary>
              <ErrorBoundary>
                <PeerComparisonChart
                  data={compsResultToPeerChartData(compsResult)}
                  title="Peer Multiples Comparison"
                />
              </ErrorBoundary>
            </>
          )}

          {/* ── DCF-Only Results ── */}
          {showResults && !isResearch && !isComps && dcfResult && (
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
          {!showResults && phase !== 'idle' && (
            <div className="grid-2">
              <ChartPlaceholder title={isResearch ? 'Research Summary' : isComps ? 'Comps Table' : 'Valuation'} />
              <ChartPlaceholder title="Sensitivity Analysis" />
              <ChartPlaceholder title="DCF Bridge" />
              <ChartPlaceholder title="Revenue & EBITDA" />
            </div>
          )}

          {/* Idle state */}
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
