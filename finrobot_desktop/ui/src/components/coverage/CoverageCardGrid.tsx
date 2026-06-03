// CoverageCardGrid — the workspace's main surface: a responsive wall of fixed
// height ticker cards. 3 columns in comfort, 4 in compact (redesign spec). The
// grid only lays out + scrolls; each card self-windows via content-visibility
// (CoverageCard), so 100+ tickers stay smooth without a virtualization library.

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
          ? 'repeat(4, minmax(210px, 1fr))'
          : 'repeat(3, minmax(260px, 1fr))',
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
