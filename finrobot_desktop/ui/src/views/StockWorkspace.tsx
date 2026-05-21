// v5 Stock Workspace — the single-page ticker view that replaces the old
// 8-tab layout (spec §3). Mounted at /stocks/:ticker. Owns the ticker-
// scoped pipeline-completion toast (moved here from the retired
// StocksPage so users who scroll away from the progress panel still
// learn when a background run finishes or fails).

import { useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { useRunStreamStore, selectRunByTicker } from '../stores/runStreamStore'
import { useToastStore } from '../stores/toastStore'
import { useAppStore } from '../stores/appStore'
import { TickerHero } from './TickerHero'
import { AnchorNav } from './AnchorNav'
import { PipelineProgressPanel } from './PipelineProgressPanel'
import { HeroVerdict } from './sections/HeroVerdict'
import { DataSnapshot } from './sections/DataSnapshot'
import { CatalystGrid } from './sections/CatalystGrid'
import { RiskGrid } from './sections/RiskGrid'
import { CompositeScoreCard } from './sections/CompositeScoreCard'
import { FootballField } from './sections/FootballField'
import { SensitivityHeatmap } from './sections/SensitivityHeatmap'
import { HistoricalBandChart } from './sections/HistoricalBandChart'
import { MonteCarloSection } from './sections/MonteCarloSection'
import { PriceTrendSection } from './sections/PriceTrendSection'
import { RevenueEbitdaSection } from './sections/RevenueEbitdaSection'
import { MarginsTrendSection } from './sections/MarginsTrendSection'
import { CashFlowSection } from './sections/CashFlowSection'
import { FinancialsSection } from './sections/FinancialsSection'
import { PerformanceSection } from './sections/PerformanceSection'
import { PeersSection } from './sections/PeersSection'
import { PeerRadarSection } from './sections/PeerRadarSection'
import { PeerComparisonBarsSection } from './sections/PeerComparisonBarsSection'
import { SniperLevelsCard } from './sections/SniperLevelsCard'
import { NewsTimeline } from './sections/NewsTimeline'
import { SentimentCard } from './sections/SentimentCard'
import { MyResearchFeed } from './sections/MyResearchFeed'
import EarningsCallPanel from '../components/EarningsCallPanel'

export function StockWorkspace(): React.ReactElement {
  const { ticker } = useParams<{ ticker: string }>()
  const symbol = (ticker || '').toUpperCase()

  // Mirror the URL ticker into appStore so legacy hooks (useHistoricalData /
  // usePerformanceData / PriceChart) that read from the store work when
  // entering via /stocks/:ticker without going through the command palette.
  const setStoreTicker = useAppStore((s) => s.setTicker)
  const storeTicker = useAppStore((s) => s.ticker)
  useEffect(() => {
    if (symbol && storeTicker !== symbol) {
      setStoreTicker(symbol)
    }
  }, [symbol, storeTicker, setStoreTicker])

  // Pipeline completion toast — fires once per runId when status transitions
  // running → completed/failed. Without this, users who scrolled away from
  // PipelineProgressPanel get no feedback when a background analysis finishes.
  const runState = useRunStreamStore(selectRunByTicker(symbol))
  const addToast = useToastStore((s) => s.addToast)
  const lastNotifiedRunIdRef = useRef<string | null>(null)
  useEffect(() => {
    const runId = runState?.runId
    if (!runId) return
    if (lastNotifiedRunIdRef.current === runId) return
    if (runState.status === 'completed') {
      lastNotifiedRunIdRef.current = runId
      addToast({
        type: 'success',
        title: `${symbol} 分析完成`,
        description: '估值 / 同业 / 论点已更新，滚动查看或点「当前判断」锚点跳转',
      })
    } else if (runState.status === 'failed') {
      lastNotifiedRunIdRef.current = runId
      addToast({
        type: 'error',
        title: `${symbol} 分析失败`,
        description: runState.error ?? '请稍后重试',
      })
    }
  }, [runState?.runId, runState?.status, runState?.error, symbol, addToast])

  if (!symbol) {
    return (
      <div style={{ padding: 48, color: 'var(--text-faint)' }}>
        缺少 ticker — 请通过搜索或自选股进入。
      </div>
    )
  }

  return (
    <div data-testid="stock-workspace" style={{ minHeight: '100vh' }}>
      <TickerHero ticker={symbol} />
      <AnchorNav />
      <main
        style={{
          maxWidth: 960,
          margin: '0 auto',
          padding: '12px 24px 96px',
        }}
      >
        <PipelineProgressPanel ticker={symbol} />
        {/* v5 sections in AnchorNav order. The FinRobot equity feature
            parity layer (composite-score / monte-carlo / price-trend /
            revenue / margins / cashflow / peer-radar / peer-bars /
            sniper / news-timeline) wraps existing chart components from
            ui/src/components/charts/ that survived the v5 tab teardown. */}
        <HeroVerdict ticker={symbol} />
        <CompositeScoreCard ticker={symbol} />
        <CatalystGrid ticker={symbol} />
        <RiskGrid ticker={symbol} />
        <FootballField ticker={symbol} />
        <SensitivityHeatmap ticker={symbol} />
        <HistoricalBandChart ticker={symbol} />
        <MonteCarloSection ticker={symbol} />
        <DataSnapshot ticker={symbol} />
        <PriceTrendSection ticker={symbol} />
        <RevenueEbitdaSection ticker={symbol} />
        <MarginsTrendSection ticker={symbol} />
        <CashFlowSection ticker={symbol} />
        <FinancialsSection ticker={symbol} />
        <PerformanceSection ticker={symbol} />
        <PeersSection ticker={symbol} />
        <PeerRadarSection ticker={symbol} />
        <PeerComparisonBarsSection ticker={symbol} />
        <SniperLevelsCard ticker={symbol} />
        <NewsTimeline ticker={symbol} />
        <SentimentCard ticker={symbol} />
        <section id="sec-earnings" style={{ margin: '12px 0' }}>
          <EarningsCallPanel ticker={symbol} />
        </section>
        <MyResearchFeed ticker={symbol} />
      </main>
    </div>
  )
}
