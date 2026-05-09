import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import CompanyRadarChart from './CompanyRadarChart'

const SAMPLE_DATA = [
  { dimension: 'Growth', value: 85, benchmark: 70 },
  { dimension: 'Profitability', value: 72, benchmark: 65 },
  { dimension: 'Leverage', value: 60, benchmark: 55 },
  { dimension: 'Liquidity', value: 90, benchmark: 80 },
  { dimension: 'Valuation', value: 55, benchmark: 60 },
]

describe('CompanyRadarChart', () => {
  it('renders title', () => {
    render(<CompanyRadarChart data={SAMPLE_DATA} title="Company Radar" />)
    expect(screen.getByText('Company Radar')).toBeInTheDocument()
  })

  it('returns null for empty data', () => {
    const { container } = render(<CompanyRadarChart data={[]} title="Empty" />)
    expect(container.firstChild).toBeNull()
  })

  it('returns null for undefined data', () => {
    const { container } = render(
      <CompanyRadarChart data={undefined as unknown as Record<string, number | string | boolean | null>[]} title="Null" />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders heading element', () => {
    render(<CompanyRadarChart data={SAMPLE_DATA} title="Company Radar" />)
    const heading = screen.getByText('Company Radar')
    expect(heading.tagName).toBe('SPAN')
  })
})
