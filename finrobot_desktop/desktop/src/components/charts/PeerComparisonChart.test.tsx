import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import PeerComparisonChart from './PeerComparisonChart'

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
      <PeerComparisonChart data={undefined as unknown as Record<string, number | string | boolean | null>[]} title="Null" />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders heading element', () => {
    render(<PeerComparisonChart data={SAMPLE_DATA} title="Peer Comparison" />)
    const heading = screen.getByText('Peer Comparison')
    expect(heading.tagName).toBe('SPAN')
  })
})
