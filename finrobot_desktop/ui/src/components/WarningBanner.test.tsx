// Vitest coverage for WarningBanner — backend `warnings` array MUST be
// surfaced visibly; this gate prevents future regressions where it gets
// rendered to innerHTML but with display:none or zero-contrast styling.

import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import { WarningBanner } from './WarningBanner'

describe('WarningBanner', () => {
  it('renders nothing when warnings is null/undefined/empty', () => {
    const { container: nullCt } = render(<WarningBanner warnings={null} />)
    expect(nullCt.firstChild).toBeNull()
    const { container: undefCt } = render(<WarningBanner warnings={undefined} />)
    expect(undefCt.firstChild).toBeNull()
    const { container: emptyCt } = render(<WarningBanner warnings={[]} />)
    expect(emptyCt.firstChild).toBeNull()
  })

  it('filters out blank/whitespace-only entries', () => {
    const { container } = render(<WarningBanner warnings={['', '   ', '\t\n']} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders single warning inline', () => {
    render(<WarningBanner warnings={['FMP returned 3 quarterly rows; TTM may be incomplete']} />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(
      screen.getByText(/FMP returned 3 quarterly rows; TTM may be incomplete/),
    ).toBeInTheDocument()
    // Single warning → no expand button
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('shows first + collapsible "more" toggle for multiple warnings', () => {
    render(
      <WarningBanner
        warnings={[
          'First warning visible by default',
          'Second hidden until expand',
          'Third also hidden',
        ]}
      />,
    )
    expect(screen.getByText(/First warning visible by default/)).toBeInTheDocument()
    expect(screen.queryByText(/Second hidden until expand/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /\+2 more/ }))
    expect(screen.getByText(/Second hidden until expand/)).toBeInTheDocument()
    expect(screen.getByText(/Third also hidden/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Collapse/ }))
    expect(screen.queryByText(/Second hidden until expand/)).not.toBeInTheDocument()
  })

  it('uses danger tone testid when explicit', () => {
    render(<WarningBanner warnings={['stale cache used']} tone="danger" />)
    expect(screen.getByTestId('warning-banner-danger')).toBeInTheDocument()
  })

  it('uses warn tone by default', () => {
    render(<WarningBanner warnings={['delayed quotes']} />)
    expect(screen.getByTestId('warning-banner-warn')).toBeInTheDocument()
  })
})
