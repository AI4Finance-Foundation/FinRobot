import { useAppStore } from '../stores/appStore'
import PriceChart from '../components/charts/PriceChart'
import ResearchSummary from '../components/ResearchSummary'
import CatalystPanel from '../components/CatalystPanel'
import NewsFeed from '../components/NewsFeed'
import { useCatalysts } from '../hooks/useCatalysts'

export default function OverviewTab() {
  const ticker = useAppStore((s) => s.ticker)
  const researchResult = useAppStore((s) => s.researchResult)
  const currentPrice = useAppStore((s) => s.currentPrice)
  const catalysts = useAppStore((s) => s.catalysts)
  const catalystsLoading = useAppStore((s) => s.catalystsLoading)

  // Fetch catalysts when ticker changes
  useCatalysts()

  return (
    <div className="tab-content overview-tab">
      <PriceChart title={`${ticker} Price`} />
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
