import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import MarginTrendChart from './MarginTrendChart'

const SAMPLE_DATA = [
  { year: 2021, gross_margin: 0.45, ebitda_margin: 0.28, operating_margin: 0.22 },
  { year: 2022, gross_margin: 0.47, ebitda_margin: 0.3, operating_margin: 0.24 },
  { year: 2023, gross_margin: 0.48, ebitda_margin: 0.31, operating_margin: 0.25 },
]

describe('MarginTrendChart', () => {
  it('renders title', () => {
    render(<MarginTrendChart data={SAMPLE_DATA} title="Margin Trends" />)
    expect(screen.getByText('Margin Trends')).toBeInTheDocument()
  })

  it('returns null for empty data', () => {
    const { container } = render(<MarginTrendChart data={[]} title="Empty" />)
    expect(container.firstChild).toBeNull()
  })

  it('returns null for undefined data', () => {
    const { container } = render(
      <MarginTrendChart
        data={undefined as unknown as Record<string, number | string | boolean | null>[]}
        title="Null"
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders heading element', () => {
    render(<MarginTrendChart data={SAMPLE_DATA} title="Margin Trends" />)
    const heading = screen.getByText('Margin Trends')
    expect(heading.tagName).toBe('SPAN')
  })
})
