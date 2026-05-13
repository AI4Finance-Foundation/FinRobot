import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import FootballField from './FootballField'

const SAMPLE_DATA = [
  { method: 'DCF', low: 120, mid: 155, high: 190 },
  { method: 'Comps EV/EBITDA', low: 130, mid: 160, high: 185 },
  { method: 'Comps P/E', low: 115, mid: 145, high: 175 },
]

describe('FootballField', () => {
  it('renders title', () => {
    render(<FootballField data={SAMPLE_DATA} title="Football Field" />)
    expect(screen.getByText('Football Field')).toBeInTheDocument()
  })

  it('returns null for empty data', () => {
    const { container } = render(<FootballField data={[]} title="Empty" />)
    expect(container.firstChild).toBeNull()
  })

  it('returns null for undefined data', () => {
    const { container } = render(
      <FootballField data={undefined as unknown as Record<string, number | string | boolean | null>[]} title="Null" />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders heading element', () => {
    render(<FootballField data={SAMPLE_DATA} title="Football Field" />)
    const heading = screen.getByText('Football Field')
    expect(heading.tagName).toBe('SPAN')
  })
})
