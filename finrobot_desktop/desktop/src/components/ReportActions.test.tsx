import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ReportActions from './ReportActions'

describe('ReportActions', () => {
  it('renders view and download buttons', () => {
    render(<ReportActions ticker="AAPL" />)
    expect(screen.getByText('View Full Report')).toBeInTheDocument()
    expect(screen.getByText('Download PDF')).toBeInTheDocument()
  })

  it('disables buttons when no ticker', () => {
    render(<ReportActions ticker="" />)
    const buttons = screen.getAllByRole('button')
    buttons.forEach(btn => expect(btn).toBeDisabled())
  })
})
