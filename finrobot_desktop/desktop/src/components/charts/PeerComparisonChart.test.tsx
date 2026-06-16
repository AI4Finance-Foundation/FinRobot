import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import PeerComparisonChart, { multipleLabel } from './PeerComparisonChart'

const SAMPLE_DATA = [
  { ticker: 'AAPL', ev_ebitda: 22.5, pe_ratio: 28.0, is_target: true },
  { ticker: 'MSFT', ev_ebitda: 25.0, pe_ratio: 32.0, is_target: false },
  { ticker: 'GOOG', ev_ebitda: 18.0, pe_ratio: 24.0, is_target: false },
]

describe('PeerComparisonChart', () => {
  it('renders title', () => {
    render(<PeerComparisonChart data={SAMPLE_DATA} title="Peer Comparison" />)
    expect(screen.getByText('Peer Comparison')).toBeInTheDocument()
  })

  it('returns null for empty data', () => {
    const { container } = render(<PeerComparisonChart data={[]} title="Empty" />)
    expect(container.firstChild).toBeNull()
  })

  it('returns null for undefined data', () => {
    const { container } = render(
      <PeerComparisonChart
        data={undefined as unknown as Record<string, number | string | boolean | null>[]}
        title="Null"
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders heading element', () => {
    render(<PeerComparisonChart data={SAMPLE_DATA} title="Peer Comparison" />)
    const heading = screen.getByText('Peer Comparison')
    expect(heading.tagName).toBe('SPAN')
  })
})

// The bar-top labels plot valuation MULTIPLES, so they MUST carry the "x" suffix
// (e.g. "22.5x") — matching the tooltip's `${v.toFixed(1)}x`. A currency format
// here would be a unit defect.
describe('PeerComparisonChart bar labels — multiples (the "x" suffix)', () => {
  it('formats a multiple with one decimal and a trailing "x"', () => {
    expect(multipleLabel(22.5)).toBe('22.5x')
    expect(multipleLabel(28)).toBe('28.0x')
  })

  it('never emits a currency symbol', () => {
    expect(multipleLabel(22.5)).not.toContain('$')
  })

  it('renders nothing for a missing / non-finite multiple', () => {
    expect(multipleLabel(null)).toBe('')
    expect(multipleLabel(Number.NaN)).toBe('')
    expect(multipleLabel('22.5')).toBe('')
  })
})
