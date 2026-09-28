// ChapterCatalysts — the AGGREGATE catalyst signal (directional read + category
// mix). These tests pin the post-dedup redesign: the chapter no longer re-lists
// the individual events the news feed already carries, no longer sweeps past
// filings into an "events to monitor" bucket, and no longer prints a per-event
// probability column (which was a hardcoded constant = fake precision). The app
// renders EN by default, so assertions use the EN catalog strings.

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

describe('ChapterCatalysts aggregate signal', () => {
  it('renders the directional read (sentiment token + net sentiment)', () => {
    const cat = catalysts({
      events: [ev({}), ev({ sentiment: 'negative' })],
      overall_sentiment: 'bullish',
      net_sentiment: 0.42,
    })
    render(<ChapterCatalysts catalysts={cat} />)
    expect(screen.getByTestId('catalyst-direction')).toHaveTextContent('BULLISH')
    expect(screen.getByText(/\+0\.42/)).toBeInTheDocument()
    // Event count caption reflects the number of underlying events.
    expect(screen.getByText(/across 2 recent catalyst events/i)).toBeInTheDocument()
  })

  it('renders the category mix as counted chips, highest count first', () => {
    const cat = catalysts({
      events: [ev({}), ev({}), ev({ category: 'earnings' })],
      overall_sentiment: 'neutral',
      net_sentiment: 0,
      category_breakdown: { product_launch: 2, earnings: 1 },
    })
    render(<ChapterCatalysts catalysts={cat} />)
    const chips = screen.getAllByTestId('catalyst-category')
    expect(chips).toHaveLength(2)
    // Sorted by count desc: product_launch (2) before earnings (1).
    expect(chips[0]).toHaveTextContent(/Product Launch\s*2/)
    expect(chips[1]).toHaveTextContent(/Earnings\s*1/)
  })

  it('does NOT re-list individual event headlines (they live once in the news feed)', () => {
    const cat = catalysts({
      events: [ev({ headline: 'Apple unveils Vision Pro 2' })],
      overall_sentiment: 'bullish',
      net_sentiment: 1.2,
      top_positive: [ev({ headline: 'Apple unveils Vision Pro 2' })],
      category_breakdown: { product_launch: 1 },
    })
    render(<ChapterCatalysts catalysts={cat} />)
    expect(screen.queryByText('Apple unveils Vision Pro 2')).toBeNull()
  })

  it('never prints a probability column (constant probability = fake precision)', () => {
    const cat = catalysts({
      events: [ev({ probability: 0.7 }), ev({ probability: 1.0, sentiment: 'neutral' })],
      overall_sentiment: 'bullish',
      net_sentiment: 0.8,
      category_breakdown: { product_launch: 2 },
    })
    render(<ChapterCatalysts catalysts={cat} />)
    expect(screen.queryByText(/70%/)).toBeNull()
    expect(screen.queryByText(/100%/)).toBeNull()
    expect(screen.queryByText(/PROBABILITY/i)).toBeNull()
  })

  it('has no "events to monitor" bucket (past filings are not forward events)', () => {
    const cat = catalysts({
      events: [ev({ category: 'regulatory', sentiment: 'neutral', impact_score: 3 })],
      overall_sentiment: 'neutral',
      net_sentiment: 0,
      category_breakdown: { regulatory: 1 },
    })
    render(<ChapterCatalysts catalysts={cat} />)
    expect(screen.queryByText(/Events to Monitor/i)).toBeNull()
  })

  it('shows the cross-reference note pointing events to the news feed and thesis', () => {
    const cat = catalysts({
      events: [ev({})],
      overall_sentiment: 'bullish',
      net_sentiment: 0.5,
      category_breakdown: { product_launch: 1 },
    })
    render(<ChapterCatalysts catalysts={cat} />)
    expect(screen.getByText(/itemized in the recent-news feed/i)).toBeInTheDocument()
  })

  it('degrades to a muted note when there are no events (never blank)', () => {
    render(<ChapterCatalysts catalysts={catalysts({ events: [] })} />)
    expect(screen.getByText(/No catalyst events were captured/i)).toBeInTheDocument()
  })

  it('degrades to the muted note even when catalysts is null', () => {
    render(<ChapterCatalysts catalysts={null} />)
    expect(screen.getByText(/No catalyst events were captured/i)).toBeInTheDocument()
  })
})
