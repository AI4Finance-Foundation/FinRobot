// CoverageCardGrid — the workspace's main surface: a responsive wall of ticker
// slabs. Columns auto-fill at a ~240px min track (≈5 across on a typical window,
// more on a wide monitor, fewer when narrow) so cards stay compact and readable
// without ever cramping or clipping; compare peers side-by-side, then scroll
// vertically for the rest. auto-FILL (not auto-fit) keeps a short final row at
// normal card width instead of stretching a lone card across the whole row.

import { useI18n } from '../../i18n'
import { CoverageCard } from './CoverageCard'
import type { CoverageRow } from '../../api/coverage'
import type { CoverageDensity } from '../../stores/coverageStore'

interface Props {
  rows: CoverageRow[]
  density: CoverageDensity
  marketPending?: boolean
  onOpen: (ticker: string) => void
}

export function CoverageCardGrid({
  rows,
  density,
  marketPending = false,
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
        gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
        // Each row sizes to its tallest card's FULL content. Without this the
        // implicit rows defaulted to `auto`, which sized a minHeight:244 flex
        // card to 244 (not its ~330 content) — the card then overflowed its row
        // track and overlapped the next row, covering the run/open buttons.
        gridAutoRows: 'max-content',
        gap: compact ? 12 : 16,
        justifyContent: 'stretch',
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
          marketPending={marketPending}
          onOpen={onOpen}
        />
      ))}
    </div>
  )
}
