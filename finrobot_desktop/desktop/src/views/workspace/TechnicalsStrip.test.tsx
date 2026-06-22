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

  it('defers the 52w band to the canonical financials value + re-prices the marker', () => {
    // JPM-shape: the /price strip computed low 264.57 from its own window, but the
    // /financials snapshot tile (canonical NormalizedPrice) shows 262.69. The strip
    // must show the canonical value so the two surfaces agree, marker re-priced.
    const tech: Technicals = {
      available: true,
      trend: 'sideways',
      current_price: 325.22,
      sma20: 320,
      sma50: 315,
      sma200: 300,
      high_52w: 338.09,
      low_52w: 264.57, // the strip's own divergent window value
      range_position: 0.82,
    }
    render(<TechnicalsStrip tech={tech} canon52wLow={262.69} canon52wHigh={338.09} />)
    expect(screen.getByText('52W Low $262.69')).toBeInTheDocument()
    expect(screen.queryByText('52W Low $264.57')).not.toBeInTheDocument()
    // marker re-priced against the canonical band: (325.22−262.69)/(338.09−262.69) ≈ 0.829 → 83%
    expect(screen.getByText('Range 83%')).toBeInTheDocument()
  })

  it('falls back to the technicals own 52w when no canonical value is given', () => {
    const tech: Technicals = {
      available: true,
      trend: 'sideways',
      current_price: 100,
      sma20: 100,
      sma50: null,
      sma200: null,
      high_52w: 120,
      low_52w: 80,
      range_position: 0.5,
    }
    render(<TechnicalsStrip tech={tech} />) // no canonical props
    expect(screen.getByText('52W Low $80.00')).toBeInTheDocument()
    expect(screen.getByText('52W High $120.00')).toBeInTheDocument()
  })
})
