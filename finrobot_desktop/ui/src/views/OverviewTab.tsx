import { useState } from 'react'
import { useAppStore } from '../stores/appStore'
import PriceChart from '../components/charts/PriceChart'
import TechnicalAnalysisView from '../components/charts/TechnicalAnalysisView'
import ResearchSummary from '../components/ResearchSummary'
import CatalystPanel from '../components/CatalystPanel'
import NewsFeed from '../components/NewsFeed'
import { useCatalysts } from '../hooks/useCatalysts'

type ChartMode = 'simple' | 'technical'

export default function OverviewTab() {
  const ticker = useAppStore((s) => s.ticker)
  const researchResult = useAppStore((s) => s.researchResult)
  const currentPrice = useAppStore((s) => s.currentPrice)
  const catalysts = useAppStore((s) => s.catalysts)
  const catalystsLoading = useAppStore((s) => s.catalystsLoading)

  const [chartMode, setChartMode] = useState<ChartMode>('simple')

  // Fetch catalysts when ticker changes
  useCatalysts()

  return (
    <div className="tab-content overview-tab">
      {/* Chart mode toggle + price chart */}
      <div>
        <div className="chart-mode-toggle">
          <button
            className={`chart-mode-btn${chartMode === 'simple' ? ' active' : ''}`}
            onClick={() => setChartMode('simple')}
          >
            Simple
          </button>
          <button
            className={`chart-mode-btn${chartMode === 'technical' ? ' active' : ''}`}
            onClick={() => setChartMode('technical')}
          >
            Technical
          </button>
        </div>
        {chartMode === 'simple' ? (
          <PriceChart title={`${ticker} Price`} />
        ) : (
          <TechnicalAnalysisView />
        )}
      </div>
      {researchResult ? (
        <ResearchSummary result={researchResult} currentPrice={currentPrice} />
      ) : (
        <div className="empty-state-card">
          <p>Run Research analysis to view investment thesis</p>
        </div>
      )}
      {ticker && (
        <CatalystPanel
          catalysts={catalysts ?? []}
          loading={catalystsLoading}
        />
      )}
      {ticker && <NewsFeed />}
    </div>
  )
}
