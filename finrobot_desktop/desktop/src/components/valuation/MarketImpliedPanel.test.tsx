/**
 * MarketImpliedPanel — wrong-ticker regression guard.
 *
 * The panel caches seed/line/wacc in local state and fetches on mount
 * (expanded by default). Mount points survive navigation (/stocks/AAPL →
 * /stocks/MSFT renders the same element), so without an explicit
 * reset-on-ticker-change the panel kept showing ticker A's market-implied
 * growth/WACC under ticker B's header — a wrong-ticker number on an
 * analyst-facing panel.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MarketImpliedPanel } from './MarketImpliedPanel'

const fetchMock = vi.fn()

vi.mock('../../api/fetch', () => ({
  fetchWithTimeout: (...args: unknown[]) => fetchMock(...args),
}))
vi.mock('../../api/client', () => ({ BASE_URL: 'http://test' }))

function jsonResponse(payload: unknown): { ok: boolean; json: () => Promise<unknown> } {
  return { ok: true, json: async () => payload }
}

function seedFor(growth: number): unknown {
  const reverse = {
    solve_for: 'horizon',
    implied_growth: growth,
    implied_wacc: 0.11,
    implied_horizon: 7,
    assumed_growth: 0.2,
    wacc: 0.09,
    terminal_growth: 0.025,
    target_price: 100,
    horizon_years: 30,
    bracket: [1, 30],
    price_at_lo: 80,
    price_at_hi: 140,
    reason_code: 'solved',
  }
  return {
    reverse_growth: reverse,
    reverse_wacc: reverse,
    reverse_horizon: reverse,
    current_price: 100,
  }
}

const LINE = {
  ticker: 'AAPL',
  target_price: 100,
  wacc: 0.09,
  terminal_growth: 0.025,
  points: [{ growth: 0.2, implied_horizon: 5 }],
}

function mockBackend(growth: number): void {
  fetchMock.mockImplementation((url: string) => {
    if (String(url).includes('dcf-seed')) return Promise.resolve(jsonResponse(seedFor(growth)))
    return Promise.resolve(jsonResponse(LINE))
  })
}

describe('MarketImpliedPanel ticker change', () => {
  beforeEach(() => {
    fetchMock.mockReset()
  })

  it('drops cached seed and re-fetches when the ticker changes', async () => {
    mockBackend(0.25)
    const { rerender } = render(<MarketImpliedPanel ticker="AAPL" />)

    // Expanded by default: the seed loads on mount, the growth anchor card
    // renders 25% with no click needed.
    await waitFor(() => expect(screen.getByText('25%')).toBeInTheDocument())

    // Same element, new ticker — the stale AAPL probe must NOT survive.
    mockBackend(0.4)
    rerender(<MarketImpliedPanel ticker="MSFT" />)
    await waitFor(() => expect(screen.queryByText('25%')).not.toBeInTheDocument())

    // Stays expanded and fetches MSFT's own seed (not the cached AAPL one).
    await waitFor(() => expect(screen.getByText('40%')).toBeInTheDocument())
    const seedCalls = fetchMock.mock.calls.filter(([u]) => String(u).includes('dcf-seed'))
    expect(seedCalls).toHaveLength(2)
    expect(String(seedCalls[1]?.[1] && (seedCalls[1][1] as RequestInit).body)).toContain('MSFT')
  })
})
