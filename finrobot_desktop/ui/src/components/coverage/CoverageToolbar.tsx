// CoverageToolbar — the desk's command strip: which workspace is open, quick
// filter lenses, card density, batch import, and the active sort. No table-only
// controls (column hide / select-all live with the cards now). Filter counts are
// computed by the page from the real rows and shown as badges so the analyst
// sees "12 Needs Action" before clicking.

import { useState } from 'react'
import { useI18n } from '../../i18n'
import { CoverageGroupMenu } from './CoverageGroupMenu'
import { COVERAGE_FILTERS, type CoverageFilter } from './coverageFilter'
import {
  TOOLBAR_SORT_KEYS,
  defaultDir,
  type CoverageSort,
  type CoverageSortKey,
} from './coverageSort'
import { isValidTicker } from '../../utils/ticker'
import type { CoverageGroupSummary } from '../../api/coverage'
import type { CoverageDensity } from '../../stores/coverageStore'

interface Props {
  groups: CoverageGroupSummary[]
  activeGroupId: string | null
  activeGroupName: string | null
  groupBusy: boolean
  onSelectGroup: (id: string) => void
  onRenameGroup: (name: string) => void
  onDeleteGroup: () => void

  filter: CoverageFilter
  filterCounts: Record<CoverageFilter, number>
  onFilter: (f: CoverageFilter) => void

  density: CoverageDensity
  onDensity: (d: CoverageDensity) => void

  sort: CoverageSort | null
  onSort: (sort: CoverageSort) => void

  onImport: (tickers: string[]) => void
  importBusy: boolean
  onInvalidImport: (invalid: string[]) => void
}

const FILTER_KEY: Record<CoverageFilter, string> = {
  all: 'coverage.filter.all',
  needs_action: 'coverage.filter.needsAction',
  running: 'coverage.filter.running',
  has_reports: 'coverage.filter.hasReports',
  not_run: 'coverage.filter.notRun',
}

const SORT_KEY_LABEL: Record<string, string> = {
  needs_action: 'coverage.sort.needsAction',
  ticker: 'coverage.sort.ticker',
  latest_report: 'coverage.sort.latestReport',
  upside_to_target_live: 'coverage.sort.upside',
}

export function CoverageToolbar({
  groups,
  activeGroupId,
  activeGroupName,
  groupBusy,
  onSelectGroup,
  onRenameGroup,
  onDeleteGroup,
  filter,
  filterCounts,
  onFilter,
  density,
  onDensity,
  sort,
  onSort,
  onImport,
  importBusy,
  onInvalidImport,
}: Props): React.ReactElement {
  const { t } = useI18n()
  const [importOpen, setImportOpen] = useState(false)
  const [importValue, setImportValue] = useState('')

  function submitImport() {
    const tokens = importValue
      .split(/[\s,;]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean)
    const valid = tokens.filter(isValidTicker)
    const invalid = tokens.filter((s) => !isValidTicker(s))
    if (invalid.length > 0) onInvalidImport(invalid)
    if (valid.length > 0) {
      onImport(valid)
      setImportValue('')
      setImportOpen(false)
    }
  }

  const activeSortKey = sort?.key ?? 'needs_action'

  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 12,
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: 14,
        marginBottom: 12,
        position: 'relative',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-lg)',
        background: 'linear-gradient(160deg, var(--secondary-soft), var(--bg-card-overlay))',
      }}
    >
      {/* ── Workspace switch ─────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 220 }}>
        <div>
          <div
            style={{
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              letterSpacing: '1.4px',
              textTransform: 'uppercase',
            }}
          >
            {t('coverage.workspace')}
          </div>
          <select
            value={activeGroupId ?? ''}
            onChange={(e) => onSelectGroup(e.target.value)}
            aria-label={t('coverage.groupSelect')}
            style={{
              marginTop: 2,
              background: 'transparent',
              border: 'none',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-display)',
              fontSize: 13,
              letterSpacing: '1.4px',
              cursor: 'pointer',
              maxWidth: 220,
            }}
          >
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name} ({g.member_count})
              </option>
            ))}
          </select>
        </div>
        {activeGroupName && (
          <CoverageGroupMenu
            groupName={activeGroupName}
            busy={groupBusy}
            onRename={onRenameGroup}
            onDelete={onDeleteGroup}
          />
        )}
      </div>

      {/* ── Filters ──────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {COVERAGE_FILTERS.map((f) => {
          const active = filter === f
          const warn = f === 'needs_action'
          return (
            <button
              key={f}
              type="button"
              onClick={() => onFilter(f)}
              aria-pressed={active}
              style={{
                padding: '7px 10px',
                borderRadius: 'var(--radius-pill)',
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                whiteSpace: 'nowrap',
                cursor: 'pointer',
                border: `1px solid ${
                  active
                    ? warn
                      ? 'var(--border-amber-soft)'
                      : 'var(--border-cyan-soft)'
                    : 'var(--border-faint)'
                }`,
                background: active
                  ? warn
                    ? 'var(--warning-soft)'
                    : 'var(--accent-cyan-soft)'
                  : 'var(--bg-card-overlay)',
                color: active
                  ? warn
                    ? 'var(--accent-amber)'
                    : 'var(--accent-cyan)'
                  : 'var(--text-secondary)',
              }}
            >
              {t(FILTER_KEY[f])} · {filterCounts[f]}
            </button>
          )
        })}
      </div>

      {/* ── Density / import / sort ──────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div
          style={{
            display: 'flex',
            gap: 4,
            padding: 4,
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-md)',
            background: 'var(--bg-card-overlay)',
          }}
        >
          {(['comfort', 'compact'] as const).map((d) => {
            const active = density === d
            return (
              <button
                key={d}
                type="button"
                onClick={() => onDensity(d)}
                aria-pressed={active}
                style={{
                  border: 'none',
                  borderRadius: 'var(--radius-sm)',
                  padding: '8px 10px',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  cursor: 'pointer',
                  background: active ? 'var(--primary-soft)' : 'transparent',
                  boxShadow: active ? 'inset 0 0 0 1px var(--border-glow)' : 'none',
                  color: active ? 'var(--text-primary)' : 'var(--text-muted)',
                }}
              >
                {t(`coverage.density.${d}`)}
              </button>
            )
          })}
        </div>

        {/* Batch import — multi-ticker paste (whitespace / comma / semicolon). */}
        {importOpen ? (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              border: '1px solid var(--border-soft)',
              borderRadius: 'var(--radius-md)',
              background: 'var(--bg-card)',
              paddingLeft: 8,
            }}
          >
            <input
              autoFocus
              value={importValue}
              onChange={(e) => setImportValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submitImport()
                if (e.key === 'Escape') setImportOpen(false)
              }}
              placeholder={t('coverage.import.placeholder')}
              aria-label={t('coverage.import.placeholder')}
              style={{
                width: 180,
                background: 'transparent',
                border: 'none',
                outline: 'none',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                padding: '8px 6px',
              }}
            />
            <button
              type="button"
              onClick={submitImport}
              disabled={!importValue.trim() || importBusy}
              style={{
                border: 'none',
                borderLeft: '1px solid var(--border-soft)',
                background: 'transparent',
                color: importValue.trim() ? 'var(--primary)' : 'var(--text-muted)',
                cursor: importValue.trim() ? 'pointer' : 'not-allowed',
                fontSize: 12,
                padding: '8px 12px',
              }}
            >
              {t('coverage.import.add')}
            </button>
          </div>
        ) : (
          <GhostButton label={t('coverage.import.open')} onClick={() => setImportOpen(true)} />
        )}

        {/* Sort — pick a key, toggle direction. */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-md)',
            background: 'var(--bg-card-overlay)',
            padding: '0 6px 0 10px',
          }}
        >
          <span
            style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 10 }}
          >
            {t('coverage.sort.label')}
          </span>
          <select
            value={activeSortKey}
            onChange={(e) =>
              onSort({
                key: e.target.value as CoverageSortKey,
                dir: defaultDir(e.target.value as CoverageSortKey),
              })
            }
            aria-label={t('coverage.sort.label')}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              padding: '8px 4px',
              cursor: 'pointer',
            }}
          >
            {TOOLBAR_SORT_KEYS.map((k) => (
              <option key={k} value={k}>
                {t(SORT_KEY_LABEL[k])}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() =>
              onSort({
                key: activeSortKey,
                dir: sort?.dir === 'asc' ? 'desc' : 'asc',
              })
            }
            aria-label={t('coverage.sort.toggleDir')}
            style={{
              border: 'none',
              background: 'transparent',
              color: 'var(--primary)',
              cursor: 'pointer',
              fontSize: 11,
              padding: '8px 6px',
            }}
          >
            {sort?.dir === 'asc' ? '▲' : '▼'}
          </button>
        </div>
      </div>
    </div>
  )
}

function GhostButton({
  label,
  onClick,
}: {
  label: string
  onClick: () => void
}): React.ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: '9px 14px',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-md)',
        background: 'var(--bg-card-overlay)',
        color: 'var(--text-secondary)',
        cursor: 'pointer',
        fontSize: 12,
      }}
    >
      {label}
    </button>
  )
}
