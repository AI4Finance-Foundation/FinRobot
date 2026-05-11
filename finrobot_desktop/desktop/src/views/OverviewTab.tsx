import { useAppStore } from '../stores/appStore'
import PriceChart from '../components/charts/PriceChart'
import ResearchSummary from '../components/ResearchSummary'

export default function OverviewTab() {
  const ticker = useAppStore((s) => s.ticker)
  const researchResult = useAppStore((s) => s.researchResult)
  const currentPrice = useAppStore((s) => s.currentPrice)

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
    </div>
  )
}
