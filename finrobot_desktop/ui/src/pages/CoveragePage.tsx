// CoveragePage — the desktop's first screen (route `/coverage`). The user's
// research workspace: a hero search (drill into one name + auto-enrol it), a
// command toolbar (workspace switch / filters / density / import / sort), a wall
// of fixed-height ticker cards, and a right Inspector scoped to the focused
// ticker. Server state via useCoverage (TanStack Query); view-state (selection,
// focus, density, sort) in coverageStore. Drill-down stays at /stocks/:ticker.
//
// A ticker is the primary object: it has a live market snapshot AND many
// research artifacts. The card shows the live snapshot + latest verdict +
// report count; the inspector splits Live Market from the Latest Research
// Artifact (at-run price frozen, never overwritten by live) and lists the full
// artifact history. Remove drops only workspace membership — never artifacts.

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useI18n } from '../i18n'
import { useCoverageStore } from '../stores/coverageStore'
import {
  useAddMembers,
  useBatchRun,
  useCoverageGroups,
  useCoverageOverview,
  useCreateGroup,
  useDeleteGroup,
  useRemoveMember,
  useUpdateGroup,
} from '../hooks/useCoverage'
import { CoverageEmptyState } from '../components/coverage/CoverageEmptyState'
import { CoverageHero } from '../components/coverage/CoverageHero'
import { CoverageToolbar } from '../components/coverage/CoverageToolbar'
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

// Default applied sort when a group has none stored: most-urgent first, so the
// names that need the analyst surface at the top of a cold desk.
const DEFAULT_SORT: CoverageSort = { key: 'needs_action', dir: 'desc' }

export function CoveragePage(): React.ReactElement {
  const { t } = useI18n()
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.addToast)

  const groupsQuery = useCoverageGroups()
  const groups = groupsQuery.data ?? []

  const storedGroupId = useCoverageStore((s) => s.selectedGroupId)
  const setSelectedGroup = useCoverageStore((s) => s.setSelectedGroup)
  const selectedTickers = useCoverageStore((s) => s.selectedTickers)
  const toggleTicker = useCoverageStore((s) => s.toggleTicker)
  const clearSelection = useCoverageStore((s) => s.clearSelection)
  const focusedTicker = useCoverageStore((s) => s.focusedTicker)
  const setFocusedTicker = useCoverageStore((s) => s.setFocusedTicker)
  const sortByGroup = useCoverageStore((s) => s.sortByGroup)
  const setSort = useCoverageStore((s) => s.setSort)
  const density = useCoverageStore((s) => s.density)
  const setDensity = useCoverageStore((s) => s.setDensity)

  const [filter, setFilter] = useState<CoverageFilter>('all')

  // Resolve the active group: stored choice if still present, else first.
  const activeGroupId =
    (storedGroupId && groups.some((g) => g.id === storedGroupId) ? storedGroupId : null) ??
    groups[0]?.id ??
    null

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

  const createGroup = useCreateGroup()
  const addMembers = useAddMembers()
  const batchRun = useBatchRun()
  const updateGroup = useUpdateGroup()
  const deleteGroup = useDeleteGroup()
  const removeMember = useRemoveMember()

  const activeGroup = groups.find((g) => g.id === activeGroupId) ?? null

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
                      onError: () => toast({ type: 'error', title: t('coverage.error.addFailed') }),
                    },
                  )
              },
              onError: () => toast({ type: 'error', title: t('coverage.error.createFailed') }),
            },
          )
        }}
      />
    )
  }

  // ── Handlers ──────────────────────────────────────────────────────────────

  function handleImport(tickers: string[]) {
    if (!activeGroupId) return
    addMembers.mutate(
      { id: activeGroupId, tickers },
      { onError: () => toast({ type: 'error', title: t('coverage.error.addFailed') }) },
    )
  }

  function handleInvalidImport(invalid: string[]) {
    toast({
      type: 'error',
      title: t('coverage.error.invalidTickers', { tickers: invalid.join(', ') }),
    })
  }

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
          toast({
            type: res.skipped.length ? 'info' : 'success',
            title: t('coverage.toast.launched', {
              n: res.runs.length,
              skipped: res.skipped.length,
            }),
          })
          clearSelection()
        },
        onError: () => toast({ type: 'error', title: t('coverage.toast.runFailed') }),
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

  function handleRename(name: string) {
    if (!activeGroupId) return
    updateGroup.mutate(
      { id: activeGroupId, name },
      { onError: () => toast({ type: 'error', title: t('coverage.error.renameFailed') }) },
    )
  }

  function handleDeleteGroup() {
    if (!activeGroupId) return
    const deletingId = activeGroupId
    deleteGroup.mutate(deletingId, {
      onSuccess: () => {
        const next = groups.find((g) => g.id !== deletingId)
        setSelectedGroup(next ? next.id : null)
      },
      onError: () => toast({ type: 'error', title: t('coverage.error.deleteGroupFailed') }),
    })
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
        onError: () => toast({ type: 'error', title: t('coverage.error.removeFailed') }),
      },
    )
  }

  const hasSelection = selectedTickers.length > 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '20px 24px' }}>
      <CoverageHero />

      <CoverageToolbar
        groups={groups}
        activeGroupId={activeGroupId}
        activeGroupName={activeGroup?.name ?? null}
        groupBusy={updateGroup.isPending || deleteGroup.isPending}
        onSelectGroup={setSelectedGroup}
        onRenameGroup={handleRename}
        onDeleteGroup={handleDeleteGroup}
        filter={filter}
        filterCounts={filterCounts}
        onFilter={setFilter}
        density={density}
        onDensity={setDensity}
        sort={effectiveSort}
        onSort={(s) => activeGroupId && setSort(activeGroupId, s)}
        onImport={handleImport}
        importBusy={addMembers.isPending}
        onInvalidImport={handleInvalidImport}
      />

      {/* Batch action bar — only when a multi-select exists. Keeps batch ops
          (Run / Compare) out of the toolbar's single-ticker flow. */}
      {hasSelection && (
        <div
          style={{
            display: 'flex',
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

      {/* Card wall + inspector */}
      <div style={{ display: 'flex', gap: 16, flex: 1, minHeight: 0 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
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
        color: primary ? '#fff' : 'var(--text-secondary)',
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
