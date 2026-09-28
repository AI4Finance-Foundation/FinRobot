import { describe, it, expect, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import WaterfallChart, { buildWaterfallBars } from './WaterfallChart'

const SAMPLE_DATA = [
  { label: 'Revenue', value: 100, is_total: false },
  { label: 'COGS', value: -40, is_total: false },
  { label: 'Gross Profit', value: 60, is_total: true },
  { label: 'OpEx', value: -20, is_total: false },
  { label: 'Net Income', value: 40, is_total: true },
]

// AAPL-magnitude DCF bridge (units in $B): PV(FCF) 900 + PV(Terminal) 1860 =
// EV 2760, less $16B net debt = equity 2744. Mirrors the production shape
// that exposed BUG-8: every non-first bar rendered from $0 instead of
// floating from the prior running total.
const DCF_BRIDGE_DATA = [
  { label: 'PV(FCF)', value: 900, is_total: false },
  { label: 'PV(Terminal)', value: 1860, is_total: false },
  { label: 'Enterprise Value', value: 2760, is_total: true },
  { label: 'Less: Net Debt', value: -16, is_total: false },
  { label: 'Equity Value', value: 2744, is_total: true },
]

// A net-cash company (equity value > enterprise value): the bridge adds
// cash back instead of subtracting debt, so the component row is positive.
// A "total" row is a checkpoint of the accumulated component deltas (it does
// NOT reset the running total to its own literal value) — so, like real DCF
// bridge data, it must be preceded by the component rows that sum to it.
const NET_CASH_BRIDGE_DATA = [
  { label: 'PV(FCF)', value: 60, is_total: false },
  { label: 'PV(Terminal)', value: 40, is_total: false },
  { label: 'Enterprise Value', value: 100, is_total: true },
  { label: 'Plus: Net Cash', value: 5, is_total: false },
  { label: 'Equity Value', value: 105, is_total: true },
]

// A component row that nets to exactly zero (e.g. a fully offset add/sub) —
// must not render a negative-height or NaN "ghost" bar.
const ZERO_VALUE_ROW_DATA = [
  { label: 'PV(FCF)', value: 60, is_total: false },
  { label: 'PV(Terminal)', value: 40, is_total: false },
  { label: 'Enterprise Value', value: 100, is_total: true },
  { label: 'Adjustment', value: 0, is_total: false },
  { label: 'Equity Value', value: 100, is_total: true },
]

describe('WaterfallChart', () => {
  it('renders title', () => {
    render(<WaterfallChart data={SAMPLE_DATA} title="P&L Waterfall" />)
    expect(screen.getByText('P&L Waterfall')).toBeInTheDocument()
  })

  it('returns null for empty data', () => {
    const { container } = render(<WaterfallChart data={[]} title="Empty" />)
    expect(container.firstChild).toBeNull()
  })

  it('returns null for undefined data', () => {
    const { container } = render(
      <WaterfallChart
        data={undefined as unknown as Record<string, number | string | boolean | null>[]}
        title="Null"
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders heading element', () => {
    render(<WaterfallChart data={SAMPLE_DATA} title="P&L Waterfall" />)
    const heading = screen.getByText('P&L Waterfall')
    expect(heading.tagName).toBe('SPAN')
  })
})

describe('buildWaterfallBars — floating-brick stacking semantics', () => {
  // BUG-8 regression: component bars must stack as (base = prior running
  // total, delta = own contribution), NOT (base = 0, delta = cumulative).
  // Only the very first row legitimately has base 0.
  it('floats every component bar from the prior running total, not from $0', () => {
    const bars = buildWaterfallBars(DCF_BRIDGE_DATA)

    expect(bars[0]).toMatchObject({ label: 'PV(FCF)', base: 0, delta: 900 })
    // PV(Terminal) must float from 900 (PV(FCF)'s cumulative), not from 0.
    expect(bars[1]).toMatchObject({ label: 'PV(Terminal)', base: 900, delta: 1860 })
    // Total bars always draw the full checkpoint height from $0.
    expect(bars[2]).toMatchObject({
      label: 'Enterprise Value',
      is_total: true,
      base: 0,
      delta: 2760,
    })
    // Net Debt is a thin brick near the top: base = equity (2744), delta = 16
    // — NOT base 0 / delta 2760 (which is what painted the full-height red
    // bar in production).
    expect(bars[3]).toMatchObject({ label: 'Less: Net Debt', base: 2744, delta: 16 })
    expect(bars[4]).toMatchObject({ label: 'Equity Value', is_total: true, base: 0, delta: 2744 })
  })

  it('floats an add (net-cash) row upward from the prior total with the positive fill', () => {
    const bars = buildWaterfallBars(NET_CASH_BRIDGE_DATA)
    const netCash = bars[3]
    expect(netCash).toMatchObject({ label: 'Plus: Net Cash', base: 100, delta: 5, labelValue: 5 })
    expect(netCash.fill).toBe('var(--success)')
    // Equity total checkpoint reflects the added cash.
    expect(bars[4]).toMatchObject({ is_total: true, base: 0, delta: 105 })
  })

  it('subtracts a net-debt row downward from the prior total with the negative fill', () => {
    const bars = buildWaterfallBars([
      { label: 'PV(FCF)', value: 60, is_total: false },
      { label: 'PV(Terminal)', value: 40, is_total: false },
      { label: 'Enterprise Value', value: 100, is_total: true },
      { label: 'Less: Net Debt', value: -5, is_total: false },
      { label: 'Equity Value', value: 95, is_total: true },
    ])
    const netDebt = bars[3]
    expect(netDebt).toMatchObject({ label: 'Less: Net Debt', base: 95, delta: 5, labelValue: -5 })
    expect(netDebt.fill).toBe('var(--danger)')
  })

  it('renders a zero-value component row as a zero-height brick, not a ghost', () => {
    const bars = buildWaterfallBars(ZERO_VALUE_ROW_DATA)
    const adjustment = bars[3]
    expect(adjustment.label).toBe('Adjustment')
    expect(adjustment.delta).toBe(0)
    expect(adjustment.base).toBe(100)
    expect(Number.isNaN(adjustment.base)).toBe(false)
    expect(Number.isNaN(adjustment.delta)).toBe(false)
  })
})

describe('WaterfallChart — rendered DOM (regression guard for the base-bar fill leak)', () => {
  // BUG-8 root cause: Recharts prioritizes a datum's own `fill` field over a
  // Bar's component-level `fill` prop. Every WaterfallBar row carries a
  // `fill` (used by the visible delta bar's per-index <Cell>), and since both
  // the invisible "base" bar and the visible "delta" bar shared that same
  // data array, the "base" bar silently inherited the row's real color
  // instead of staying transparent — painting a solid full-height rectangle
  // behind the correct floating segment. Guarded here by asserting the base
  // bar's rendered path fill stays "transparent" for every row that has one.
  // jsdom reports 0 layout dimensions by default, and Recharts' ResponsiveContainer
  // skips rendering its children entirely at zero size — so give it a concrete
  // box to measure, matching the card's real rendered width/height.
  beforeAll(() => {
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 600 })
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: 260 })
    HTMLElement.prototype.getBoundingClientRect = function () {
      return {
        width: 600,
        height: 260,
        top: 0,
        left: 0,
        right: 600,
        bottom: 260,
        x: 0,
        y: 0,
        toJSON() {},
      } as DOMRect
    }
  })

  it('keeps every base-bar path transparent even though the data rows carry real fill colors', () => {
    const { container } = render(<WaterfallChart data={DCF_BRIDGE_DATA} title="DCF Bridge" />)
    const barGroups = container.querySelectorAll('g.recharts-bar')
    expect(barGroups.length).toBe(2)
    const baseGroup = barGroups[0]
    const basePaths = Array.from(baseGroup.querySelectorAll('.recharts-bar-rectangle path'))
    expect(basePaths.length).toBeGreaterThan(0)
    basePaths.forEach((p) => {
      expect(p.getAttribute('fill')).toBe('transparent')
    })
  })

  it('reserves top margin so bar-top value labels are not clipped against the plot area', () => {
    const { container } = render(<WaterfallChart data={DCF_BRIDGE_DATA} title="DCF Bridge" />)
    const clipRect = container.querySelector('clipPath rect')
    // Recharts' un-configured default top margin is ~5px, which clipped the
    // total bars' labels (they draw at ~the Y-domain max, right at the plot
    // area's top edge). 24px of headroom fixes it; guard against a regression
    // back toward the default.
    expect(Number(clipRect?.getAttribute('y'))).toBeGreaterThanOrEqual(20)
  })
})
