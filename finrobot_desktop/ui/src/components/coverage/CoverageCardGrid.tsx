// CoverageCardGrid — the workspace's main surface: a responsive wall of fixed
// height ticker cards. Column count is auto-derived from the container's own
// width via auto-fill + minmax (comfort floor 260, compact 210) — NOT a fixed
// repeat(3/4). A fixed column count with a min track wider than the available
// space forced horizontal clipping the moment the AI panel + inspector ate into
// the width (BUG: GOOGL sliced off at the default 1200 window). auto-fill lets
// the wall fall back to 1 column at any width, so it only ever scrolls
// vertically. The grid lays out + scrolls; cards render in full (no windowing —
// a coverage desk holds tens to low-hundreds of tickers; a true 1000+ wall would
// want real list virtualization).

import { useI18n } from '../../i18n'
import { CoverageCard } from './CoverageCard'
import type { CoverageRow } from '../../api/coverage'
import type { CoverageDensity } from '../../stores/coverageStore'

interface Props {
  rows: CoverageRow[]
  density: CoverageDensity
  focusedTicker: string | null
  selected: string[]
  marketPending?: boolean
  onFocus: (ticker: string) => void
  onToggleSelect: (ticker: string) => void
  onRun: (ticker: string) => void
  onOpen: (ticker: string) => void
}

export function CoverageCardGrid({
  rows,
  density,
  focusedTicker,
  selected,
  marketPending = false,
  onFocus,
  onToggleSelect,
  onRun,
  onOpen,
}: Props): React.ReactElement {
  const { t } = useI18n()
  const compact = density === 'compact'

  if (rows.length === 0) {
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
        {t('coverage.filterEmpty')}
      </div>
    )
  }

  return (
    <div
      data-testid="coverage-card-grid"
      style={{
        display: 'grid',
        gridTemplateColumns: compact
          ? 'repeat(auto-fill, minmax(210px, 1fr))'
          : 'repeat(auto-fill, minmax(260px, 1fr))',
        gap: 12,
        alignContent: 'start',
        height: '100%',
        overflow: 'auto',
        paddingRight: 2,
      }}
    >
      {rows.map((row) => (
        <CoverageCard
          key={row.ticker}
          row={row}
          density={density}
          focused={focusedTicker === row.ticker}
          selected={selected.includes(row.ticker)}
          marketPending={marketPending}
          onFocus={onFocus}
          onToggleSelect={onToggleSelect}
          onRun={onRun}
          onOpen={onOpen}
        />
      ))}
    </div>
  )
}
