import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import RevenueEbitdaChart from './RevenueEbitdaChart'

const SAMPLE_DATA = [
  { year: 2022, revenue: 50_000_000_000, ebitda: 15_000_000_000, is_forecast: false },
  { year: 2023, revenue: 55_000_000_000, ebitda: 17_000_000_000, is_forecast: false },
  { year: 2024, revenue: 60_000_000_000, ebitda: 19_000_000_000, is_forecast: true },
]

describe('RevenueEbitdaChart', () => {
  it('renders title', () => {
    render(<RevenueEbitdaChart data={SAMPLE_DATA} title="Revenue & EBITDA" />)
    expect(screen.getByText('Revenue & EBITDA')).toBeInTheDocument()
  })

  it('returns null for empty data', () => {
    const { container } = render(<RevenueEbitdaChart data={[]} title="Empty" />)
    expect(container.firstChild).toBeNull()
  })

  it('returns null for undefined data', () => {
    const { container } = render(
      <RevenueEbitdaChart
        data={undefined as unknown as Record<string, number | string | boolean | null>[]}
        title="Null"
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders container with correct styling', () => {
    render(<RevenueEbitdaChart data={SAMPLE_DATA} title="Revenue & EBITDA" />)
    const heading = screen.getByText('Revenue & EBITDA')
    expect(heading.tagName).toBe('SPAN')
  })
})
