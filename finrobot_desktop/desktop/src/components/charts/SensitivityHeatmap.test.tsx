import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import SensitivityHeatmap from './SensitivityHeatmap'

const SAMPLE_DATA = [
  { wacc: 0.08, tg: 0.02, implied_price: 150 },
  { wacc: 0.08, tg: 0.025, implied_price: 170 },
  { wacc: 0.09, tg: 0.02, implied_price: 130 },
  { wacc: 0.09, tg: 0.025, implied_price: 145 },
  { wacc: 0.10, tg: 0.02, implied_price: 110 },
  { wacc: 0.10, tg: 0.025, implied_price: 125 },
]

describe('SensitivityHeatmap', () => {
  it('renders title', () => {
    render(<SensitivityHeatmap data={SAMPLE_DATA} title="Sensitivity Analysis" />)
    expect(screen.getByText('Sensitivity Analysis')).toBeInTheDocument()
  })

  it('returns null for empty data', () => {
    const { container } = render(<SensitivityHeatmap data={[]} title="Empty" />)
    expect(container.firstChild).toBeNull()
  })

  it('returns null for undefined data', () => {
    const { container } = render(
      <SensitivityHeatmap data={undefined as unknown as Record<string, number | string | boolean | null>[]} title="Null" />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders a table with correct structure', () => {
    render(<SensitivityHeatmap data={SAMPLE_DATA} title="Sensitivity" />)
    const table = screen.getByRole('table')
    expect(table).toBeInTheDocument()
  })

  it('renders WACC row labels as percentages', () => {
    render(<SensitivityHeatmap data={SAMPLE_DATA} title="Sensitivity" />)
    expect(screen.getByText('8.0%')).toBeInTheDocument()
    expect(screen.getByText('9.0%')).toBeInTheDocument()
    expect(screen.getByText('10.0%')).toBeInTheDocument()
  })

  it('renders implied prices in cells', () => {
    render(<SensitivityHeatmap data={SAMPLE_DATA} title="Sensitivity" />)
    expect(screen.getByText('$150')).toBeInTheDocument()
    expect(screen.getByText('$110')).toBeInTheDocument()
  })
})
