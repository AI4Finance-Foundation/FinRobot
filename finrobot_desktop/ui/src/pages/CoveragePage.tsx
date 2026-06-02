// CoveragePage — the desktop's first screen (route `/coverage`). Manages the
// user's research coverage universe: pick a group, see the Coverage Table
// (live market + latest research + signal + refresh reasons), add tickers,
// batch-run research, jump to Compare. Server state via useCoverage (TanStack
// Query); selection in coverageStore. Drill-down stays at /stocks/:ticker.

import { useMemo, useState } from 'react'
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
import { CoverageTable } from '../components/coverage/CoverageTable'
import { CoverageGroupMenu } from '../components/coverage/CoverageGroupMenu'
import { CoverageRail } from '../components/coverage/CoverageRail'
import { CoverageEmptyState } from '../components/coverage/CoverageEmptyState'
import { CoverageHero } from '../components/coverage/CoverageHero'
import { ColumnMenu } from '../components/coverage/ColumnMenu'
import { nextSort, sortCoverageRows } from '../components/coverage/coverageSort'
import { useToastStore } from '../stores/toastStore'
import { isValidTicker } from '../utils/ticker'

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
  const setSelected = useCoverageStore((s) => s.setSelected)
  const clearSelection = useCoverageStore((s) => s.clearSelection)
  const sortByGroup = useCoverageStore((s) => s.sortByGroup)
  const setSort = useCoverageStore((s) => s.setSort)
  const hiddenColumns = useCoverageStore((s) => s.hiddenColumns)
  const toggleColumn = useCoverageStore((s) => s.toggleColumn)

  // Resolve the active group: stored choice if still present, else first.
  const activeGroupId =
    (storedGroupId && groups.some((g) => g.id === storedGroupId) ? storedGroupId : null) ??
    groups[0]?.id ??
    null

  const overviewQuery = useCoverageOverview(activeGroupId)
  // Stable ref (the `?? []` would otherwise be a fresh array each render and
  // defeat the sort useMemo below).
  const rows = useMemo(() => overviewQuery.data?.rows ?? [], [overviewQuery.data])

  // Per-group sort (persisted in coverageStore). Sort here so the Table stays
  // presentational and the Rail keeps the backend (member) order.
  const activeSort = activeGroupId ? (sortByGroup[activeGroupId] ?? null) : null
  const sortedRows = useMemo(() => sortCoverageRows(rows, activeSort), [rows, activeSort])

  const createGroup = useCreateGroup()
  const addMembers = useAddMembers()
  const batchRun = useBatchRun()
  const updateGroup = useUpdateGroup()
  const deleteGroup = useDeleteGroup()
  const removeMember = useRemoveMember()

  const [addInput, setAddInput] = useState('')

  const activeGroup = groups.find((g) => g.id === activeGroupId) ?? null

  // ── Groups request failed → error state, NOT the starter ──────────────────
  // Falling through to the empty check would show the "create your first
  // group" starter on a 503, hiding existing groups and inviting duplicates.
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

  function handleAdd() {
    if (!activeGroupId) return
    // Split on whitespace / comma / semicolon, then validate each symbol so we
    // never persist junk ("苹果", "BRK/B", over-long) that would fan out to
    // providers forever (BUG-053). Invalid tokens are reported, not silently
    // dropped; only valid ones are sent (backend re-validates → 422 safety net).
    const tokens = addInput
      .split(/[\s,;]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean)
    const valid = tokens.filter(isValidTicker)
    const invalid = tokens.filter((s) => !isValidTicker(s))
    if (invalid.length > 0) {
      toast({
        type: 'error',
        title: t('coverage.error.invalidTickers', { tickers: invalid.join(', ') }),
      })
    }
    if (valid.length === 0) return
    addMembers.mutate(
      { id: activeGroupId, tickers: valid },
      {
        onSuccess: () => setAddInput(''),
        onError: () => toast({ type: 'error', title: t('coverage.error.addFailed') }),
      },
    )
  }

  function handleRun(tickers: string[]) {
    if (!activeGroupId || tickers.length === 0) return
    batchRun.mutate(
      { id: activeGroupId, tickers },
      {
        onSuccess: (res) => {
          // All skipped → the batch did nothing (e.g. every ticker rejected).
          // A 200 with zero runs is NOT success — surface it as an error with
          // the first reason so the user doesn't think research was launched.
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

  function handleCompare() {
    if (selectedTickers.length < 2) {
      toast({ type: 'info', title: t('coverage.toast.compareNeedsTwo') })
      return
    }
    navigate(`/compare?tickers=${encodeURIComponent(selectedTickers.join(','))}`)
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
        // Move the selection off the now-gone group: next remaining group, else
        // let activeGroupId fall back to the first (or the starter if none).
        const next = groups.find((g) => g.id !== deletingId)
        // setSelectedGroup already clears the multi-select; passing null lets
        // activeGroupId fall back to the first remaining group (or the starter).
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
        onSuccess: () => toggleTickerOff(ticker),
        onError: () => toast({ type: 'error', title: t('coverage.error.removeFailed') }),
      },
    )
  }

  // Drop a removed ticker from the multi-select so a stale id can't be batch-run.
  function toggleTickerOff(ticker: string) {
    if (selectedTickers.includes(ticker)) toggleTicker(ticker)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '20px 24px' }}>
      {/* Hero band — robot backdrop + big ticker search (drill-down into a
          single name). Sits above the Coverage tool so the first screen reads
          as a product, not a bare table. */}
      <CoverageHero />

      {/* Command bar */}
      <div
        style={{
          display: 'flex',
          gap: 12,
          alignItems: 'center',
          marginBottom: 16,
          flexWrap: 'wrap',
        }}
      >
        <select
          value={activeGroupId ?? ''}
          onChange={(e) => setSelectedGroup(e.target.value)}
          aria-label={t('coverage.groupSelect')}
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--text-primary)',
            fontSize: 14,
            padding: '7px 12px',
          }}
        >
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name} ({g.member_count})
            </option>
          ))}
        </select>

        {activeGroup && (
          <CoverageGroupMenu
            groupName={activeGroup.name}
            busy={updateGroup.isPending || deleteGroup.isPending}
            onRename={handleRename}
            onDelete={handleDeleteGroup}
          />
        )}

        {/* Add-to-group control — NOT a second search. The hero search drills
            into a single stock (/stocks/:ticker); this adds a ticker to THIS
            coverage group (a row in the table below). The leading "+" and the
            explicit Add button keep the two from reading as the same thing. */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            flex: '1 1 220px',
            minWidth: 200,
            background: 'var(--bg-card)',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-md)',
            paddingLeft: 10,
          }}
        >
          <span style={{ color: 'var(--text-muted)', fontSize: 14, lineHeight: 1 }} aria-hidden>
            +
          </span>
          <input
            value={addInput}
            onChange={(e) => setAddInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            placeholder={t('coverage.addPlaceholder')}
            aria-label={t('coverage.addPlaceholder')}
            style={{
              flex: 1,
              minWidth: 0,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 13,
              padding: '7px 10px',
            }}
          />
          <button
            type="button"
            onClick={handleAdd}
            disabled={!addInput.trim() || addMembers.isPending}
            style={{
              background: 'transparent',
              border: 'none',
              borderLeft: '1px solid var(--border-soft)',
              color: addInput.trim() ? 'var(--primary)' : 'var(--text-muted)',
              cursor: addInput.trim() ? 'pointer' : 'not-allowed',
              fontSize: 12,
              padding: '7px 12px',
              whiteSpace: 'nowrap',
            }}
          >
            {t('coverage.addButton')}
          </button>
        </div>

        <ToolbarButton
          label={t('coverage.runSelected', { n: selectedTickers.length })}
          onClick={() => handleRun(selectedTickers)}
          disabled={selectedTickers.length === 0 || batchRun.isPending}
          primary
        />
        <ToolbarButton
          label={t('coverage.compareSelected')}
          onClick={handleCompare}
          disabled={selectedTickers.length < 2}
        />
        <div style={{ marginLeft: 'auto' }}>
          <ColumnMenu hiddenColumns={hiddenColumns} onToggle={toggleColumn} />
        </div>
      </div>

      {/* Table + rail */}
      <div style={{ display: 'flex', gap: 20, flex: 1, minHeight: 0 }}>
        <div
          style={{
            flex: 1,
            minWidth: 0,
            background: 'rgba(15,15,34,0.4)',
            border: '1px solid var(--border-faint)',
            borderRadius: 'var(--radius-lg)',
          }}
        >
          {overviewQuery.isLoading ? (
            <Placeholder text={t('coverage.loading')} />
          ) : overviewQuery.isError ? (
            // 503 / store-not-initialised must not render as "empty group".
            <ErrorState
              message={t('coverage.error.overviewFailed')}
              retryLabel={t('coverage.error.retry')}
              onRetry={() => void overviewQuery.refetch()}
            />
          ) : rows.length === 0 ? (
            <Placeholder text={t('coverage.emptyGroup')} />
          ) : (
            <CoverageTable
              rows={sortedRows}
              selected={selectedTickers}
              marketPending={overviewQuery.marketPending}
              hiddenColumns={hiddenColumns}
              sort={activeSort}
              onSort={(key) => activeGroupId && setSort(activeGroupId, nextSort(activeSort, key))}
              onToggle={toggleTicker}
              onToggleAll={() =>
                selectedTickers.length === rows.length
                  ? clearSelection()
                  : setSelected(rows.map((r) => r.ticker))
              }
              onOpenTicker={(ticker) => navigate(`/stocks/${ticker}`)}
              onRunOne={(ticker) => handleRun([ticker])}
              onRemove={handleRemoveMember}
            />
          )}
        </div>
        <CoverageRail rows={rows} />
      </div>
    </div>
  )
}

function ToolbarButton({
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
        padding: '7px 16px',
        borderRadius: 'var(--radius-md)',
        fontSize: 13,
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

// Error state — distinct from the empty state on purpose. A request FAILURE
// (503 / network / store not initialised) must never look like "no data"
// (BUG-051): for an analyst, "the service is down" and "this group is empty"
// are opposite conclusions. Offers a retry.
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
