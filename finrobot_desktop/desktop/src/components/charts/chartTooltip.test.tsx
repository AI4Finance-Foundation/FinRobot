import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CosmicTooltip } from './chartTooltip'

// The shared tooltip stamps a "Projected" footer when the hovered point is an
// engine forecast (row.is_forecast), making the projection-vs-reported seam
// explicit inside any chart. Reported rows carry no flag → no footer.
const row = (is_forecast: boolean) => [
  {
    value: 100,
    name: 'Revenue',
    dataKey: 'revenue',
    color: 'var(--primary)',
    payload: { is_forecast },
  },
]

describe('CosmicTooltip — projected-point provenance footer', () => {
  it('stamps a Projected footer on a forecast point', () => {
    render(<CosmicTooltip active payload={row(true)} label="2026" format={(v) => `$${v}`} />)
    expect(screen.getByText(/Projected/i)).toBeInTheDocument()
  })

  it('shows no footer for a reported point', () => {
    render(<CosmicTooltip active payload={row(false)} label="2024" format={(v) => `$${v}`} />)
    expect(screen.queryByText(/Projected/i)).not.toBeInTheDocument()
  })

  it('renders nothing when inactive', () => {
    const { container } = render(
      <CosmicTooltip active={false} payload={row(true)} label="2026" format={(v) => `$${v}`} />,
    )
    expect(container.firstChild).toBeNull()
  })
})
