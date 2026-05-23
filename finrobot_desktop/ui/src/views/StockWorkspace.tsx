// StockWorkspace — single-ticker dashboard at /stocks/:ticker.
//
// Job per CLAUDE.md: "保持 dashboard 形态：实时行情 + 跑 AI 入口 +
// artifact timeline 跳转，不承担研报阅读". The 12-chapter research
// reading lives at /stocks/:ticker/runs/:artifactId (ArtifactDetailPage).
//
// Layout:
//   - TickerHero       — name / price / live overlay / actions
//   - PipelineProgress — in-progress streaming run status (when running)
//   - 2-column grid    — left MarketDataZone (live, always present),
//                        right AIZone (cold = big CTA / hot = artifact
//                        summary + 12-chapter mini-grid + version timeline)
//
// Section contents that constituted the actual research (HeroVerdict /
// FootballField / Sensitivity / Peers / Risks / etc) now live as
// chapters inside ArtifactDetailPage so the workspace serves as a clean
// entry point rather than duplicating the report body.

import { useEffect, useRef } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useRunStreamStore, selectRunByTicker } from '../stores/runStreamStore'
import { useToastStore } from '../stores/toastStore'
import { useAppStore } from '../stores/appStore'
import { useNavMemoryStore } from '../stores/navMemoryStore'
import { TickerHero } from './TickerHero'
import { MarketDataZone } from './workspace/MarketDataZone'
import { AIZone } from './workspace/AIZone'

export function StockWorkspace(): React.ReactElement {
  const { ticker } = useParams<{ ticker: string }>()
  const symbol = (ticker || '').toUpperCase()
  const location = useLocation()

  // Mirror URL ticker into appStore so legacy hooks (useHistoricalData /
  // usePerformanceData / PriceChart) keep working when the user lands
  // directly on /stocks/:ticker without going through ⌘K search.
  const setStoreTicker = useAppStore((s) => s.setTicker)
  const storeTicker = useAppStore((s) => s.ticker)
  useEffect(() => {
    if (symbol && storeTicker !== symbol) {
      setStoreTicker(symbol)
    }
  }, [symbol, storeTicker, setStoreTicker])

  // Remember this path so the sidebar can restore context after the user
  // detours through /settings or any other top-level section.
  const setLastStocksPath = useNavMemoryStore((s) => s.setLastStocksPath)
  useEffect(() => {
    if (symbol) setLastStocksPath(location.pathname)
  }, [location.pathname, symbol, setLastStocksPath])

  // Pipeline completion toast + cache invalidation — fires once per runId
  // when status transitions running → completed / failed. Two jobs:
  //   1. surface a toast so users scrolled away from PipelineProgressPanel
  //      still learn the run finished
  //   2. invalidate the artifact-timeline + latest-artifact queries so the
  //      AI zone re-fetches and flips out of cold state. Without this,
  //      `useV5ArtifactTimeline` (staleTime: Infinity, immutable artifacts)
  //      keeps serving the pre-run snapshot forever.
  const runState = useRunStreamStore(selectRunByTicker(symbol))
  const addToast = useToastStore((s) => s.addToast)
  const queryClient = useQueryClient()
  const lastNotifiedRunIdRef = useRef<string | null>(null)
  useEffect(() => {
    const runId = runState?.runId
    if (!runId) return
    if (lastNotifiedRunIdRef.current === runId) return
    if (runState.status === 'completed') {
      lastNotifiedRunIdRef.current = runId
      // Refetch every read model that an equity_research artifact touches.
      // Artifacts are immutable per-id but the *list* of artifacts for a
      // ticker grows on every run, so the timeline / studied-tickers /
      // recent-research queries must invalidate too.
      // react-query invalidates by key-prefix match, so partial keys cover
      // every limit / window variant. Keys must mirror the hooks exactly:
      //   useV5ArtifactTimeline:      ['v5-artifacts-timeline', ticker]
      //   useStudiedTickers:          ['studied-tickers', limit]
      //   useDashboardHitRate:        ['dashboard', 'hit-rate', window]
      //   useDashboardRecentResearch: ['dashboard', 'recent-research', limit]
      queryClient.invalidateQueries({ queryKey: ['v5-artifacts-timeline', symbol] })
      queryClient.invalidateQueries({ queryKey: ['studied-tickers'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      addToast({
        type: 'success',
        title: `${symbol} 研报完成`,
        description: '完整 12 章研报已生成，点击右侧 AI 区"打开完整研报"查看',
      })
    } else if (runState.status === 'failed') {
      lastNotifiedRunIdRef.current = runId
      addToast({
        type: 'error',
        title: `${symbol} 研报失败`,
        description: runState.error ?? '请稍后重试',
      })
    }
  }, [runState?.runId, runState?.status, runState?.error, symbol, addToast, queryClient])

  if (!symbol) {
    return (
      <div style={{ padding: 48, color: 'var(--text-faint)' }}>
        缺少股票代码，请通过搜索或自选股进入。
      </div>
    )
  }

  return (
    <div
      data-testid="stock-workspace"
      style={{ minHeight: '100vh', position: 'relative', zIndex: 1 }}
    >
      <TickerHero ticker={symbol} />
      <main
        style={{
          maxWidth: 1480,
          margin: '0 auto',
          padding: '24px 32px 96px',
        }}
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 24,
            alignItems: 'start',
          }}
        >
          <MarketDataZone ticker={symbol} />
          {/* PipelineProgressPanel is rendered inside AIZone — it shares
              the AI column's visual real estate (cold / running / hot are
              three states of the same surface) instead of stacking on
              top of MarketDataZone where it stole vertical room. */}
          <AIZone ticker={symbol} />
        </div>
      </main>
    </div>
  )
}
