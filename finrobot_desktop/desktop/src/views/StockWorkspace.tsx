// StockWorkspace — single-ticker dashboard at /stocks/:ticker.
//
// Job per CLAUDE.md: "保持 dashboard 形态：实时行情 + 跑 AI 入口 +
// artifact timeline 跳转，不承担研报阅读". The 13-chapter research
// reading lives at /stocks/:ticker/runs/:artifactId (ArtifactDetailPage).
//
// Layout:
//   - Fixed header band — WorkspaceBackBar + TickerHero, pinned (never scrolls)
//   - 2-column scroll region — each column owns its OWN vertical scroll so a long
//     market rail and a tall hot report don't drag each other (the page itself
//     never scrolls). Left = MarketDataZone (live, always present), right =
//     AIZone (cold = big CTA / running = progress + prior report / hot = verdict
//     card + 13-chapter grid + version timeline + standalone/artifacts panels).
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
      style={{
        // Fill the shell's content area exactly (TitleBar + global footer are
        // outside .main-content) and own the overflow ourselves: the PAGE never
        // scrolls — the two columns below scroll independently. Without this the
        // outer .main-content would scroll as one, which is the "left slides a
        // lot, right barely moves" feel the redesign kills.
        height: 'calc(100vh - var(--titlebar-h) - var(--app-footer-h))',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
        zIndex: 1,
      }}
    >
      {/* Fixed header band — back bar + identity hero stay pinned while the
          columns scroll under them (flexShrink:0 keeps them out of the scroll). */}
      <div style={{ flexShrink: 0 }}>
        <WorkspaceBackBar ticker={symbol} />
        <TickerHero ticker={symbol} />
      </div>

      {/* Scroll region — the two columns each own their vertical scroll. */}
      <div
        style={{
          flex: 1,
          minHeight: 0, // critical: lets the grid children actually scroll
          overflow: 'hidden',
          // 1320 (not 1480): on ultra-wide windows a wider split made both
          // columns too wide for the compact data cards. 1320 keeps the
          // dashboard at a Bloomberg-terminal density. Stays in sync with
          // TickerHero's inner box so the glyph aligns with the card edge.
          maxWidth: 1320,
          width: '100%',
          margin: '0 auto',
        }}
      >
        <div
          style={{
            display: 'grid',
            // Market = a fixed ~480px reference RAIL, AI research = flexible and
            // DOMINANT — the design's proportions (AI is the hero column, market a
            // side rail), NOT a 50/50 split. A near-even split starved the report
            // card's verdict|target+gauge|actions row on a 1200px window (the
            // gauge collapsed, the $target overlapped the button); giving AI the
            // rest of the width is what lets the card render at design density.
            gridTemplateColumns: 'minmax(420px, 480px) minmax(0, 1fr)',
            gap: 24,
            height: '100%',
            minHeight: 0,
            alignItems: 'stretch',
          }}
        >
          {/* Semantic split: LEFT = every live market surface (chart, multiples,
              reverse-DCF, financials, catalysts, sentiment — all Non-AI), RIGHT =
              the AI report column. Each column scrolls on its own (overflow-y),
              so a long market rail and a tall hot report no longer drag each
              other — the user's core complaint. The 6px cosmic scrollbar is the
              global default (App.css). */}
          <div
            data-testid="workspace-market-col"
            style={{
              minHeight: 0,
              overflowY: 'auto',
              overflowX: 'hidden',
              // Padding lives inside each scroll column so the scrollbar sits at
              // the window edge, not floating over content.
              padding: '24px 16px 32px 32px',
            }}
          >
            <MarketDataZone ticker={symbol} />
          </div>
          {/* PipelineProgressPanel is rendered inside AIZone — cold / running /
              hot are three states of the same surface. No sticky wrapper now:
              the column scrolls itself. */}
          <div
            data-testid="workspace-ai-col"
            style={{
              minHeight: 0,
              overflowY: 'auto',
              overflowX: 'hidden',
              padding: '24px 32px 32px 16px',
            }}
          >
            <AIZone ticker={symbol} />
          </div>
        </div>
      </div>
    </div>
  )
}
