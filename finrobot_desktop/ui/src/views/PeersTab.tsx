import { useMemo } from 'react'
import { useAppStore } from '../stores/appStore'
import { usePerformanceData } from '../hooks/usePerformanceData'
import { useRunTool } from '../hooks/useRunTool'
import { useStocksStore } from '../stores/stocksStore'
import CompsSummary from '../components/CompsSummary'
import { CompanyRadarChart, PeerComparisonChart, RelativePerformanceChart } from '../components/charts'
import { compsResultToPeerChartData, compsResultToRadarData } from '../utils/chartAdapters'
import { extractNarrativeSection } from '../utils/narrativeParser'
import { useI18n } from '../i18n'

export default function PeersTab() {
  const compsResult = useAppStore((s) => s.compsResult)
  const researchResult = useAppStore((s) => s.researchResult)
  const performanceData = useAppStore((s) => s.performanceData)
  const currentPrice = useAppStore((s) => s.currentPrice)
  const ticker = useStocksStore((s) => s.currentTicker)
  const { t } = useI18n()
  const { mutate, isPending } = useRunTool({ ticker })

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
        <EmptyCta
          label={t('peers.empty')}
          cta={t('peers.cta')}
          loading={isPending}
          loadingLabel={t('common.loading')}
          onClick={() => mutate('comps')}
        />
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

interface EmptyCtaProps {
  label: string
  cta: string
  loading: boolean
  loadingLabel: string
  onClick: () => void
}

function EmptyCta({ label, cta, loading, loadingLabel, onClick }: EmptyCtaProps) {
  return (
    <div
      className="empty-state-card"
      style={{ display: 'flex', flexDirection: 'column', gap: 12, alignItems: 'center' }}
    >
      <p style={{ color: 'var(--text-secondary)' }}>{label}</p>
      <button
        onClick={onClick}
        disabled={loading}
        className="btn"
        style={{
          padding: '6px 16px',
          fontSize: '0.85rem',
          background: loading ? 'var(--border)' : 'var(--gold-dim)',
          color: 'var(--gold)',
          border: '1px solid var(--gold)',
          borderRadius: 4,
          cursor: loading ? 'wait' : 'pointer',
          opacity: loading ? 0.6 : 1,
        }}
      >
        {loading ? loadingLabel : cta}
      </button>
    </div>
  )
}
