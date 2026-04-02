import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import WaterfallChart from './WaterfallChart'

const SAMPLE_DATA = [
  { label: 'Revenue', value: 100, is_total: false },
  { label: 'COGS', value: -40, is_total: false },
  { label: 'Gross Profit', value: 60, is_total: true },
  { label: 'OpEx', value: -20, is_total: false },
  { label: 'Net Income', value: 40, is_total: true },
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
      <WaterfallChart data={undefined as unknown as Record<string, number | string | boolean | null>[]} title="Null" />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders heading element', () => {
    render(<WaterfallChart data={SAMPLE_DATA} title="P&L Waterfall" />)
    const heading = screen.getByText('P&L Waterfall')
    expect(heading.tagName).toBe('H4')
  })
})
