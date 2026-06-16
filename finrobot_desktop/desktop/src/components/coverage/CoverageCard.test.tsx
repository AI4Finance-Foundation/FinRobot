/**
 * CoverageCard — the reverse-DCF "expectations" line.
 *
 * Verifies the three market_implied states render with the right copy + tone,
 * and that the line is omitted when there's nothing honest to say (no DCF, a
 * fundamental with no solved growth, or a cold row still shimmering).
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { CoverageCard } from './CoverageCard'
import type { CoverageRow, MarketImpliedNature } from '../../api/coverage'

function row(over: Partial<CoverageRow>): CoverageRow {
  return {
    ticker: 'AAA',
    company: null,
    price: 200,
    change_pct_1d: null,
    price_as_of: null,
    session_state: null,
    market_cap: null,
    revenue_ttm: null,
    ev_ebitda: null,
    pe: null,
    currency: 'USD',
    latest_verdict: null,
    target_price: null,
    target_date: null,
    entry_price: null,
    upside_to_target_live: null,
    signal: null,
    artifact_count: 0,
    research_count: 0,
    latest_artifact_id: null,
    latest_type: null,
    latest_at: null,
    run_status: null,
    run_error: null,
    market_implied: null,
    market_stale: false,
    needs_refresh: [],
    warnings: [],
    sources: {
      price: null,
      change_pct_1d: null,
      market_cap: null,
      revenue_ttm: null,
      ev_ebitda: null,
      pe: null,
      upside_to_target_live: null,
      market_implied: null,
    },
    ...over,
  }
}

function renderCard(over: Partial<CoverageRow>, marketPending = false): void {
  render(
    <MemoryRouter>
      <CoverageCard
        row={row(over)}
        density="comfort"
        marketPending={marketPending}
        onOpen={vi.fn()}
      />
    </MemoryRouter>,
  )
}

const nat = (over: Partial<MarketImpliedNature>): MarketImpliedNature => ({
  kind: 'fundamental',
  implied_growth: null,
  implied_wacc: null,
  horizon_years: 5,
  growth_ceiling: null,
  ceiling_price: null,
  ...over,
})

describe('CoverageCard market-implied line', () => {
  it('renders option_value in danger tone with the ceiling in the tooltip', () => {
    renderCard({
      market_implied: nat({ kind: 'option_value', growth_ceiling: 0.5, ceiling_price: 90 }),
    })
    const el = screen.getByText(/Option-value/)
    expect(el).toBeInTheDocument()
    expect(el.style.color).toBe('var(--danger)')
  })

  it('renders near_ceiling in warning tone', () => {
    renderCard({ market_implied: nat({ kind: 'near_ceiling' }) })
    const el = screen.getByText(/Near-ceiling/)
    expect(el).toBeInTheDocument()
    expect(el.style.color).toBe('var(--warning)')
  })

  it('renders fundamental with the implied growth as neutral context', () => {
    renderCard({ market_implied: nat({ kind: 'fundamental', implied_growth: 0.28 }) })
    const el = screen.getByText(/priced in/)
    expect(el.textContent).toMatch(/28\.0%/)
    expect(el.style.color).toBe('var(--text-secondary)')
  })

  it('omits the line for fundamental with no solved growth (never "—")', () => {
    renderCard({ market_implied: nat({ kind: 'fundamental', implied_growth: null }) })
    expect(screen.queryByText('Mkt implied')).not.toBeInTheDocument()
  })

  it('omits the line when there is no DCF (market_implied null)', () => {
    renderCard({ market_implied: null })
    expect(screen.queryByText('Mkt implied')).not.toBeInTheDocument()
  })

  it('omits the line while a cold row is still shimmering', () => {
    renderCard(
      {
        price: null,
        market_implied: nat({ kind: 'option_value', growth_ceiling: 0.5, ceiling_price: 90 }),
      },
      true,
    )
    expect(screen.queryByText(/Option-value/)).not.toBeInTheDocument()
  })
})

describe('CoverageCard price-target gauge', () => {
  function renderC(over: Partial<CoverageRow>, marketPending = false): HTMLElement {
    const { container } = render(
      <MemoryRouter>
        <CoverageCard
          row={row(over)}
          density="comfort"
          marketPending={marketPending}
          onOpen={vi.fn()}
        />
      </MemoryRouter>,
    )
    return container.querySelector('.target-gauge') as HTMLElement
  }

  it('renders the target value + a green marker when the target is ABOVE price', () => {
    const el = renderC({ price: 399.76, target_price: 558.78, upside_to_target_live: 0.3978 })
    expect(el).not.toBeNull()
    expect(el.textContent).toContain('558.78')
    const value = el.querySelector('.target-gauge__value') as HTMLElement
    expect(value.style.color).toBe('var(--success)')
    const mark = el.querySelector('.target-gauge__mark') as HTMLElement
    // Above price → marker sits right of the centre tick (>50%).
    expect(parseFloat(mark.style.left)).toBeGreaterThan(50)
  })

  it('renders a red marker LEFT of centre when the target is BELOW price', () => {
    const el = renderC({ price: 296.42, target_price: 195.04, upside_to_target_live: -0.342 })
    expect(el.textContent).toContain('195.04')
    const value = el.querySelector('.target-gauge__value') as HTMLElement
    expect(value.style.color).toBe('var(--danger)')
    const mark = el.querySelector('.target-gauge__mark') as HTMLElement
    expect(parseFloat(mark.style.left)).toBeLessThan(50)
  })

  it('omits the gauge when there is no stored target (degrade, never a broken bar)', () => {
    const el = renderC({ price: 411.15, target_price: null })
    expect(el).toBeNull()
  })

  it('omits the gauge when there is no live price', () => {
    const el = renderC({ price: null, target_price: 195.04 }, true)
    expect(el).toBeNull()
  })
})

describe('CoverageCard freshness / session affordance', () => {
  function renderC(over: Partial<CoverageRow>, marketPending = false): HTMLElement {
    const { container } = render(
      <MemoryRouter>
        <CoverageCard
          row={row(over)}
          density="comfort"
          marketPending={marketPending}
          onOpen={vi.fn()}
        />
      </MemoryRouter>,
    )
    return container.querySelector('.coverage-card__provider') as HTMLElement
  }

  it('a CLOSED market shows a static "Close · date", never the refreshing pulse', () => {
    const el = renderC(
      { session_state: 'closed', price_as_of: '2026-06-05T20:00:00Z' },
      true, // revalidate in flight — must NOT pulse over a settled close
    )
    expect(el.textContent).toContain('Close · 2026-06-05')
    expect(el.textContent).not.toContain('refreshing')
    expect(el.getAttribute('data-session')).toBe('closed')
    expect(el.getAttribute('data-refreshing')).toBeNull()
  })

  it('a LIVE market revalidating shows the refreshing affordance', () => {
    const el = renderC({ session_state: 'live', price_as_of: '2026-06-08T15:00:00Z' }, true)
    expect(el.getAttribute('data-refreshing')).toBe('true')
    expect(el.textContent).toContain('refreshing')
    expect(el.getAttribute('data-session')).toBeNull()
  })

  it('a CLOSED market labels the 1D change with the session date, not "1D"', () => {
    const { container } = render(
      <MemoryRouter>
        <CoverageCard
          row={row({
            session_state: 'closed',
            change_pct_1d: -6.56,
            price_as_of: '2026-06-05T20:00:00Z',
          })}
          density="comfort"
          onOpen={vi.fn()}
        />
      </MemoryRouter>,
    )
    const change = container.querySelector('.coverage-card__change') as HTMLElement
    expect(change.textContent).toContain('-6.56% · 06-05')
    expect(change.textContent).not.toContain('1D')
  })
})

describe('CoverageCard verdict signal chroma', () => {
  function signal(over: Partial<CoverageRow>): string | null {
    const { container } = render(
      <MemoryRouter>
        <CoverageCard row={row(over)} density="comfort" onOpen={vi.fn()} />
      </MemoryRouter>,
    )
    return (container.querySelector('.coverage-card') as HTMLElement).getAttribute('data-signal')
  }

  it('maps the three directional verdicts to their hue bucket', () => {
    expect(signal({ latest_verdict: 'BUY' })).toBe('buy')
    expect(signal({ latest_verdict: 'SELL' })).toBe('sell')
    expect(signal({ latest_verdict: 'HOLD' })).toBe('hold')
  })

  it('treats NOT RUN (null) and the legacy WITHHELD/REVIEW token as neutral', () => {
    expect(signal({ latest_verdict: null })).toBe('neutral')
    expect(signal({ latest_verdict: 'WITHHELD' })).toBe('neutral')
    expect(signal({ latest_verdict: 'REVIEW' })).toBe('neutral')
  })
})
