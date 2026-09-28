/**
 * TargetGauge — the shared analyst price-target gauge (Coverage card + workspace
 * verdict card). Asserts the direction/tone of the gap, the magnitude clamp, and
 * the degrade-to-null on missing data. NO confidence band is ever drawn (that's
 * TargetRange's job — fabricating one here would invent precision).
 */

import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { TargetGauge } from './TargetGauge'

function renderGauge(props: {
  targetPrice: number | null
  currentPrice: number | null
  upside?: number | null
}): HTMLElement | null {
  const { container } = render(
    <MemoryRouter>
      <TargetGauge quoteCurrency="USD" ticker="AAA" {...props} />
    </MemoryRouter>,
  )
  return container.querySelector('.target-gauge') as HTMLElement | null
}

describe('TargetGauge', () => {
  it('plots a green marker RIGHT of centre when the target is above price', () => {
    const el = renderGauge({ currentPrice: 399.76, targetPrice: 558.78, upside: 0.3978 })
    expect(el).not.toBeNull()
    expect(el!.textContent).toContain('558.78')
    const value = el!.querySelector('.target-gauge__value') as HTMLElement
    expect(value.style.color).toBe('var(--success)')
    const mark = el!.querySelector('.target-gauge__mark') as HTMLElement
    expect(parseFloat(mark.style.left)).toBeGreaterThan(50)
  })

  it('plots a red marker LEFT of centre when the target is below price', () => {
    const el = renderGauge({ currentPrice: 296.42, targetPrice: 195.04, upside: -0.342 })
    expect(el!.textContent).toContain('195.04')
    const value = el!.querySelector('.target-gauge__value') as HTMLElement
    expect(value.style.color).toBe('var(--danger)')
    const mark = el!.querySelector('.target-gauge__mark') as HTMLElement
    expect(parseFloat(mark.style.left)).toBeLessThan(50)
  })

  it('derives the gap from the ratio when no explicit upside is given', () => {
    // 150 vs 100 → +50% → marker pinned to the clamp ceiling (100%, the far edge).
    const el = renderGauge({ currentPrice: 100, targetPrice: 150 })
    const mark = el!.querySelector('.target-gauge__mark') as HTMLElement
    expect(parseFloat(mark.style.left)).toBe(100)
  })

  it('clamps a moon-shot gap at the |50%| ceiling (marker never leaves the rail)', () => {
    // +400% would overflow without the clamp; the marker pins at the far edge.
    const el = renderGauge({ currentPrice: 10, targetPrice: 50, upside: 4.0 })
    const mark = el!.querySelector('.target-gauge__mark') as HTMLElement
    expect(parseFloat(mark.style.left)).toBe(100)
    // …and the full value still rides the label, not the geometry.
    expect(el!.textContent).toContain('50.00')
  })

  it('degrades to null when there is no stored target (never a broken bar)', () => {
    expect(renderGauge({ currentPrice: 411.15, targetPrice: null })).toBeNull()
  })

  it('degrades to null when there is no current price', () => {
    expect(renderGauge({ currentPrice: null, targetPrice: 195.04 })).toBeNull()
  })

  it('degrades to null on a non-positive current price (no divide-by-zero)', () => {
    expect(renderGauge({ currentPrice: 0, targetPrice: 195.04 })).toBeNull()
  })

  it('draws no confidence band — only a single target marker, never a range rect', () => {
    const el = renderGauge({ currentPrice: 100, targetPrice: 120, upside: 0.2 })
    // TargetGauge is a thin track + one mark; it must NOT render TargetRange's
    // band rect / svg ruler (the honesty distinction — no fabricated band).
    expect(el!.querySelector('svg')).toBeNull()
    expect(el!.querySelector('[data-testid="target-range"]')).toBeNull()
    expect(el!.querySelectorAll('.target-gauge__mark').length).toBe(1)
  })
})
