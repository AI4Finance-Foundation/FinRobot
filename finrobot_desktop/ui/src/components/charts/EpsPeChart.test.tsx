import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import EpsPeChart from './EpsPeChart'

const SAMPLE_DATA = [
  { year: 2021, eps: 5.67, pe_ratio: 28.5 },
  { year: 2022, eps: 6.15, pe_ratio: 25.0 },
  { year: 2023, eps: 6.42, pe_ratio: 30.2 },
]

describe('EpsPeChart', () => {
  it('renders title', () => {
    render(<EpsPeChart data={SAMPLE_DATA} title="EPS & P/E" />)
    expect(screen.getByText('EPS & P/E')).toBeInTheDocument()
  })

  it('returns null for empty data', () => {
    const { container } = render(<EpsPeChart data={[]} title="Empty" />)
    expect(container.firstChild).toBeNull()
  })

  it('returns null for undefined data', () => {
    const { container } = render(
      <EpsPeChart data={undefined as unknown as Record<string, number | string | boolean | null>[]} title="Null" />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders heading element', () => {
    render(<EpsPeChart data={SAMPLE_DATA} title="EPS & P/E" />)
    const heading = screen.getByText('EPS & P/E')
    expect(heading.tagName).toBe('SPAN')
  })
})
