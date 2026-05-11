import { useAppStore } from '../stores/appStore'
import PriceChart from '../components/charts/PriceChart'
import ResearchSummary from '../components/ResearchSummary'
import WarningBanner from '../components/WarningBanner'

export default function OverviewTab() {
  const ticker = useAppStore((s) => s.ticker)
  const researchResult = useAppStore((s) => s.researchResult)
  const warnings = useAppStore((s) => s.warnings)
  const currentPrice = useAppStore((s) => s.currentPrice)

  return (
    <div className="tab-content overview-tab">
      <PriceChart title={`${ticker} Price`} />
      {warnings.length > 0 && <WarningBanner warnings={warnings} />}
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
