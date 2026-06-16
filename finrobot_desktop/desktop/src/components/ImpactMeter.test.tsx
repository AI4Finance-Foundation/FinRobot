// ImpactMeter — the shared 5-segment magnitude meter (extracted from the News
// feed so Catalysts can reuse it). These tests pin the segment-fill contract:
// filled = round(score) clamped to 0–5, neutral cyan fill on filled segments,
// grid fill on the remainder. The data-filled hook makes the count testable in
// jsdom (where SVG layout doesn't compute).

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ImpactMeter } from './ImpactMeter'

function filledCount(): number {
  return Number(screen.getByTestId('impact-meter').getAttribute('data-filled'))
}

function segmentFills(): string[] {
  return [...screen.getByTestId('impact-meter').querySelectorAll('rect')].map(
    (r) => r.getAttribute('fill') ?? '',
  )
}

describe('ImpactMeter', () => {
  it('always renders exactly 5 segments', () => {
    render(<ImpactMeter score={3} />)
    expect(screen.getByTestId('impact-meter').querySelectorAll('rect')).toHaveLength(5)
  })

  it('fills the first N segments for an integer score (cyan = filled, grid = empty)', () => {
    render(<ImpactMeter score={3} />)
    expect(filledCount()).toBe(3)
    expect(segmentFills()).toEqual([
      'var(--accent-cyan)',
      'var(--accent-cyan)',
      'var(--accent-cyan)',
      'var(--border-grid)',
      'var(--border-grid)',
    ])
  })

  it('rounds a fractional score to the nearest segment', () => {
    render(<ImpactMeter score={2.6} />)
    expect(filledCount()).toBe(3)
  })

  it('clamps above 5 and below 0', () => {
    const { rerender } = render(<ImpactMeter score={9} />)
    expect(filledCount()).toBe(5)
    rerender(<ImpactMeter score={-2} />)
    expect(filledCount()).toBe(0)
  })

  it('renders 0 lit segments (never "NaN") for a non-finite score', () => {
    const { rerender } = render(<ImpactMeter score={NaN} />)
    expect(filledCount()).toBe(0)
    expect(screen.getByTestId('impact-meter').getAttribute('title')).toBe('Impact 0/5')
    rerender(<ImpactMeter score={Infinity} />)
    expect(filledCount()).toBe(0)
  })

  it('exposes an impact tooltip with the clamped score', () => {
    render(<ImpactMeter score={4} />)
    // EN catalog: "Impact {score}/5"
    expect(screen.getByTestId('impact-meter').getAttribute('title')).toBe('Impact 4/5')
  })
})
