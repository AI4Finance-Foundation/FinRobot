// CoveragePage — the desktop's first screen (route `/coverage`). The analyst's
// research desk: a hero search (drill into one name + auto-enrol on open), a
// slim wall header (triage lens + sort), a wall of ticker cards, and a right
// Inspector scoped to the focused ticker. There is ONE list — Studied Tickers
// (the system coverage group) — surfaced; the multi-group machinery stays in the
// backend but is not exposed (no switcher / rename / import chrome). Server
// state via useCoverage; view-state (selection, focus, sort) in coverageStore.
//
// A ticker is the primary object: a live market snapshot AND many research
// artifacts. The card shows the snapshot + latest verdict + report count; the
// inspector splits Market from the Latest Research Artifact (at-run price frozen)
// and lists the full artifact history. Remove drops list membership, never
// artifacts. Landing view = Needs Action — the triage queue IS the homepage.

import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useI18n } from '../i18n'
import { useCoverageStore } from '../stores/coverageStore'
import { useRunStreamStore } from '../stores/runStreamStore'
import {
  useAddMembers,
  useBatchRun,
  useCoverageGroups,
  useCoverageOverview,
  useCreateGroup,
  useRemoveMember,
} from '../hooks/useCoverage'
import { CoverageEmptyState } from '../components/coverage/CoverageEmptyState'
import { CoverageHero } from '../components/coverage/CoverageHero'
import { WallHeader } from '../components/coverage/WallHeader'
import { CoverageCardGrid } from '../components/coverage/CoverageCardGrid'
import { CoverageInspector } from '../components/coverage/CoverageInspector'
import { sortCoverageRows, type CoverageSort } from '../components/coverage/coverageSort'
import {
  COVERAGE_FILTERS,
  filterRows,
  matchesFilter,
  type CoverageFilter,
} from '../components/coverage/coverageFilter'
import { useToastStore } from '../stores/toastStore'
import { mapErrorToUserMessage } from '../utils/errorMessage'

// Default applied sort when none is stored: most-urgent first, so the names that
// need the analyst surface at the top.
const DEFAULT_SORT: CoverageSort = { key: 'needs_action', dir: 'desc' }

export function CoveragePage(): React.ReactElement {
  const { t } = useI18n()
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.addToast)

  const groupsQuery = useCoverageGroups()
  const groups = groupsQuery.data ?? []

  const setSelectedGroup = useCoverageStore((s) => s.setSelectedGroup)
  const selectedTickers = useCoverageStore((s) => s.selectedTickers)
  const toggleTicker = useCoverageStore((s) => s.toggleTicker)
  const clearSelection = useCoverageStore((s) => s.clearSelection)
  const focusedTicker = useCoverageStore((s) => s.focusedTicker)
  const setFocusedTicker = useCoverageStore((s) => s.setFocusedTicker)
  const sortByGroup = useCoverageStore((s) => s.sortByGroup)
  const setSort = useCoverageStore((s) => s.setSort)
  // One shipped density (comfort). The toggle was cut; the store field stays so
  // the card/grid sizing props keep working, pinned to comfort.
  const density = useCoverageStore((s) => s.density)

  // Landing view = the triage queue. The analyst's first question is "what needs
  // me", so Needs Action is the homepage, not an unfiltered dump.
  const [filter, setFilter] = useState<CoverageFilter>('needs_action')

  // Market-degraded retry bar (BUG-032): the fast skeleton painted the table but
  // the full (market) fetch failed, so price/market-cap/multiples columns keep
  // shimmering. We surface a dismissible retry bar; dismissal is sticky until a
  // fresh failure (the marketError → false → true transition re-shows it).
  const [marketRetryDismissed, setMarketRetryDismissed] = useState(false)

  // The single surfaced list is the system "Studied Tickers" group; there is no
  // group switcher in the UX. Fall back to the first group only if the system
  // flag isn't present (older seed).
  const activeGroupId = (groups.find((g) => g.is_system) ?? groups[0])?.id ?? null

  const overviewQuery = useCoverageOverview(activeGroupId)
  const rows = useMemo(() => overviewQuery.data?.rows ?? [], [overviewQuery.data])

  const activeSort = activeGroupId ? (sortByGroup[activeGroupId] ?? null) : null
  const effectiveSort = activeSort ?? DEFAULT_SORT

  const visibleRows = useMemo(
    () => sortCoverageRows(filterRows(rows, filter), effectiveSort),
    [rows, filter, effectiveSort],
  )

  // Counts per filter — computed over the full row set so each badge reflects
  // the real universe, not the currently-filtered view.
  const filterCounts = useMemo(() => {
    const counts = {} as Record<CoverageFilter, number>
    for (const f of COVERAGE_FILTERS) counts[f] = rows.filter((r) => matchesFilter(r, f)).length
    return counts
  }, [rows])

  // Focus management: keep the inspector on a real, currently-visible card.
  // Resets to the first visible card when focus is empty (group switch nulls it)
  // or when the focused ticker dropped out of view (filtered out / removed).
  useEffect(() => {
    if (visibleRows.length === 0) {
      if (focusedTicker !== null) setFocusedTicker(null)
      return
    }
    const stillVisible = focusedTicker && visibleRows.some((r) => r.ticker === focusedTicker)
    if (!stillVisible) setFocusedTicker(visibleRows[0].ticker)
  }, [visibleRows, focusedTicker, setFocusedTicker])

  const focusedRow = useMemo(
    () => rows.find((r) => r.ticker === focusedTicker) ?? null,
    [rows, focusedTicker],
  )

  // Re-arm the market-degraded retry bar on each fresh failure: when marketError
  // flips false→true (e.g. a retry failed again, or a new group's full fetch
  // fails), clear a prior dismissal so the user sees it again.
  const prevMarketErrorRef = useRef(false)
  useEffect(() => {
    if (overviewQuery.marketError && !prevMarketErrorRef.current) setMarketRetryDismissed(false)
    prevMarketErrorRef.current = overviewQuery.marketError
  }, [overviewQuery.marketError])

  // ── Run completion → refresh the desk ────────────────────────────────────
  // Runs launched from a card / inspector are async (SSE-tracked in
  // runStreamStore). Without this, a card fires off a run, shows "running",
  // and then stays stuck on that snapshot — the overview's staleTime (30s,
  // no refetch-on-focus) never re-pulls run_status / research_count / latest_at.
  // Mirror StockWorkspace: when any tracked run transitions to completed /
  // failed, invalidate the read models it touched. Deduped per runId so a
  // progress tick doesn't re-invalidate.
  const queryClient = useQueryClient()
  const runs = useRunStreamStore((s) => s.runs)
  const trackBatchRuns = useRunStreamStore((s) => s.trackBatchRuns)
  const closeBatchStream = useRunStreamStore((s) => s.closeBatchStream)
  const notifiedRunsRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    for (const run of Object.values(runs)) {
      if (run.status !== 'completed' && run.status !== 'failed') continue
      const key = `${run.runId}:${run.status}`
      if (notifiedRunsRef.current.has(key)) continue
      notifiedRunsRef.current.add(key)
      // Key-prefix invalidation (TanStack matches by prefix), mirroring the
      // hooks: overview (run_status / counts / latest_*), the ticker's artifact
      // timeline (a new artifact appended), and the studied-tickers list.
      queryClient.invalidateQueries({ queryKey: ['coverage', 'overview'] })
      queryClient.invalidateQueries({ queryKey: ['v5-artifacts-timeline', run.ticker] })
      queryClient.invalidateQueries({ queryKey: ['studied-tickers'] })
    }
  }, [runs, queryClient])

  // ── Teardown the aggregated batch stream on unmount ───────────────────────
  // The Coverage batch opens ONE long-lived SSE connection (BUG-031). Unlike
  // single-run streams — which intentionally survive navigation so a 30-60s run
  // keeps tracking — the batch connection is owned by THIS page: nothing else
  // reads it, so leaving it open on navigate-away leaks a connection (and, on
  // HTTP/1.1, a pool slot). Close it on unmount. The runs themselves keep going
  // on the backend and their final state is already in the store for the badge;
  // re-entering Coverage just won't live-stream the in-flight ones (acceptable —
  // the overview's invalidation on the next completion still refreshes the desk).
  useEffect(() => {
    return () => closeBatchStream()
  }, [closeBatchStream])

  // ── Responsive: side inspector vs bottom dock ─────────────────────────────
  // A fixed 300px right inspector + the card wall can't coexist once the AI
  // panel eats the width (BUG: cards clipped at the default window). Below a
  // workspace-width threshold the inspector stacks BELOW the wall as a capped
  // dock, so the cards keep a full-width single column instead of being crushed.
  const workspaceRef = useRef<HTMLDivElement>(null)
  const [stacked, setStacked] = useState(false)
  useEffect(() => {
    const el = workspaceRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0
      // ~360 min card column + 300 inspector + 16 gap ≈ 676; stack a touch above.
      setStacked(w > 0 && w < 720)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Compare needs ≥2 distinct tickers (focused + multi-select). Drives the
  // inspector's Compare enabled-state so it never looks actionable then dead-ends.
  const compareReady = useMemo(
    () => new Set([focusedTicker, ...selectedTickers].filter(Boolean)).size >= 2,
    [focusedTicker, selectedTickers],
  )

  // createGroup + addMembers are used ONLY by the cold-start empty state below
  // (seed the first Studied Tickers list). batchRun / removeMember drive the
  // card + inspector actions. Group rename/delete were removed with the switcher.
  const createGroup = useCreateGroup()
  const addMembers = useAddMembers()
  const batchRun = useBatchRun()
  const removeMember = useRemoveMember()

  // ── Groups request failed → error state, NOT the starter ──────────────────
  if (groupsQuery.isError) {
    return (
      <ErrorState
        message={t('coverage.error.groupsFailed')}
        retryLabel={t('coverage.error.retry')}
        onRetry={() => void groupsQuery.refetch()}
      />
    )
  }

  // ── No groups yet → Coverage Starter (State A) ────────────────────────────
  if (!groupsQuery.isLoading && groups.length === 0) {
    return (
      <CoverageEmptyState
        busy={createGroup.isPending}
        onCreate={(name, tickers) => {
          createGroup.mutate(
            { name },
            {
              onSuccess: (group) => {
                setSelectedGroup(group.id)
                if (tickers.length > 0)
                  addMembers.mutate(
                    { id: group.id, tickers },
                    {
                      onError: (err) =>
                        toast({
                          type: 'error',
                          title: t('coverage.error.addFailed'),
                          description: mapErrorToUserMessage(err),
                        }),
                    },
                  )
              },
              onError: (err) =>
                toast({
                  type: 'error',
                  title: t('coverage.error.createFailed'),
                  description: mapErrorToUserMessage(err),
                }),
            },
          )
        }}
      />
    )
  }

  // ── Handlers ──────────────────────────────────────────────────────────────

  function handleRun(tickers: string[]) {
    if (!activeGroupId || tickers.length === 0) return
    batchRun.mutate(
      { id: activeGroupId, tickers },
      {
        onSuccess: (res) => {
          if (res.runs.length === 0 && res.skipped.length > 0) {
            toast({
              type: 'error',
              title: t('coverage.toast.allSkipped', {
                skipped: res.skipped.length,
                reason: res.skipped[0]?.reason ?? '',
              }),
            })
            return
          }
          // Register the whole batch over ONE aggregated SSE connection
          // (/api/runs/events?ids=…). Per-run EventSources saturate the browser's
          // ~6-conn HTTP/1.1 pool, so a 10-ticker batch starved runs 7-10 AND
          // blocked all other polling — the app froze (BUG-031). trackBatchRuns
          // seeds each ticker's 'running' state and multiplexes every run's
          // events back to its ticker, so the run-completion effect below still
          // fires per ticker and the desk refreshes on each completion.
          trackBatchRuns(
            res.runs.map((r) => ({ runId: r.run_id, ticker: r.ticker })),
            res.pipeline_type,
          )
          toast({
            type: res.skipped.length ? 'info' : 'success',
            title: t('coverage.toast.launched', {
              n: res.runs.length,
              skipped: res.skipped.length,
            }),
          })
          clearSelection()
        },
        onError: (err) =>
          toast({
            type: 'error',
            title: t('coverage.toast.runFailed'),
            description: mapErrorToUserMessage(err),
          }),
      },
    )
  }

  function handleCompare(tickers: string[]) {
    const unique = [...new Set(tickers)]
    if (unique.length < 2) {
      toast({ type: 'info', title: t('coverage.toast.compareNeedsTwo') })
      return
    }
    navigate(`/compare?tickers=${encodeURIComponent(unique.join(','))}`)
  }

  function handleRemoveMember(ticker: string) {
    if (!activeGroupId) return
    removeMember.mutate(
      { id: activeGroupId, ticker },
      {
        // Drop the removed ticker from the multi-select so a stale id can't be
        // batch-run. Focus is re-resolved by the effect once the row vanishes.
        onSuccess: () => {
          if (selectedTickers.includes(ticker)) toggleTicker(ticker)
        },
        onError: (err) =>
          toast({
            type: 'error',
            title: t('coverage.error.removeFailed'),
            description: mapErrorToUserMessage(err),
          }),
      },
    )
  }

  const hasSelection = selectedTickers.length > 0

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        // Stacked (narrow) mode scrolls vertically: the tall hero + wrapped
        // toolbar + docked inspector can't all share a fixed viewport height
        // without crushing the card wall to nothing, so let the page grow and
        // scroll (spec: small windows are usable + scrollable, not pixel-tight).
        overflowY: stacked ? 'auto' : undefined,
        padding: '20px 24px',
      }}
    >
      <CoverageHero />

      <WallHeader
        filter={filter}
        filterCounts={filterCounts}
        onFilter={setFilter}
        sort={effectiveSort}
        onSort={(s) => activeGroupId && setSort(activeGroupId, s)}
      />

      {/* Market-degraded retry bar (BUG-032): the table is alive (fast skeleton)
          but the full market fetch failed, so the price/cap/multiples columns
          are shimmering with no data behind them. Offer a retry on the FULL
          query (not the fast skeleton) and let the user dismiss the bar. */}
      {overviewQuery.marketError && !marketRetryDismissed && (
        <MarketRetryBar
          message={t('coverage.error.marketFailed')}
          retryLabel={t('coverage.error.retry')}
          dismissLabel={t('coverage.error.dismiss')}
          onRetry={() => overviewQuery.refetch()}
          onDismiss={() => setMarketRetryDismissed(true)}
        />
      )}

      {/* Batch action bar — only when a multi-select exists. Keeps batch ops
          (Run / Compare) out of the toolbar's single-ticker flow. */}
      {hasSelection && (
        <div
          style={{
            display: 'flex',
            flexShrink: 0,
            alignItems: 'center',
            gap: 12,
            marginBottom: 12,
            padding: '8px 14px',
            border: '1px solid var(--border-glow)',
            borderRadius: 'var(--radius-md)',
            background: 'var(--primary-soft)',
          }}
        >
          <span
            style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: 12 }}
          >
            {t('coverage.batch.selected', { n: selectedTickers.length })}
          </span>
          <BarButton
            label={t('coverage.runSelected', { n: selectedTickers.length })}
            onClick={() => handleRun(selectedTickers)}
            disabled={batchRun.isPending}
            primary
          />
          <BarButton
            label={t('coverage.compareSelected')}
            onClick={() => handleCompare(selectedTickers)}
            disabled={selectedTickers.length < 2}
          />
          <BarButton label={t('coverage.batch.clear')} onClick={clearSelection} />
        </div>
      )}

      {/* Card wall + inspector — side-by-side when wide, inspector docks below
          when the workspace is too narrow (so cards never get crushed). */}
      <div
        ref={workspaceRef}
        style={{
          display: 'flex',
          flexDirection: stacked ? 'column' : 'row',
          gap: 16,
          // Side mode fills the remaining viewport; stacked mode sizes to content
          // (wall + dock) and lets the PAGE scroll to reach the dock.
          flex: stacked ? '0 0 auto' : 1,
          minHeight: 0,
        }}
      >
        <div
          style={{
            flex: stacked ? '0 0 auto' : 1,
            minWidth: 0,
            minHeight: 0,
            // Stacked: the wall is a CONTROLLED-height viewport that scrolls
            // INTERNALLY — so 100 tickers don't grow it to ~10000px and shove the
            // inspector dock past the bottom. The dock sits right after this box.
            // Side mode: flex:1 fills the column and the grid scrolls internally.
            height: stacked ? 'clamp(280px, 55vh, 600px)' : undefined,
            flexShrink: 0,
          }}
        >
          {overviewQuery.isLoading ? (
            <Placeholder text={t('coverage.loading')} />
          ) : overviewQuery.isError ? (
            <ErrorState
              message={t('coverage.error.overviewFailed')}
              retryLabel={t('coverage.error.retry')}
              onRetry={() => void overviewQuery.refetch()}
            />
          ) : rows.length === 0 ? (
            <Placeholder text={t('coverage.emptyGroup')} />
          ) : (
            <CoverageCardGrid
              rows={visibleRows}
              density={density}
              focusedTicker={focusedTicker}
              selected={selectedTickers}
              marketPending={overviewQuery.marketPending}
              onFocus={setFocusedTicker}
              onToggleSelect={toggleTicker}
              onRun={(ticker) => handleRun([ticker])}
              onOpen={(ticker) => navigate(`/stocks/${ticker}`)}
            />
          )}
        </div>
        <CoverageInspector
          row={focusedRow}
          layout={stacked ? 'dock' : 'side'}
          compareReady={compareReady}
          onRun={(ticker) => handleRun([ticker])}
          onOpen={(ticker) => navigate(`/stocks/${ticker}`)}
          onCompare={(ticker) => handleCompare([ticker, ...selectedTickers])}
          onRemove={handleRemoveMember}
        />
      </div>
    </div>
  )
}

function BarButton({
  label,
  onClick,
  disabled,
  primary,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
  primary?: boolean
}): React.ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: '6px 14px',
        borderRadius: 'var(--radius-md)',
        fontSize: 12,
        fontWeight: 500,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        border: primary ? 'none' : '1px solid var(--border-soft)',
        background: primary
          ? 'linear-gradient(135deg, var(--primary), var(--secondary))'
          : 'transparent',
        color: primary ? 'var(--text-on-primary)' : 'var(--text-secondary)',
      }}
    >
      {label}
    </button>
  )
}

function Placeholder({ text }: { text: string }): React.ReactElement {
  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--text-muted)',
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
      }}
    >
      {text}
    </div>
  )
}

// Error state — distinct from the empty state on purpose (BUG-051): a request
// FAILURE must never look like "no data". Offers a retry.
function ErrorState({
  message,
  retryLabel,
  onRetry,
}: {
  message: string
  retryLabel: string
  onRetry: () => void
}): React.ReactElement {
  return (
    <div
      data-testid="coverage-error"
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        color: 'var(--danger)',
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
        textAlign: 'center',
        padding: 24,
      }}
    >
      <span>{message}</span>
      <button
        type="button"
        onClick={onRetry}
        className="btn-shimmer"
        style={{ padding: '6px 16px', fontSize: 11 }}
      >
        {retryLabel}
      </button>
    </div>
  )
}

// Slim inline bar shown when the fast skeleton stands in but the full market
// fetch failed (BUG-032). Retry re-runs the FULL query; dismiss hides the bar
// (the columns keep their shimmer either way).
function MarketRetryBar({
  message,
  retryLabel,
  dismissLabel,
  onRetry,
  onDismiss,
}: {
  message: string
  retryLabel: string
  dismissLabel: string
  onRetry: () => void
  onDismiss: () => void
}): React.ReactElement {
  return (
    <div
      data-testid="coverage-market-retry"
      style={{
        display: 'flex',
        flexShrink: 0,
        alignItems: 'center',
        gap: 12,
        marginBottom: 12,
        padding: '8px 14px',
        border: '1px solid var(--danger)',
        borderRadius: 'var(--radius-md)',
        background: 'var(--danger-soft)',
        color: 'var(--text-secondary)',
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
      }}
    >
      <span style={{ flex: 1, minWidth: 0 }}>{message}</span>
      <button
        type="button"
        onClick={onRetry}
        className="btn-shimmer"
        style={{ padding: '4px 12px', fontSize: 11, flexShrink: 0 }}
      >
        {retryLabel}
      </button>
      <button
        type="button"
        onClick={onDismiss}
        aria-label={dismissLabel}
        title={dismissLabel}
        style={{
          flexShrink: 0,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 22,
          height: 22,
          padding: 0,
          border: 'none',
          background: 'transparent',
          color: 'var(--text-secondary)',
          cursor: 'pointer',
        }}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path
            d="M2.5 2.5l7 7M9.5 2.5l-7 7"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
          />
        </svg>
      </button>
    </div>
  )
}
