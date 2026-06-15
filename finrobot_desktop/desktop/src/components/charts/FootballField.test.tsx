import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import FootballField from './FootballField'
import type { HistoricalBandShape } from '../../pages/artifact-detail/chapters/types'

const SAMPLE_DATA = [
  { method: 'DCF', low: 120, mid: 155, high: 190 },
  { method: 'Comps EV/EBITDA', low: 130, mid: 160, high: 185 },
  { method: 'Comps P/E', low: 115, mid: 145, high: 175 },
]

// Canonical method keys (what the backend emits) — the rail matches on these.
const KEYED_ROWS = [
  { method: 'dcf', low: 120, mid: 155, high: 190 },
  { method: 'ev_ebitda', low: 130, mid: 160, high: 185 },
]

const EV_BAND: HistoricalBandShape = {
  metric: 'ev_ebitda',
  current: 15,
  p25: 22,
  median: 24,
  p75: 26,
  p90: 29,
  sample_count: 751,
  classification: 'cheap',
}

// The P25 multiple "22.0×" is rendered ONLY by the rail (price bars use $),
// so its presence is a clean, i18n-independent signal that the rail mounted.
const RAIL_SIGNAL = /22\.0×/

describe('FootballField', () => {
  it('renders title', () => {
    render(<FootballField data={SAMPLE_DATA} title="Football Field" />)
    expect(screen.getByText('Football Field')).toBeInTheDocument()
  })

  it('returns null for empty data', () => {
    const { container } = render(<FootballField data={[]} title="Empty" />)
    expect(container.firstChild).toBeNull()
  })

  it('returns null for undefined data', () => {
    const { container } = render(
      <FootballField
        data={undefined as unknown as Record<string, number | string | boolean | null>[]}
        title="Null"
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders heading element', () => {
    render(<FootballField data={SAMPLE_DATA} title="Football Field" />)
    const heading = screen.getByText('Football Field')
    expect(heading.tagName).toBe('SPAN')
  })
})

describe('FootballField historical-band provenance rail', () => {
  it('renders the rail when the band metric matches a rendered method', () => {
    const { container } = render(
      <FootballField data={KEYED_ROWS} title="FF" historicalBand={EV_BAND} />,
    )
    expect(container.textContent).toMatch(RAIL_SIGNAL)
    // Classification badge surfaces (en catalog → "cheap").
    expect(container.textContent).toMatch(/15\.0×/) // current multiple marker
  })

  it('hides the rail when the band metric matches no rendered method', () => {
    // p_fcf band but only dcf/ev_ebitda methods are plotted → orphan band, no rail.
    const { container } = render(
      <FootballField
        data={KEYED_ROWS}
        title="FF"
        historicalBand={{ ...EV_BAND, metric: 'p_fcf' }}
      />,
    )
    expect(container.textContent).not.toMatch(RAIL_SIGNAL)
  })

  it('hides the rail when core band stats are non-finite', () => {
    const { container } = render(
      <FootballField data={KEYED_ROWS} title="FF" historicalBand={{ ...EV_BAND, p25: null }} />,
    )
    expect(container.textContent).not.toMatch(RAIL_SIGNAL)
  })

  it('renders the plot but no rail when no band is supplied (back-compat)', () => {
    const { container } = render(<FootballField data={KEYED_ROWS} title="FF" />)
    expect(screen.getByText('FF')).toBeInTheDocument()
    expect(container.textContent).not.toMatch(RAIL_SIGNAL)
  })
})

describe('FootballField calibrated synthesis target overlay', () => {
  // 172 is not a method low/mid/high in KEYED_ROWS, so "$172" is a clean signal
  // that the weighted-target marker mounted (price-space, same axis as the bars).
  it('overlays the weighted-target marker on the price axis', () => {
    const { container } = render(
      <FootballField
        data={KEYED_ROWS}
        title="FF"
        targetBand={{ low: 148, high: 178, point: 172 }}
      />,
    )
    expect(container.textContent).toMatch(/\$172/)
  })

  it('draws the marker even when the band ends are absent (point only)', () => {
    const { container } = render(
      <FootballField data={KEYED_ROWS} title="FF" targetBand={{ point: 172 }} />,
    )
    expect(container.textContent).toMatch(/\$172/)
  })

  it('omits the target overlay when no target band is supplied', () => {
    const { container } = render(<FootballField data={KEYED_ROWS} title="FF" />)
    expect(container.textContent).not.toMatch(/\$172/)
  })
})
