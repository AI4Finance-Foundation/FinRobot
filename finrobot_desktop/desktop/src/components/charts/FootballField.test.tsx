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
  // that the headline-target marker mounted (price-space, same axis as the bars).
  it('overlays the headline-target marker on the price axis', () => {
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

// 🔴 Surface gate #2 (render): the ONLY number the football field labels "Target"
// is targetBand.point. When the headline is anchored ($188) the DISCARDED weighted
// blend ($209) can still surface as a method-bar mid — but it must NEVER carry a
// "Target" label. This is the render half of the price-split double gate (the data
// half lives in ChapterValuation.test.tsx): together they lock "anchor active ⇒
// every 'Target' surface points at the anchor value, never the blend".
describe('FootballField "Target" label points only at the headline point', () => {
  // dcf mid = $188 is the anchored headline; ev_ebitda mid = $209 is the discarded
  // blend value surfacing as a method bar (fmtPrice rounds ≥$100 to whole dollars,
  // so 188.31→"$188" and 208.65→"$209" — the exact strings the bug displayed).
  const ANCHOR_ROWS = [
    { method: 'dcf', low: 165, mid: 188, high: 200 },
    { method: 'ev_ebitda', low: 195, mid: 209, high: 260 },
  ]

  it('labels only the headline point "Target"; the discarded blend value carries no Target label', () => {
    render(
      <FootballField
        data={ANCHOR_ROWS}
        title="FF"
        currentPrice={210.02}
        targetBand={{ low: 170, high: 205, point: 188 }}
      />,
    )
    // (b) Every visible node containing "Target" shows the headline $188 — never $209.
    const targetNodes = screen.getAllByText(/Target/)
    expect(targetNodes.length).toBeGreaterThan(0)
    for (const n of targetNodes) {
      expect(n.textContent).toMatch(/\$188\b/)
      expect(n.textContent).not.toMatch(/\$209\b/)
    }
    // (c) The discarded blend value $209 is present (as a method mid) but no node
    // that shows it is labelled "Target".
    const blendNodes = screen.getAllByText(/\$209/)
    expect(blendNodes.length).toBeGreaterThan(0)
    for (const n of blendNodes) {
      expect(n.textContent).not.toMatch(/Target/)
    }
  })
})
