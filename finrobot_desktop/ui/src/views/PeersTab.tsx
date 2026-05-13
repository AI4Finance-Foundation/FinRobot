import { useMemo } from 'react'
import { useAppStore } from '../stores/appStore'
import { usePerformanceData } from '../hooks/usePerformanceData'
import CompsSummary from '../components/CompsSummary'
import { CompanyRadarChart, PeerComparisonChart, RelativePerformanceChart } from '../components/charts'
import { compsResultToPeerChartData, compsResultToRadarData } from '../utils/chartAdapters'
import { extractNarrativeSection } from '../utils/narrativeParser'

export default function PeersTab() {
  const compsResult = useAppStore((s) => s.compsResult)
  const researchResult = useAppStore((s) => s.researchResult)
  const performanceData = useAppStore((s) => s.performanceData)
  const currentPrice = useAppStore((s) => s.currentPrice)

  const peerTickers = useMemo(
    () => compsResult?.peers?.map((p: { ticker: string }) => p.ticker) ?? [],
    [compsResult]
  )

  usePerformanceData(peerTickers)

  return (
    <div className="tab-content peers-tab">
      {compsResult ? (
        <CompsSummary result={compsResult} currentPrice={currentPrice} />
      ) : (
        <div className="empty-state-card">
          <p>Run Comps Analysis to view peer comparison</p>
        </div>
      )}

      {compsResult && (
        <div className="chart-grid-2col">
          <CompanyRadarChart data={compsResultToRadarData(compsResult)} title="Financial Profile" />
          <PeerComparisonChart data={compsResultToPeerChartData(compsResult)} title="Peer Multiples" />
        </div>
      )}

      {performanceData && (
        <RelativePerformanceChart data={performanceData} title="Relative Performance (normalized to 100)" />
      )}

      {researchResult?.narrative && (
        <CompetitorNarrative narrative={researchResult.narrative} />
      )}
    </div>
  )
}

function CompetitorNarrative({ narrative }: { narrative: string }) {
  const content = extractNarrativeSection(narrative, ['competitive', 'competitor', 'peer', 'positioning', 'market position'])
  if (!content) return null
  return (
    <details className="insight-block">
      <summary className="insight-title">Competitive Analysis</summary>
      <div className="insight-content">{content}</div>
    </details>
  )
}
