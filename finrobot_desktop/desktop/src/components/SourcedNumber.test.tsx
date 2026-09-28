/**
 * SourcedNumber — unit tests
 *
 * Covers: value formatting, popover on hover, popover on keyboard,
 * auto-positioning, missing source, NaN/null handling.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { SourcedNumber } from './SourcedNumber'

// SourcedNumber reads the ticker via useParams() to build the deep link to
// the artifact detail page. Tests that need the artifact link must render
// inside a route that provides :ticker; the helper below scopes a memory
// router around the component under test.
function renderWithTicker(ui: React.ReactElement, ticker = 'AAPL'): void {
  render(
    <MemoryRouter initialEntries={[`/stocks/${ticker}`]}>
      <Routes>
        <Route path="/stocks/:ticker" element={ui} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('SourcedNumber', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  // ── Value formatting ────────────────────────────────────────────────────────

  it('displays formatted number value deterministically (UI locale, not OS locale)', () => {
    render(<SourcedNumber value={1234567.89} />)
    // Routed through formatNumberAuto(_, 'en') — a bare toLocaleString()
    // followed the OS locale and made this output environment-dependent.
    expect(screen.getByText('1,234,567.89')).toBeInTheDocument()
  })

  it('applies custom format function', () => {
    render(<SourcedNumber value={0.2142} format={(v) => `${(v * 100).toFixed(1)}%`} />)
    expect(screen.getByText('21.4%')).toBeInTheDocument()
  })

  it('displays em-dash for null value', () => {
    render(<SourcedNumber value={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('displays em-dash for undefined value', () => {
    render(<SourcedNumber value={undefined} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('displays em-dash for NaN value', () => {
    render(<SourcedNumber value={NaN} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('displays string value as-is', () => {
    render(<SourcedNumber value="$12.3B" />)
    expect(screen.getByText('$12.3B')).toBeInTheDocument()
  })

  // ── No popover when source is absent ────────────────────────────────────────

  it('does not show popover trigger when source is absent', () => {
    render(<SourcedNumber value={42} />)
    // Should not have role=button if no source
    const el = screen.getByText('42')
    // The outer span should not have role=button
    expect(el.closest('[role="button"]')).toBeNull()
  })

  it('does not show popover when source has no content fields', () => {
    render(<SourcedNumber value={42} source={{}} />)
    const el = screen.getByText('42')
    expect(el.closest('[role="button"]')).toBeNull()
  })

  // ── Hover triggers popover after 200ms ──────────────────────────────────────

  it('shows popover after 200ms hover delay', () => {
    render(
      <SourcedNumber
        value={100}
        source={{ provider: 'yfinance', fetched_at: '2026-05-13T10:00:00Z' }}
      />,
    )

    const trigger = screen.getByRole('button')
    fireEvent.mouseEnter(trigger)

    // Before 200ms — popover should not be visible
    expect(screen.queryByRole('dialog')).toBeNull()

    // Advance 200ms — timer fires, state updates
    act(() => {
      vi.advanceTimersByTime(250)
    })

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('yfinance')).toBeInTheDocument()
  })

  it('hides popover when mouse leaves after delay', () => {
    render(<SourcedNumber value={100} source={{ provider: 'FMP' }} />)

    const trigger = screen.getByRole('button')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    expect(screen.getByRole('dialog')).toBeInTheDocument()

    fireEvent.mouseLeave(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    expect(screen.queryByRole('dialog')).toBeNull()
  })

  // ── Popover content ──────────────────────────────────────────────────────────

  it('shows source.provider in popover', () => {
    render(<SourcedNumber value={50} source={{ provider: 'DCF engine' }} />)
    const trigger = screen.getByRole('button')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('DCF engine')).toBeInTheDocument()
  })

  it('shows formula_warning in amber (caution, not price-red) in popover', () => {
    render(
      <SourcedNumber
        value={50}
        source={{
          provider: 'DCF engine',
          formula_warning: 'Simplified FCF formula — excludes D&A tax shield',
        }}
      />,
    )
    const trigger = screen.getByRole('button')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    const warning = screen.getByText('Simplified FCF formula — excludes D&A tax shield')
    expect(warning).toBeInTheDocument()
    // Data caveat = --warning (amber), red stays reserved for price-down.
    expect(warning).toHaveStyle({ color: 'var(--warning)' })
  })

  // ── Inline warning marker (visible without hover) ────────────────────────────

  it('renders an inline warning marker without opening the popover', () => {
    render(
      <SourcedNumber
        value={50}
        source={{ provider: 'DCF engine', formula_warning: 'Simplified FCF formula' }}
      />,
    )
    // No hover, no keyboard — the marker must already be visible inline.
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('img', { name: 'Simplified FCF formula' })).toBeInTheDocument()
  })

  it('renders no inline warning marker when there is no formula_warning', () => {
    render(<SourcedNumber value={50} source={{ provider: 'DCF engine' }} />)
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('shows as_of (data semantic time) distinct from fetched_at in popover', () => {
    render(
      <SourcedNumber
        value={28.5}
        source={{ provider: 'yfinance', as_of: '2024-09-28T00:00:00Z' }}
      />,
    )
    const trigger = screen.getByRole('button')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    // "As of" labels the reporting-period date — never conflated with fetch time.
    expect(screen.getByText(/As of/)).toBeInTheDocument()
  })

  it('resolves the artifact deep-link from the ticker prop when the route has no :ticker', () => {
    // Coverage Table renders SourcedNumber on /coverage (no :ticker param) —
    // the prop must fill in so the "open report" link still resolves.
    render(
      <SourcedNumber
        value={50}
        ticker="MSFT"
        source={{ provider: 'DCF engine', artifact_id: 'art_msft_dcf' }}
      />,
    )
    const trigger = screen.getByRole('button')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })
    const link = screen.getByText(/Open full report/) as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/stocks/MSFT/runs/art_msft_dcf')
  })

  it('shows artifact link when artifact_id is present', () => {
    renderWithTicker(
      <SourcedNumber
        value={50}
        source={{ provider: 'DCF engine', artifact_id: 'art_2026-05-13_AAPL_dcf' }}
      />,
    )
    const trigger = screen.getByRole('button')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    const link = screen.getByText(/Open full report/) as HTMLAnchorElement
    expect(link).toBeInTheDocument()
    expect(link.getAttribute('href')).toBe('/stocks/AAPL/runs/art_2026-05-13_AAPL_dcf')
  })

  // ── Keyboard access ──────────────────────────────────────────────────────────

  it('opens popover on Enter keypress', () => {
    render(<SourcedNumber value={100} source={{ provider: 'yfinance' }} />)
    const trigger = screen.getByRole('button')

    act(() => {
      fireEvent.keyDown(trigger, { key: 'Enter' })
    })

    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('opens popover on Space keypress', () => {
    render(<SourcedNumber value={100} source={{ provider: 'yfinance' }} />)
    const trigger = screen.getByRole('button')

    act(() => {
      fireEvent.keyDown(trigger, { key: ' ' })
    })

    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('closes popover on Escape keypress', () => {
    render(<SourcedNumber value={100} source={{ provider: 'yfinance' }} />)
    const trigger = screen.getByRole('button')

    act(() => {
      fireEvent.keyDown(trigger, { key: 'Enter' })
    })
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    act(() => {
      fireEvent.keyDown(trigger, { key: 'Escape' })
    })
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
