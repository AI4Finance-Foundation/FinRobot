import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => mockNavigate }
})

// SplineHero injects a remote <script> + WebGL viewer — stub it in jsdom.
vi.mock('../SplineHero', () => ({ SplineHero: () => <div data-testid="spline-stub" /> }))

import { CoverageHero } from './CoverageHero'

function renderHero() {
  return render(
    <MemoryRouter>
      <CoverageHero />
    </MemoryRouter>,
  )
}

describe('CoverageHero', () => {
  beforeEach(() => mockNavigate.mockClear())

  it('drills into /stocks/:ticker on a valid submit (upper-cased)', () => {
    renderHero()
    fireEvent.change(screen.getByLabelText('Ticker symbol'), { target: { value: 'aapl' } })
    fireEvent.click(screen.getByLabelText('Load ticker'))
    expect(mockNavigate).toHaveBeenCalledWith('/stocks/AAPL')
  })

  it('sanitizes input to the ticker charset as you type', () => {
    renderHero()
    const input = screen.getByLabelText('Ticker symbol') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'a@p#l!' } })
    expect(input.value).toBe('APL')
  })

  it('shows an error and does not navigate when the symbol is invalid', () => {
    renderHero()
    const input = screen.getByLabelText('Ticker symbol') as HTMLInputElement
    // 13 chars exceeds the 1–12 limit (fireEvent bypasses maxLength, so this
    // exercises the validator, not just the input cap).
    fireEvent.change(input, { target: { value: 'A'.repeat(13) } })
    fireEvent.submit(input.closest('form')!)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(mockNavigate).not.toHaveBeenCalled()
  })
})
