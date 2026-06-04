import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { TechnicalsStrip } from './MarketDataZone'
import type { Technicals } from '../../hooks/useTickerData'

describe('TechnicalsStrip', () => {
  it('renders nothing when technicals are absent', () => {
    const { container } = render(<TechnicalsStrip tech={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows an insufficient-history note instead of numbers', () => {
    const tech: Technicals = { available: false, reason: 'insufficient_history' }
    render(<TechnicalsStrip tech={tech} />)
    expect(screen.getByText(/Insufficient trend data/)).toBeInTheDocument()
  })

  it('renders 多头排列 + SMA stack + clamped range position for an uptrend', () => {
    const tech: Technicals = {
      available: true,
      trend: 'uptrend',
      current_price: 312.06,
      sma20: 297.54,
      sma50: 275.29,
      sma200: 263.24,
      high_52w: 315,
      low_52w: 195.07,
      range_position: 0.975,
    }
    render(<TechnicalsStrip tech={tech} />)
    expect(screen.getByText('↑ Uptrend')).toBeInTheDocument()
    expect(screen.getByText('$297.54')).toBeInTheDocument()
    expect(screen.getByText('$263.24')).toBeInTheDocument()
    expect(screen.getByText('52W Low $195.07')).toBeInTheDocument()
    expect(screen.getByText('52W High $315.00')).toBeInTheDocument()
    // 0.975 → 98%
    expect(screen.getByText('Range 98%')).toBeInTheDocument()
  })

  it('clamps a range_position above the rolling window into [0,1]', () => {
    const tech: Technicals = {
      available: true,
      trend: 'sideways',
      current_price: 120,
      sma20: 100,
      sma50: null,
      sma200: null,
      high_52w: 118,
      low_52w: 80,
      range_position: 1.05, // current poked past the window high
    }
    render(<TechnicalsStrip tech={tech} />)
    // clamped to 100%
    expect(screen.getByText('Range 100%')).toBeInTheDocument()
    // null SMA shows the em-dash placeholder
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1)
  })
})
