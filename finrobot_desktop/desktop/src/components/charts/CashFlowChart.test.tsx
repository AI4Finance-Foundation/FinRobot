import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import CashFlowChart, { formatBillions, barLabel } from './CashFlowChart'

const SAMPLE_DATA = [
  { year: '2023', operating: 110e9, investing: -90e9, financing: -10e9 },
  { year: '2024', operating: 122e9, investing: -85e9, financing: -12e9 },
]

describe('CashFlowChart', () => {
  it('renders title', () => {
    render(<CashFlowChart data={SAMPLE_DATA} title="Cash Flow" />)
    expect(screen.getByText('Cash Flow')).toBeInTheDocument()
  })

  it('returns null for empty data', () => {
    const { container } = render(<CashFlowChart data={[]} title="Empty" />)
    expect(container.firstChild).toBeNull()
  })
})

// The bar-top labels reuse the chart's currency formatter (cash flows are large
// CURRENCY magnitudes — never multiples, so NO "x" suffix). `barLabel` is the
// LabelList formatter; it must format currency-compactly and suppress $0 bars.
describe('CashFlowChart bar labels — currency (not multiples)', () => {
  it('formats billions/millions compactly, never with an "x"', () => {
    expect(formatBillions(110e9)).toBe('110.0B')
    expect(formatBillions(-90e9)).toBe('-90.0B')
    expect(formatBillions(4.5e6)).toBe('5M')
    expect(formatBillions(110e9)).not.toContain('x')
  })

  it('barLabel suppresses a zero-value component bar (no "0" stamped on the axis)', () => {
    expect(barLabel(0)).toBe('')
    expect(barLabel(110e9)).toBe('110.0B')
    expect(barLabel(-90e9)).toBe('-90.0B')
    expect(barLabel('not a number')).toBe('')
  })
})
