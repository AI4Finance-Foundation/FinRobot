// ChapterCatalysts — the forward-looking Positive / Risks / Monitor buckets.
// These tests pin the per-item meta line after the W11 change: impact now
// renders as the shared ImpactMeter (magnitude on a non-text channel), while
// category and probability stay as text (probability is legitimate here, unlike
// the raw News feed). The app renders EN by default, so assertions use the EN
// catalog strings.

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterCatalysts } from './ChapterCatalysts'
import type { CatalystAnalysisShape, CatalystEventShape } from './types'

function ev(over: Partial<CatalystEventShape>): CatalystEventShape {
  return {
    category: 'product_launch',
    headline: 'Headline',
    sentiment: 'positive',
    impact_score: 4,
    probability: 0.7,
    ...over,
  }
}

function catalysts(over: Partial<CatalystAnalysisShape>): CatalystAnalysisShape {
  return { events: [], ...over }
}

describe('ChapterCatalysts meta line', () => {
  it('renders impact as the shared ImpactMeter (not plain "X/5" text)', () => {
    const cat = catalysts({
      top_positive: [ev({ headline: 'New chip launch', impact_score: 4 })],
    })
    render(<ChapterCatalysts catalysts={cat} />)
    // The meter is present and reflects the impact score…
    const meter = screen.getByTestId('impact-meter')
    expect(meter.getAttribute('data-filled')).toBe('4')
    // …and the old plain-text "4/5" rendering is gone.
    expect(screen.queryByText(/\b4\/5\b/)).toBeNull()
  })

  it('keeps category and probability as text alongside the meter', () => {
    const cat = catalysts({
      top_positive: [ev({ category: 'product_launch', probability: 0.7 })],
    })
    render(<ChapterCatalysts catalysts={cat} />)
    expect(screen.getByText(/product_launch/)).toBeInTheDocument()
    expect(screen.getByText(/70%/)).toBeInTheDocument()
    // IMPACT label still labels the meter.
    expect(screen.getByText(/IMPACT/)).toBeInTheDocument()
  })

  it('renders a meter for each catalyst item', () => {
    const cat = catalysts({
      top_positive: [
        ev({ headline: 'A', impact_score: 5 }),
        ev({ headline: 'B', impact_score: 2 }),
      ],
    })
    render(<ChapterCatalysts catalysts={cat} />)
    const meters = screen.getAllByTestId('impact-meter')
    expect(meters).toHaveLength(2)
    expect(meters[0].getAttribute('data-filled')).toBe('5')
    expect(meters[1].getAttribute('data-filled')).toBe('2')
  })

  it('leaves the aggregate net/overall sentiment block intact', () => {
    const cat = catalysts({
      top_positive: [ev({})],
      overall_sentiment: 'bullish',
      net_sentiment: 0.42,
    })
    render(<ChapterCatalysts catalysts={cat} />)
    expect(screen.getByText('BULLISH')).toBeInTheDocument()
    expect(screen.getByText(/\+0\.42/)).toBeInTheDocument()
  })

  it('shows the empty-risks note (no thesis fallback) when there are no structured negative events', () => {
    // thesis.risks no longer back-fills the risk bucket here — it lives in the
    // Investment Thesis bull/bear case. With no top_negative, the bucket shows the
    // empty note, NOT a thesis-risk fallback (so risks render in exactly one place).
    const cat = catalysts({ top_positive: [ev({ headline: 'Up' })] })
    render(<ChapterCatalysts catalysts={cat} />)
    expect(screen.getByText('No major risk factors identified')).toBeInTheDocument()
  })
})
