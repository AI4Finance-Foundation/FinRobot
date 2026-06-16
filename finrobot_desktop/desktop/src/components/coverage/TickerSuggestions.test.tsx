import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { TickerSuggestions } from './TickerSuggestions'

const RESULTS = [
  { symbol: 'AAPL', name: 'Apple Inc.' },
  { symbol: 'AMAT', name: 'Applied Materials' },
]

function renderList(activeIndex = 0, onSelect = vi.fn(), onHover = vi.fn()) {
  render(
    <TickerSuggestions
      results={RESULTS}
      activeIndex={activeIndex}
      query="ap"
      labelId="lst"
      onSelect={onSelect}
      onHover={onHover}
    />,
  )
  return { onSelect, onHover }
}

describe('TickerSuggestions', () => {
  it('renders one option per result with ticker + name', () => {
    renderList()
    expect(screen.getAllByRole('option')).toHaveLength(2)
    const row = screen.getByTestId('suggestion-AAPL')
    expect(row.textContent).toContain('AAPL')
    expect(row.textContent).toContain('Apple Inc.')
  })

  it('marks only the active row', () => {
    renderList(1)
    expect(screen.getByTestId('suggestion-AAPL').getAttribute('data-active')).toBeNull()
    expect(screen.getByTestId('suggestion-AMAT').getAttribute('data-active')).toBe('true')
    expect(screen.getByTestId('suggestion-AMAT').getAttribute('aria-selected')).toBe('true')
  })

  it('calls onSelect with the symbol when a row is clicked', () => {
    const { onSelect } = renderList()
    fireEvent.click(screen.getByTestId('suggestion-AMAT'))
    expect(onSelect).toHaveBeenCalledWith('AMAT')
  })

  it('calls onHover with the row index on mouse enter', () => {
    const { onHover } = renderList()
    fireEvent.mouseEnter(screen.getByTestId('suggestion-AMAT'))
    expect(onHover).toHaveBeenCalledWith(1)
  })

  it('bold-emphasises the matched substring in the company name', () => {
    renderList()
    const strongs = screen.getByTestId('suggestion-AAPL').querySelectorAll('strong')
    const texts = [...strongs].map((s) => s.textContent)
    expect(texts).toContain('Ap') // "Apple" -> **Ap**ple
  })

  it('shows no price/exchange fields (only honest symbol + name)', () => {
    renderList()
    // guard against fabricated data sneaking back in
    expect(screen.getByTestId('ticker-suggestions').textContent).not.toMatch(/\$|NASDAQ|NYSE|%/)
  })
})
