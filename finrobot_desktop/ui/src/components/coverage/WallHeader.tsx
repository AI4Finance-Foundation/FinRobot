// WallHeader — the card wall's single slim control row, replacing the old
// CoverageToolbar band. Two things only: a 3-segment triage control on the left,
// and a compact sort control on the right. Everything the old toolbar carried
// is gone or demoted:
// the workspace switcher (there is one Studied Tickers list, no groups in the
// UX), add-ticker flow (owned by Research), density (one shipped density), and
// the has_reports/not_run pills (the card self-reports those). Counts come from
// the page, computed over the full row set so each segment is honest.

import { useI18n } from '../../i18n'
import { COVERAGE_FILTERS, type CoverageFilter } from './coverageFilter'
import {
  TOOLBAR_SORT_KEYS,
  defaultDir,
  type CoverageSort,
  type CoverageSortKey,
} from './coverageSort'

interface Props {
  filter: CoverageFilter
  filterCounts: Record<CoverageFilter, number>
  onFilter: (f: CoverageFilter) => void
  sort: CoverageSort
  onSort: (sort: CoverageSort) => void
}

const FILTER_KEY: Record<CoverageFilter, string> = {
  needs_action: 'coverage.filter.needsAction',
  running: 'coverage.filter.running',
  all: 'coverage.filter.all',
}

// Archive order: everything first, with urgent and running lenses still nearby.
const TRIAGE_ORDER: CoverageFilter[] = ['all', 'needs_action', 'running']

const SORT_KEY_LABEL: Record<string, string> = {
  needs_action: 'coverage.sort.needsAction',
  ticker: 'coverage.sort.ticker',
  latest_report: 'coverage.sort.latestReport',
  upside_to_target_live: 'coverage.sort.upside',
}

export function WallHeader({
  filter,
  filterCounts,
  onFilter,
  sort,
  onSort,
}: Props): React.ReactElement {
  const { t } = useI18n()
  // Defensive: render only the triage lenses we ship, in triage order.
  const segments = TRIAGE_ORDER.filter((f) => COVERAGE_FILTERS.includes(f))

  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 10,
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 12,
        flexShrink: 0,
      }}
    >
      {/* Triage segments — the landing question. Needs Action reads amber. */}
      <div
        style={{
          display: 'inline-flex',
          gap: 2,
          padding: 3,
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          background: 'var(--bg-card-overlay)',
        }}
      >
        {segments.map((f) => {
          const active = filter === f
          const warn = f === 'needs_action'
          return (
            <button
              key={f}
              type="button"
              onClick={() => onFilter(f)}
              aria-pressed={active}
              style={{
                padding: '6px 12px',
                borderRadius: 'var(--radius-sm)',
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                whiteSpace: 'nowrap',
                cursor: 'pointer',
                border: 'none',
                background: active
                  ? warn
                    ? 'var(--warning-soft)'
                    : 'var(--primary-soft)'
                  : 'transparent',
                boxShadow: active ? 'inset 0 0 0 1px var(--border-glow)' : 'none',
                color: active
                  ? warn
                    ? 'var(--accent-amber)'
                    : 'var(--text-primary)'
                  : 'var(--text-muted)',
              }}
            >
              {t(FILTER_KEY[f])} · {filterCounts[f]}
            </button>
          )
        })}
      </div>

      {/* Sort — a key + a direction toggle. Default needs_action/desc, so most
          sessions never touch it; it stays compact and out of the way. */}
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
        <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 10 }}>
          {t('coverage.sort.label')}
        </span>
        <select
          value={sort.key}
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
          onClick={() => onSort({ key: sort.key, dir: sort.dir === 'asc' ? 'desc' : 'asc' })}
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
          {sort.dir === 'asc' ? '▲' : '▼'}
        </button>
      </div>
    </div>
  )
}
