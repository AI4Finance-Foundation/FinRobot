// CoveragePage — the coverage archive / management route (`/coverage`). The
// search-first homepage lives at `/research`; this screen is the studied ticker
// desk: track-record strip, triage/sort controls, and a wall of ticker cards.
// There is ONE surfaced list — Studied Tickers (the system coverage group);
// multi-group machinery stays backend-only. Card click opens `/stocks/:ticker`,
// where research runs and artifact history live.
//
// A ticker is the primary object: a live market snapshot AND many research
// artifacts. The card shows the snapshot + latest verdict + report count; the
// detail workspace owns running research and reviewing historical runs.

import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useI18n } from '../i18n'
import { useCoverageStore } from '../stores/coverageStore'
import { useCoverageGroups, useCoverageOverview } from '../hooks/useCoverage'
import { CoverageEmptyState } from '../components/coverage/CoverageEmptyState'
import { CoverageTrustStrip } from '../components/coverage/CoverageTrustStrip'
import { WallHeader } from '../components/coverage/WallHeader'
import { CoverageCardGrid } from '../components/coverage/CoverageCardGrid'
import { sortCoverageRows, type CoverageSort } from '../components/coverage/coverageSort'
import {
  COVERAGE_FILTERS,
  filterRows,
  matchesFilter,
  type CoverageFilter,
} from '../components/coverage/coverageFilter'

// Default applied sort when none is stored: most-urgent first, so the names that
// need the analyst surface at the top.
const DEFAULT_SORT: CoverageSort = { key: 'needs_action', dir: 'desc' }

export function CoveragePage(): React.ReactElement {
  const { t } = useI18n()
  const navigate = useNavigate()

  const groupsQuery = useCoverageGroups()
  const groups = groupsQuery.data ?? []

  const sortByGroup = useCoverageStore((s) => s.sortByGroup)
  const setSort = useCoverageStore((s) => s.setSort)
  // One shipped density (comfort). The toggle was cut; the store field stays so
  // the card/grid sizing props keep working, pinned to comfort.
  const density = useCoverageStore((s) => s.density)

  // Archive default: show the whole studied universe first. Needs Action remains
  // one lens, but it no longer blanks the page when there is nothing urgent.
  const [filter, setFilter] = useState<CoverageFilter>('all')

  // Market-degraded retry bar (BUG-032): the fast skeleton painted the table but
  // the full (market) fetch failed, so price/market-cap/multiples columns keep
  // shimmering. We surface a dismissible retry bar; dismissal is sticky until a
  // fresh failure (the marketError → false → true transition re-shows it).
  const [marketRetryDismissed, setMarketRetryDismissed] = useState(false)

  // The single surfaced list is the system "Studied Tickers" group; there is no
  // group switcher in the UX. Fall back to the first group only if the system
  // flag isn't present (older seed).
  const activeGroup = groups.find((g) => g.is_system) ?? groups[0]
  const activeGroupId = activeGroup?.id ?? null

  const overviewQuery = useCoverageOverview(activeGroupId)
  const rows = useMemo(() => overviewQuery.data?.rows ?? [], [overviewQuery.data])
  // Scope the track-record strip to the active group's members (UX-013).
  const groupTickers = useMemo(() => rows.map((r) => r.ticker), [rows])

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

  // Re-arm the market-degraded retry bar on each fresh failure: when marketError
  // flips false→true (e.g. a retry failed again, or a new group's full fetch
  // fails), clear a prior dismissal so the user sees it again.
  const prevMarketErrorRef = useRef(false)
  useEffect(() => {
    if (overviewQuery.marketError && !prevMarketErrorRef.current) setMarketRetryDismissed(false)
    prevMarketErrorRef.current = overviewQuery.marketError
  }, [overviewQuery.marketError])

  // ── Groups still loading → full-page placeholder, NOT a false empty state ──
  // Cold start: while groups load, activeGroupId is null → useCoverageOverview
  // is disabled → in TanStack v5 a disabled query reports isLoading=false, so
  // rows=[] would fall into the rows.length===0 empty state ("还没有 ticker")
  // and flash "no coverage" to a user who actually has coverage (UX-007). Gate
  // the whole page on the groups load instead.
  if (groupsQuery.isLoading) {
    return (
      <div style={{ height: '100%', padding: '20px 24px' }}>
        <Placeholder text={t('coverage.loading')} />
      </div>
    )
  }

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

  // ── No coverage yet → archive-empty state ────────────────────────────────
  // Loading + error are handled above, so reaching here means groups resolved
  // to empty. Research starts from `/research`; this route stays the management
  // surface and points the user back to the search-first entry.
  if (groups.length === 0) {
    return <CoverageEmptyState />
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        padding: '20px 24px',
      }}
    >
      {/* Track record — the credibility proof for the analyst/quant, scoped to
          the active group. Renders only with a non-empty scope; suppresses the
          percentage until the sample is large enough (UX-013). */}
      <CoverageTrustStrip tickers={groupTickers} groupName={activeGroup?.name ?? ''} />

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

      {/* Card wall — every card is a direct link to the ticker workspace. */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          minWidth: 0,
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
            marketPending={overviewQuery.marketPending}
            showReasons={filter === 'needs_action'}
            onOpen={(ticker) => navigate(`/stocks/${ticker}`)}
          />
        )}
      </div>
    </div>
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
