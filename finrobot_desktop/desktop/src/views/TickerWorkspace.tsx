import { useRef, useEffect, useCallback, useState } from 'react'
import { useAppStore } from '../stores/appStore'
import { useMonteCarloCompute } from '../hooks/useCompute'
import { ErrorBoundary } from '../components/ErrorBoundary'
import TickerInput from '../components/TickerInput'
import WarningBanner from '../components/WarningBanner'
import FinancialsPanel from '../components/FinancialsPanel'
import PipelineRunner from '../components/PipelineRunner'
import AssumptionsEditor from '../components/AssumptionsEditor'
import ValuationCard from '../components/ValuationCard'
import ScenarioCompare from '../components/ScenarioCompare'
import AskPanel from '../components/AskPanel'
import ExportBar from '../components/ExportBar'
import StockOverview from '../components/StockOverview'
import StockHeader from '../components/StockHeader'
import TabBar from '../components/TabBar'
import OverviewTab from './OverviewTab'
import FinancialsTab from './FinancialsTab'
import ValuationTab from './ValuationTab'
import PeersTab from './PeersTab'
import ResearchSummary from '../components/ResearchSummary'
import CompsSummary from '../components/CompsSummary'
import EarningsSummary from '../components/EarningsSummary'
import LBOSummary from '../components/LBOSummary'
import ICMemoSummary from '../components/ICMemoSummary'
import SensitivityHeatmap from '../components/charts/SensitivityHeatmap'
import WaterfallChart from '../components/charts/WaterfallChart'
import RevenueEbitdaChart from '../components/charts/RevenueEbitdaChart'
import MarginTrendChart from '../components/charts/MarginTrendChart'
import PeerComparisonChart from '../components/charts/PeerComparisonChart'
import FootballField from '../components/charts/FootballField'
import CompanyRadarChart from '../components/charts/CompanyRadarChart'
import MonteCarloChart from '../components/charts/MonteCarloChart'
import StatusBar from '../components/StatusBar'
import {
  sensitivityGridToHeatmapRows,
  dcfResultToWaterfallData,
  dcfResultToRevenueEbitdaData,
  dcfResultToMarginData,
  compsResultToPeerChartData,
  compsResultToRadarData,
  dcfSensitivityToFootballData,
} from '../utils/chartAdapters'
import { relativeTime } from '../utils/time'
import type { PipelineType } from '../stores/appStore'

interface Props {
  onOpenSettings: () => void
}

const PIPELINE_OPTIONS: { value: PipelineType; label: string }[] = [
  { value: 'research', label: 'Research' },
  { value: 'dcf', label: 'DCF' },
  { value: 'comps', label: 'Comps' },
  { value: 'earnings', label: 'Earnings' },
  { value: 'lbo', label: 'LBO' },
  { value: 'ic-memo', label: 'IC Memo' },
]

const QUICK_TICKERS = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'META']

export default function TickerWorkspace({ onOpenSettings }: Props) {
  const {
    ticker,
    phase,
    pipelineType,
    warnings,
    dcfInputs,
    dcfResult,
    sensitivityData,
    currentPrice,
    priceChange,
    priceChangePct,
    dataFetchedAt,
    researchResult,
    compsResult,
    earningsResult,
    lboResult,
    icMemoResult,
    monteCarloResult,
    monteCarloLoading,
    scenarioResults,
    activeTab,
    setPipelineType,
    setMonteCarloResult,
    setMonteCarloLoading,
  } = useAppStore()

  const monteCarlo = useMonteCarloCompute()

  // Refresh relative time display every 30s
  const [, setTimeTick] = useState(0)
  useEffect(() => {
    if (!dataFetchedAt) return
    const id = setInterval(() => setTimeTick((t) => t + 1), 30_000)
    return () => clearInterval(id)
  }, [dataFetchedAt])

  const handleQuickTicker = (t: string) => {
    const store = useAppStore.getState()
    store.setTicker(t)
    store.setPhase('loading_data')
  }

  const handleRunMonteCarlo = () => {
    if (!dcfInputs || !currentPrice) return
    setMonteCarloLoading(true)
    setMonteCarloResult(null)
    monteCarlo.mutate(
      { inputs: dcfInputs, current_price: currentPrice },
      {
        onSuccess: (data) => {
          setMonteCarloResult(data)
          setMonteCarloLoading(false)
        },
        onError: () => {
          setMonteCarloLoading(false)
        },
      },
    )
  }

  const showResults = phase === 'pipeline_done' || phase === 'interactive'
  const isLoading = phase === 'loading_data'
  const showControls = isLoading || phase === 'data_ready' || phase === 'running_pipeline' || showResults
  const isResearch = pipelineType === 'research'
  const isDcf = pipelineType === 'dcf'
  const isComps = pipelineType === 'comps'
  const isEarnings = pipelineType === 'earnings'
  const isLbo = pipelineType === 'lbo'
  const isIcMemo = pipelineType === 'ic-memo'

  // Does the currently selected pipeline type have results to show?
  const hasCurrentResults = showResults && (
    (isResearch && researchResult != null) ||
    (isComps && compsResult != null) ||
    (isEarnings && earningsResult != null) ||
    (isLbo && lboResult != null) ||
    (isIcMemo && icMemoResult != null) ||
    (isDcf && dcfResult != null)
  )

  // Show scenario compare in DCF mode when at least 2 scenarios computed
  const showScenarioCompare = isDcf && hasCurrentResults && (() => {
    const filled = (['bull', 'base', 'bear'] as const).filter(k => scenarioResults[k] !== null)
    return filled.length >= 2
  })()

  // ── Sliding indicator for segmented control ──
  const segmentedRef = useRef<HTMLDivElement>(null)
  const indicatorRef = useRef<HTMLDivElement>(null)

  const updateIndicator = useCallback(() => {
    const container = segmentedRef.current
    const indicator = indicatorRef.current
    if (!container || !indicator) return
    const activeBtn = container.querySelector('.segmented-btn.active') as HTMLElement | null
    if (!activeBtn) return
    indicator.style.width = `${activeBtn.offsetWidth}px`
    indicator.style.transform = `translateX(${activeBtn.offsetLeft - 2}px)`
  }, [])

  useEffect(() => {
    updateIndicator()
  }, [pipelineType, updateIndicator])

  // ── Right panel content based on active tab ──
  const renderTabContent = () => {
    switch (activeTab) {
      case 'overview':
        return <OverviewTab />
      case 'financials':
        return <FinancialsTab />
      case 'valuation':
        return <ValuationTab />
      case 'peers':
        return <PeersTab />
    }
  }

  // ── Pipeline result rendering (temporary — will migrate to tabs in Tasks 8-12) ──
  const renderPipelineResults = () => {
    if (!hasCurrentResults) return null

    return (
      <>
        {/* ── Equity Research Results ── */}
        {isResearch && researchResult && (
          <>
            <div style={{ '--stagger': 0 } as React.CSSProperties}>
              <ErrorBoundary>
                <ResearchSummary
                  result={researchResult}
                  currentPrice={currentPrice}
                />
              </ErrorBoundary>
            </div>

            {/* Valuation football field (full-width) */}
            {dcfResult && sensitivityData && (
              <div style={{ '--stagger': 1 } as React.CSSProperties}>
                <ErrorBoundary>
                  <FootballField
                    data={dcfSensitivityToFootballData(dcfResult, sensitivityData)}
                    title="Valuation Range"
                    currentPrice={currentPrice}
                  />
                </ErrorBoundary>
              </div>
            )}

            {/* DCF charts from equity research pipeline (if available) */}
            {dcfResult && (
              <div className="grid-2" style={{ '--stagger': 2 } as React.CSSProperties}>
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
        {isComps && compsResult && (
          <>
            <div style={{ '--stagger': 0 } as React.CSSProperties}>
              <ErrorBoundary>
                <CompsSummary
                  result={compsResult}
                  currentPrice={currentPrice}
                />
              </ErrorBoundary>
            </div>
            <div className="grid-2" style={{ '--stagger': 2 } as React.CSSProperties}>
              <ErrorBoundary>
                <PeerComparisonChart
                  data={compsResultToPeerChartData(compsResult)}
                  title="Peer Multiples Comparison"
                />
              </ErrorBoundary>
              <ErrorBoundary>
                <CompanyRadarChart
                  data={compsResultToRadarData(compsResult)}
                  title="Financial Profile vs Peers"
                />
              </ErrorBoundary>
            </div>
          </>
        )}

        {/* ── Earnings Results ── */}
        {isEarnings && earningsResult && (
          <div style={{ '--stagger': 0 } as React.CSSProperties}>
            <ErrorBoundary>
              <EarningsSummary result={earningsResult} />
            </ErrorBoundary>
          </div>
        )}

        {/* ── LBO Results ── */}
        {isLbo && lboResult && (
          <div style={{ '--stagger': 0 } as React.CSSProperties}>
            <ErrorBoundary>
              <LBOSummary result={lboResult} />
            </ErrorBoundary>
          </div>
        )}

        {/* ── IC Memo Results ── */}
        {isIcMemo && icMemoResult && (
          <div style={{ '--stagger': 0 } as React.CSSProperties}>
            <ErrorBoundary>
              <ICMemoSummary result={icMemoResult} />
            </ErrorBoundary>
          </div>
        )}

        {/* ── DCF-Only Results ── */}
        {isDcf && dcfResult && (
          <>
            <div style={{ '--stagger': 0 } as React.CSSProperties}>
              <ErrorBoundary>
                <ValuationCard
                  dcfResult={dcfResult}
                  currentPrice={currentPrice}
                />
              </ErrorBoundary>
            </div>

            {/* Scenario comparison (between valuation card and charts) */}
            {showScenarioCompare && (
              <div style={{ '--stagger': 1 } as React.CSSProperties}>
                <ErrorBoundary>
                  <ScenarioCompare />
                </ErrorBoundary>
              </div>
            )}

            {/* Valuation football field (full-width) */}
            {sensitivityData && (
              <div style={{ '--stagger': 2 } as React.CSSProperties}>
                <ErrorBoundary>
                  <FootballField
                    data={dcfSensitivityToFootballData(dcfResult, sensitivityData)}
                    title="Valuation Range"
                    currentPrice={currentPrice}
                  />
                </ErrorBoundary>
              </div>
            )}

            <div className="grid-2" style={{ '--stagger': 3 } as React.CSSProperties}>
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

            {/* Monte Carlo Simulation */}
            <div style={{ '--stagger': 4 } as React.CSSProperties}>
              {!monteCarloResult && (
                <div className="card animate-in" style={{ textAlign: 'center', padding: 'var(--sp-4)' }}>
                  <button
                    className="mc-run-btn"
                    style={{ margin: '0 auto' }}
                    onClick={handleRunMonteCarlo}
                    disabled={monteCarloLoading || !dcfInputs}
                  >
                    {monteCarloLoading ? (
                      <>
                        <span className="spinner" />
                        Running 10,000 simulations...
                      </>
                    ) : (
                      <>
                        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                          <path d="M1 10l3-4 3 2 4-5M13 10l-3-4-3 2-4-5" opacity="0.4" />
                          <path d="M1 12h12" />
                        </svg>
                        Run Monte Carlo (10K DCF Simulations)
                      </>
                    )}
                  </button>
                </div>
              )}
              {monteCarloResult && (
                <ErrorBoundary>
                  <MonteCarloChart result={monteCarloResult} currentPrice={currentPrice} />
                </ErrorBoundary>
              )}
            </div>

            <div style={{ '--stagger': 5 } as React.CSSProperties}>
              <ErrorBoundary>
                <ExportBar />
              </ErrorBoundary>
            </div>
          </>
        )}
      </>
    )
  }

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
              {priceChange != null && priceChangePct != null && (
                <span className={`ticker-change${priceChange >= 0 ? ' positive' : ' negative'}`}>
                  {priceChange >= 0 ? '+' : ''}{priceChange.toFixed(2)} ({priceChange >= 0 ? '+' : ''}{priceChangePct.toFixed(2)}%)
                </span>
              )}
              {dataFetchedAt && (
                <span
                  className="data-freshness"
                  title={new Date(dataFetchedAt).toLocaleString()}
                >
                  {relativeTime(dataFetchedAt)}
                </span>
              )}
            </div>
          </>
        )}

        <div className="topbar-spacer" />

        <button
          className="cmd-trigger"
          onClick={() => useAppStore.getState().toggleCmdPalette()}
          title="Command Palette (⌘K)"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3">
            <circle cx="6" cy="6" r="4" />
            <path d="M9.5 9.5L12.5 12.5" />
          </svg>
          <span className="cmd-trigger-label">⌘K</span>
        </button>

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
            <div className="segmented" ref={segmentedRef}>
              <div className="segmented-indicator" ref={indicatorRef} />
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

          {/* DCF Assumptions (only for DCF mode) */}
          {showResults && dcfResult && !isResearch && !isLbo && !isIcMemo && (
            <ErrorBoundary>
              <AssumptionsEditor />
            </ErrorBoundary>
          )}

          {/* Idle state — left panel */}
          {phase === 'idle' && (
            <div className="idle-left animate-in">
              <div className="idle-brand">
                <svg width="36" height="36" viewBox="0 0 20 20" fill="none">
                  <rect x="1" y="4" width="4" height="12" rx="1" fill="var(--gold)" />
                  <rect x="8" y="2" width="4" height="14" rx="1" fill="var(--gold)" opacity="0.6" />
                  <rect x="15" y="6" width="4" height="10" rx="1" fill="var(--gold)" opacity="0.35" />
                </svg>
                <div className="idle-tagline">AI Investment Research</div>
              </div>

              <div className="idle-section">
                <div className="section-label">Quick Start</div>
                <div className="idle-ticker-grid">
                  {QUICK_TICKERS.map((t) => (
                    <button
                      key={t}
                      className="idle-ticker-btn"
                      onClick={() => handleQuickTicker(t)}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>

              <div className="idle-section">
                <div className="section-label">Keyboard</div>
                <div className="idle-shortcuts">
                  <div className="idle-shortcut">
                    <kbd className="idle-kbd">⌘K</kbd>
                    <span>Command Palette</span>
                  </div>
                  <div className="idle-shortcut">
                    <kbd className="idle-kbd">↵</kbd>
                    <span>Load Ticker</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </aside>

        {/* ── Right Panel ── */}
        <main className="panel-right">
          <ErrorBoundary>
            <WarningBanner warnings={warnings} />
          </ErrorBoundary>

          {/* ── Tab system: StockHeader + TabBar + tab content (when not idle) ── */}
          {phase !== 'idle' && (
            <>
              <StockHeader />
              {showControls && <TabBar />}
              <div className="tab-panel">
                {renderTabContent()}
              </div>
            </>
          )}

          {/* ── Pipeline results (transitional — will move to tabs in Tasks 8-12) ── */}
          {renderPipelineResults()}

          {/* Stock overview: before pipeline completes, or when switching to an un-run pipeline */}
          {phase !== 'idle' && !hasCurrentResults && (
            <>
              <ErrorBoundary>
                <StockOverview />
              </ErrorBoundary>
              {showResults && (
                <div className="card animate-in" style={{
                  textAlign: 'center',
                  padding: 'var(--sp-5)',
                  color: 'var(--text-muted)',
                  fontSize: '0.82rem',
                  borderStyle: 'dashed',
                }}>
                  Click <strong style={{ color: 'var(--text-secondary)' }}>Run</strong> to generate{' '}
                  <strong style={{ color: 'var(--text-secondary)' }}>
                    {PIPELINE_OPTIONS.find(o => o.value === pipelineType)?.label ?? pipelineType}
                  </strong>{' '}
                  analysis
                </div>
              )}
            </>
          )}

          {/* Ask Panel — collapsible at bottom, visible when ticker loaded */}
          {phase !== 'idle' && ticker && (
            <ErrorBoundary>
              <AskPanel />
            </ErrorBoundary>
          )}

          {/* Idle state — right panel */}
          {phase === 'idle' && (
            <div className="idle-right animate-in">
              <div className="idle-watermark">
                <svg width="72" height="72" viewBox="0 0 20 20" fill="none">
                  <rect x="1" y="4" width="4" height="12" rx="1" fill="var(--gold)" opacity="0.12" />
                  <rect x="8" y="2" width="4" height="14" rx="1" fill="var(--gold)" opacity="0.08" />
                  <rect x="15" y="6" width="4" height="10" rx="1" fill="var(--gold)" opacity="0.05" />
                </svg>
              </div>
              <div className="idle-hero-text">
                <div className="idle-hero-label">Investment Research Workstation</div>
                <p className="idle-hero-desc">
                  Type a ticker to start, or press{' '}
                  <kbd className="idle-kbd">⌘K</kbd> to search.
                </p>
              </div>
              <div className="idle-features">
                <div className="idle-feature">
                  <svg className="idle-feature-icon" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="var(--gold)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="2,14 6,9 10,11 16,4" />
                    <polyline points="12,4 16,4 16,8" />
                  </svg>
                  <div className="idle-feature-label">6 Pipelines</div>
                  <div className="idle-feature-desc">Research, DCF, Comps, Earnings, LBO, IC Memo</div>
                </div>
                <div className="idle-feature">
                  <svg className="idle-feature-icon" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="var(--gold)" strokeWidth="1.3" strokeLinecap="round">
                    <path d="M6 2C4 2 3 3 3 5v3c0 1-1 1-1 1s1 0 1 1v3c0 2 1 3 3 3" />
                    <path d="M12 2c2 0 3 1 3 3v3c0 1 1 1 1 1s-1 0-1 1v3c0 2-1 3-3 3" />
                  </svg>
                  <div className="idle-feature-label">Deterministic Math</div>
                  <div className="idle-feature-desc">WACC, DCF, IRR, MOIC — no LLM guessing</div>
                </div>
                <div className="idle-feature">
                  <svg className="idle-feature-icon" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="var(--gold)" strokeWidth="1.3">
                    <ellipse cx="9" cy="4.5" rx="6" ry="2.5" />
                    <path d="M3 4.5v4c0 1.38 2.69 2.5 6 2.5s6-1.12 6-2.5v-4" />
                    <path d="M3 8.5v4c0 1.38 2.69 2.5 6 2.5s6-1.12 6-2.5v-4" />
                  </svg>
                  <div className="idle-feature-label">Multi-Source Data</div>
                  <div className="idle-feature-desc">FMP, Finnhub, SEC EDGAR with cross-validation</div>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>

      <StatusBar />
    </>
  )
}
