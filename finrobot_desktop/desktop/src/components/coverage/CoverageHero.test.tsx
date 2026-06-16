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

// The debounced search hook is unit-tested separately (useTickerSearch.test.ts);
// stub it here so the dropdown is driven deterministically, no network/timers.
vi.mock('../../hooks/useTickerSearch', () => ({ useTickerSearch: vi.fn(() => []) }))

import { CoverageHero } from './CoverageHero'
import { useTickerSearch } from '../../hooks/useTickerSearch'

const mockSuggest = vi.mocked(useTickerSearch)
const SUGGESTIONS = [
  { symbol: 'AAPL', name: 'Apple Inc.' },
  { symbol: 'AMAT', name: 'Applied Materials' },
]

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
    fireEvent.click(screen.getByLabelText('Analyze'))
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

describe('CoverageHero typeahead', () => {
  beforeEach(() => {
    mockNavigate.mockClear()
    mockSuggest.mockReturnValue([])
  })

  function focusType(value: string): HTMLElement {
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value } })
    return input
  }

  it('opens the dropdown only once focused with matching suggestions', () => {
    mockSuggest.mockReturnValue(SUGGESTIONS)
    renderHero()
    expect(screen.queryByTestId('ticker-suggestions')).toBeNull()
    focusType('ap')
    expect(screen.getByTestId('ticker-suggestions')).toBeTruthy()
  })

  it('ArrowDown highlights, Enter navigates to the highlighted suggestion', () => {
    mockSuggest.mockReturnValue(SUGGESTIONS)
    renderHero()
    const input = focusType('ap')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(screen.getByTestId('suggestion-AAPL').getAttribute('data-active')).toBe('true')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(screen.getByTestId('suggestion-AMAT').getAttribute('data-active')).toBe('true')
    fireEvent.submit(input.closest('form')!)
    expect(mockNavigate).toHaveBeenCalledWith('/stocks/AMAT')
  })

  it('clicking a suggestion navigates to it', () => {
    mockSuggest.mockReturnValue(SUGGESTIONS)
    renderHero()
    focusType('ap')
    fireEvent.click(screen.getByTestId('suggestion-AAPL'))
    expect(mockNavigate).toHaveBeenCalledWith('/stocks/AAPL')
  })

  it('Enter with no highlight submits the typed ticker (suggestions never hijack)', () => {
    mockSuggest.mockReturnValue(SUGGESTIONS) // dropdown open with AAPL/AMAT…
    renderHero()
    const input = focusType('nflx') // …but the user typed NFLX and never arrowed
    fireEvent.submit(input.closest('form')!)
    expect(mockNavigate).toHaveBeenCalledWith('/stocks/NFLX')
  })

  it('Escape dismisses the dropdown', () => {
    mockSuggest.mockReturnValue(SUGGESTIONS)
    renderHero()
    const input = focusType('ap')
    expect(screen.getByTestId('ticker-suggestions')).toBeTruthy()
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(screen.queryByTestId('ticker-suggestions')).toBeNull()
  })
})
