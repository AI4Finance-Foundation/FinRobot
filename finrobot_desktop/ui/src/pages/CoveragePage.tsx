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
} from '../hooks/useCoverage'
import { CoverageTable } from '../components/coverage/CoverageTable'
import { CoverageRail } from '../components/coverage/CoverageRail'
import { CoverageEmptyState } from '../components/coverage/CoverageEmptyState'
import { nextSort, sortCoverageRows } from '../components/coverage/coverageSort'
import { useToastStore } from '../stores/toastStore'

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

  const [addInput, setAddInput] = useState('')

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
                if (tickers.length > 0) addMembers.mutate({ id: group.id, tickers })
              },
            },
          )
        }}
      />
    )
  }

  function handleAdd() {
    if (!activeGroupId) return
    const tickers = addInput
      .split(/[\s,]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean)
    if (tickers.length === 0) return
    addMembers.mutate({ id: activeGroupId, tickers }, { onSuccess: () => setAddInput('') })
  }

  function handleRun(tickers: string[]) {
    if (!activeGroupId || tickers.length === 0) return
    batchRun.mutate(
      { id: activeGroupId, tickers },
      {
        onSuccess: (res) => {
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '20px 24px' }}>
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

        <input
          value={addInput}
          onChange={(e) => setAddInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
          placeholder={t('coverage.addPlaceholder')}
          style={{
            flex: '1 1 220px',
            minWidth: 180,
            background: 'var(--bg-card)',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--text-primary)',
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            padding: '7px 12px',
          }}
        />

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
          ) : rows.length === 0 ? (
            <Placeholder text={t('coverage.emptyGroup')} />
          ) : (
            <CoverageTable
              rows={sortedRows}
              selected={selectedTickers}
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
