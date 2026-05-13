import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import PriceChart from './PriceChart'

const SAMPLE_DATA = [
  { date: '2024-01-02', close: 185.5, volume: 45_000_000 },
  { date: '2024-01-03', close: 187.2, volume: 38_000_000 },
  { date: '2024-01-04', close: 184.8, volume: 42_000_000 },
]

describe('PriceChart', () => {
  it('renders title', () => {
    render(<PriceChart data={SAMPLE_DATA} title="Price & Volume" />)
    expect(screen.getByText('Price & Volume')).toBeInTheDocument()
  })

  it('returns null for empty data', () => {
    const { container } = render(<PriceChart data={[]} title="Empty" />)
    expect(container.firstChild).toBeNull()
  })

  it('returns null for undefined data', () => {
    const { container } = render(
      <PriceChart data={undefined as unknown as Record<string, number | string | boolean | null>[]} title="Null" />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders heading element', () => {
    render(<PriceChart data={SAMPLE_DATA} title="Price & Volume" />)
    const heading = screen.getByText('Price & Volume')
    expect(heading.tagName).toBe('SPAN')
  })
})
