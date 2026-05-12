import { useEffect, useState } from 'react'
import { useAppStore } from '../stores/appStore'
import { ErrorBoundary } from '../components/ErrorBoundary'
import TickerInput from '../components/TickerInput'
import WarningBanner from '../components/WarningBanner'
import PipelineRunner from '../components/PipelineRunner'
import AskPanel from '../components/AskPanel'
import StockHeader from '../components/StockHeader'
import TabBar from '../components/TabBar'
import OverviewTab from './OverviewTab'
import FinancialsTab from './FinancialsTab'
import ValuationTab from './ValuationTab'
import PeersTab from './PeersTab'
import CompareView from './CompareView'
import StatusBar from '../components/StatusBar'
import { relativeTime } from '../utils/time'
import type { PipelineType } from '../stores/appStore'

interface Props {
  onOpenSettings: () => void
}

const PRIMARY_PIPELINE = { value: 'research' as PipelineType, label: 'Research' }

const ADVANCED_PIPELINES: { value: PipelineType; label: string }[] = [
  { value: 'dcf', label: 'DCF' },
  { value: 'comps', label: 'Comps' },
  { value: 'lbo', label: 'LBO' },
  { value: 'earnings', label: 'Earnings' },
]

const QUICK_TICKERS = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'META']

export default function TickerWorkspace({ onOpenSettings }: Props) {
  const {
    ticker,
    phase,
    pipelineType,
    warnings,
    currentPrice,
    priceChange,
    priceChangePct,
    dataFetchedAt,
    activeTab,
    setPipelineType,
  } = useAppStore()

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

  const showResults = phase === 'pipeline_done' || phase === 'interactive'
  const isLoading = phase === 'loading_data'
  const showControls = isLoading || phase === 'data_ready' || phase === 'running_pipeline' || showResults

  // (Sliding indicator removed — replaced with two-tier pipeline controls)

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
      case 'compare':
        return <CompareView />
    }
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
          {/* Pipeline type selector — two-tier: primary + advanced */}
          {showControls && (
            <div className="pipeline-controls">
              {/* Primary action */}
              <button
                className={`pipeline-primary${pipelineType === PRIMARY_PIPELINE.value ? ' active' : ''}`}
                onClick={() => setPipelineType(PRIMARY_PIPELINE.value)}
                disabled={phase === 'running_pipeline'}
              >
                {PRIMARY_PIPELINE.label}
              </button>

              {/* Advanced tools */}
              <div className="pipeline-advanced">
                {ADVANCED_PIPELINES.map((opt) => (
                  <button
                    key={opt.value}
                    className={`pipeline-adv-btn${pipelineType === opt.value ? ' active' : ''}`}
                    onClick={() => setPipelineType(opt.value)}
                    disabled={phase === 'running_pipeline'}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Pipeline runner */}
          {showControls && (
            <ErrorBoundary>
              <PipelineRunner />
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
                  <div className="idle-feature-label">5 Pipelines</div>
                  <div className="idle-feature-desc">Research, DCF, Comps, LBO, Earnings + IC Memo from LBO</div>
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
