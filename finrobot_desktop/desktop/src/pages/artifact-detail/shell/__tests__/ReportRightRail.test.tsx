// The version-timeline row is reason-aware, mirroring the chips (TargetRange)
// and the left-rail card: a point target withheld BECAUSE the price sits inside
// the fair-value band (a.fairly_valued) is a confident HOLD → "Fairly Valued",
// while a genuine withhold (M&A / single divergent method) keeps the neutral
// "WITHHELD" token. A published point still shows its dollar target.

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { VersionTimelineList } from '../ReportRightRail'
import type { ArtifactSummaryV5 } from '../../../../types/v5'

function summary(over: Partial<ArtifactSummaryV5> & { id: string }): ArtifactSummaryV5 {
  return {
    ticker: 'AAA',
    cross_tickers: [],
    type: 'equity_research',
    created_at: '2026-06-01T00:00:00+00:00',
    headline: 'h',
    source: 'pipeline:equity_research',
    archived: false,
    ...over,
  }
}

function renderTimeline(timeline: ArtifactSummaryV5[]): void {
  render(
    <MemoryRouter>
      <VersionTimelineList
        ticker="AAA"
        currentArtifactId="none"
        timeline={timeline}
        reportType="equity_research"
      />
    </MemoryRouter>,
  )
}

describe('VersionTimelineList target/withhold label', () => {
  it('in-band withhold (fairly_valued) → "Fairly Valued", not "WITHHELD"', () => {
    renderTimeline([
      summary({
        id: 'in_band',
        target_price: null,
        verdict: 'HOLD',
        fairly_valued: true,
      }),
    ])
    expect(screen.getByText('Fairly Valued')).toBeInTheDocument()
    expect(screen.queryByText('WITHHELD')).toBeNull()
  })

  it('genuine withhold (not fairly_valued) → neutral "WITHHELD", never "Fairly Valued"', () => {
    renderTimeline([
      summary({
        id: 'genuine',
        target_price: null,
        verdict: 'HOLD',
        fairly_valued: false,
      }),
    ])
    expect(screen.getByText('WITHHELD')).toBeInTheDocument()
    expect(screen.queryByText('Fairly Valued')).toBeNull()
  })

  it('legacy row (fairly_valued undefined) falls back to "WITHHELD"', () => {
    renderTimeline([summary({ id: 'legacy', target_price: null })])
    expect(screen.getByText('WITHHELD')).toBeInTheDocument()
    expect(screen.queryByText('Fairly Valued')).toBeNull()
  })

  it('published point target still shows the dollar value', () => {
    renderTimeline([
      summary({ id: 'published', target_price: 300, verdict: 'BUY', fairly_valued: false }),
    ])
    expect(screen.getByText('$300.00')).toBeInTheDocument()
    expect(screen.queryByText('Fairly Valued')).toBeNull()
  })

  it('mixed history renders exactly one "Fairly Valued" — only the in-band row', () => {
    renderTimeline([
      summary({ id: 'published', target_price: 300, fairly_valued: false }),
      summary({ id: 'in_band', target_price: null, fairly_valued: true }),
      summary({ id: 'genuine', target_price: null, fairly_valued: false }),
    ])
    expect(screen.getAllByText('Fairly Valued')).toHaveLength(1)
  })
})
