// Regression: the raw provider fast path (/price provider-cache) bypasses the
// backend normalize chokepoint, and yfinance can hand an all-NaN OHLC session
// row that serializes as close:null (live 2026-06-11: AAPL 2026-06-10). A null
// close anywhere — especially TRAILING — must not crash the footer readout
// (`fmtPrice(null).toFixed`) nor poison the Y domain / 1Y change anchor.

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PriceTrendChart } from './PriceTrendChart'
import type { PricePoint } from '../../hooks/useTickerData'

function pts(closes: Array<number | null>): PricePoint[] {
  return closes.map(
    (close, i) =>
      ({
        date: `2026-05-${String(i + 1).padStart(2, '0')}`,
        close,
      }) as unknown as PricePoint,
  )
}

describe('PriceTrendChart — non-finite close defense', () => {
  it('renders the chart and anchors the readout to the last FINITE close', () => {
    render(<PriceTrendChart points={pts([100, 110, 120, null])} sessionState="closed" />)
    // Footer shows the last finite close (120), not a crash on null.toFixed.
    expect(screen.getByText(/\$120\.00/)).toBeInTheDocument()
  })

  it('falls back to the empty state when every close is null', () => {
    render(<PriceTrendChart points={pts([null, null, null])} />)
    expect(screen.getByText(/No price history/i)).toBeInTheDocument()
  })

  it('still shows the empty state for a null payload', () => {
    render(<PriceTrendChart points={null} />)
    expect(screen.getByText(/No price history/i)).toBeInTheDocument()
  })
})
