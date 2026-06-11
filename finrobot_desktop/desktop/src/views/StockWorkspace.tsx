// StockWorkspace — single-ticker dashboard at /stocks/:ticker.
//
// Job per CLAUDE.md: "保持 dashboard 形态：实时行情 + 跑 AI 入口 +
// artifact timeline 跳转，不承担研报阅读". The 13-chapter research
// reading lives at /stocks/:ticker/runs/:artifactId (ArtifactDetailPage).
//
// Layout:
//   - TickerHero       — name / price / live overlay / actions
//   - PipelineProgress — in-progress streaming run status (when running)
//   - 2-column grid    — left MarketDataZone (live, always present),
//                        right AIZone (cold = big CTA / hot = artifact
//                        summary + 13-chapter mini-grid + version timeline)
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
import { useNavMemoryStore } from '../stores/navMemoryStore'
import { useTickerPrice } from '../hooks/useTickerData'
import { useAddStudiedTicker } from '../hooks/useCoverage'
import { FetchHttpError, mapErrorToUserMessage } from '../utils/errorMessage'
import { TickerNotFoundView } from './workspace/TickerNotFoundView'
import { WorkspaceBackBar } from './workspace/WorkspaceBackBar'
import { TickerHero } from './TickerHero'
import { MarketDataZone } from './workspace/MarketDataZone'
import { AIZone } from './workspace/AIZone'
import { useI18n } from '../i18n'

export function StockWorkspace(): React.ReactElement {
  const { ticker } = useParams<{ ticker: string }>()
  const symbol = (ticker || '').toUpperCase()
  const location = useLocation()
  const { t } = useI18n()

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
  const markTerminalNotified = useRunStreamStore((s) => s.markTerminalNotified)
  const addToast = useToastStore((s) => s.addToast)
  const queryClient = useQueryClient()
  useEffect(() => {
    const runId = runState?.runId
    if (!runId) return
    // Dedupe at the STORE level, not via a component ref: this view is
    // route-mounted, so a useRef resets on every navigate-away/back and would
    // re-fire the toast + invalidations against the still-resident completed
    // run (BUG-085). markTerminalNotified returns true once per runId, ever.
    if (
      runState.status !== 'completed' &&
      runState.status !== 'failed' &&
      runState.status !== 'cancelled'
    )
      return
    if (!markTerminalNotified(runId)) return
    if (runState.status === 'completed') {
      // Refetch every read model that an equity_research artifact touches.
      // Artifacts are immutable per-id but the *list* of artifacts for a
      // ticker grows on every run, so the timeline query must invalidate too.
      // react-query invalidates by key-prefix match, so the partial key covers
      // every limit variant. Key must mirror the hook exactly:
      //   useV5ArtifactTimeline:      ['v5-artifacts-timeline', ticker]
      queryClient.invalidateQueries({ queryKey: ['v5-artifacts-timeline', symbol] })
      addToast({
        type: 'success',
        title: t('workspace.toast.reportDone', { ticker: symbol }),
        description: t('workspace.toast.reportDoneDesc'),
      })
    } else if (runState.status === 'cancelled') {
      // User-requested stop: neutral info, not an error — nothing to retry,
      // nothing to diagnose.
      addToast({
        type: 'info',
        title: t('workspace.toast.reportCancelled', { ticker: symbol }),
      })
    } else if (runState.status === 'failed') {
      // runState.error is the raw SSE `run.failed` payload (or our SSE-dropout
      // message) — route it through mapErrorToUserMessage so a leaked "HTTP
      // 500" / dev string becomes friendly copy (BUG-027). Pre-localised
      // messages (Chinese sentences) pass through untouched.
      addToast({
        type: 'error',
        title: t('workspace.toast.reportFailed', { ticker: symbol }),
        description: runState.error
          ? mapErrorToUserMessage(new Error(runState.error))
          : t('workspace.toast.retryLater'),
      })
    }
  }, [
    runState?.runId,
    runState?.status,
    runState?.error,
    symbol,
    addToast,
    markTerminalNotified,
    queryClient,
    t,
  ])

  // Gate: validate ticker via useTickerPrice before rendering the workspace
  // shell. Status code is the protocol; UI never matches on Chinese detail.
  //
  //   FetchHttpError 422 → TickerNotFoundView (invalid ticker, no retry value)
  //   anything else → render the workspace shell and let market-data widgets
  //   show their local degraded state. A yfinance outage must not hide the
  //   AI run/timeline column while a pipeline is still progressing.
  //
  // Called unconditionally (Rules of Hooks) — enabled: !!symbol suppresses
  // the fetch when the URL param is absent (same guard as TickerHero /
  // MarketDataZone). React Query deduplicates the three callers (this hook
  // + TickerHero + MarketDataZone) to a single network request.
  //
  // isLoading is intentionally NOT intercepted: TickerHero and MarketDataZone
  // render their own skeleton states, so a gate-level loading guard would
  // produce a double spinner.
  const priceQuery = useTickerPrice(symbol)

  // Auto-enrol an opened ticker into the default Studied Tickers workspace
  // (Coverage redesign §2). Gated on the ticker being ACCEPTED — the exact same
  // condition that renders the workspace below: anything except a 422
  // (invalid-ticker) counts. Gating on price *success* alone dropped valid names
  // during a provider outage (non-422 error): the user could open the page and
  // run research, yet the name never entered Studied Tickers, so "跑过的东西"
  // couldn't be found in the workspace. Idempotent server-side; the ref fires it
  // once per symbol so a re-render / live re-poll doesn't re-POST. Best-effort
  // onboarding — failures stay silent (no toast), the workspace never depends on it.
  const addStudied = useAddStudiedTicker()
  const lastStudiedRef = useRef<string | null>(null)
  const accepted =
    priceQuery.isSuccess ||
    (priceQuery.isError &&
      !(priceQuery.error instanceof FetchHttpError && priceQuery.error.status === 422))
  useEffect(() => {
    if (!symbol || !accepted) return
    if (lastStudiedRef.current === symbol) return
    lastStudiedRef.current = symbol
    addStudied.mutate(symbol)
  }, [symbol, accepted, addStudied])

  if (!symbol) {
    return (
      <div style={{ padding: 48, color: 'var(--text-faint)' }}>{t('workspace.missingTicker')}</div>
    )
  }

  const priceErrorStatus =
    priceQuery.isError && priceQuery.error instanceof FetchHttpError
      ? priceQuery.error.status
      : null
  if (priceErrorStatus === 422) return <TickerNotFoundView ticker={symbol} />

  return (
    <div
      data-testid="stock-workspace"
      style={{ minHeight: '100vh', position: 'relative', zIndex: 1 }}
    >
      <WorkspaceBackBar ticker={symbol} />
      <TickerHero ticker={symbol} />
      <main
        style={{
          // 1320 (not 1480): on ultra-wide windows a 50/50 split at 1480 made
          // both columns ~700px — wider than the compact data cards need.
          // 1320 keeps the dashboard at a Bloomberg-terminal density. Must stay
          // in sync with TickerHero's inner box so the ticker glyph's left edge
          // aligns with the MarketDataZone card edge.
          maxWidth: 1320,
          margin: '0 auto',
          padding: '24px 32px 96px',
        }}
      >
        <div
          style={{
            display: 'grid',
            // Right (AI) column weighted wider: its verdict badge + target row
            // and 3-col chapter grid are width-hungry, while the left data
            // column's Kv4 cards read fine narrower.
            gridTemplateColumns: '1fr 1.15fr',
            gap: 24,
            alignItems: 'start',
          }}
        >
          {/* Semantic split: LEFT = every live market surface (quote, chart,
              financials, catalysts, sentiment — all Non-AI), RIGHT = the AI
              report column. The right column is sticky so when the longer
              market rail scrolls, the report stays in view instead of leaving
              trailing whitespace (it only pins while shorter than the
              viewport — the hot multi-chapter state simply scrolls). */}
          <MarketDataZone ticker={symbol} />
          {/* PipelineProgressPanel is rendered inside AIZone — it shares
              the AI column's visual real estate (cold / running / hot are
              three states of the same surface) instead of stacking on
              top of MarketDataZone where it stole vertical room. */}
          <div style={{ position: 'sticky', top: 24 }}>
            <AIZone ticker={symbol} />
          </div>
        </div>
      </main>
    </div>
  )
}
