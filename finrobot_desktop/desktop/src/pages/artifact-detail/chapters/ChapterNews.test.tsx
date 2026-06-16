// ChapterNews — the sourced chronological event feed. These tests assert the
// traceability contract: events render as dated, sentiment-bordered rows with
// honest source chips, sorted newest-first (undated last), and degrade without
// crashing when the feed is empty or a field is null. The app renders EN by
// default (defaultLocale), so the assertions use the EN catalog strings.

import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'

import { ChapterNews } from './ChapterNews'
import type { CatalystAnalysisShape, CatalystEventShape, ThesisShape } from './types'

const THESIS: ThesisShape = { news_summary: 'Apple momentum holds into the print.' }

function ev(over: Partial<CatalystEventShape>): CatalystEventShape {
  return {
    category: 'market',
    headline: 'Headline',
    sentiment: 'neutral',
    impact_score: 3,
    probability: 0.5,
    ...over,
  }
}

function catalysts(events: CatalystEventShape[]): CatalystAnalysisShape {
  return { events }
}

describe('ChapterNews sourced feed', () => {
  it('renders each sourced event row in the feed', () => {
    const cat = catalysts([
      ev({ headline: 'Apple unveils Vision Pro 2', published: '2026-05-01' }),
      ev({ headline: 'Q2 earnings beat consensus', published: '2026-04-15' }),
    ])
    render(<ChapterNews thesis={THESIS} catalysts={cat} />)
    expect(screen.getByText('Apple unveils Vision Pro 2')).toBeInTheDocument()
    expect(screen.getByText('Q2 earnings beat consensus')).toBeInTheDocument()
    expect(screen.getAllByTestId('news-feed-row')).toHaveLength(2)
  })

  it('keeps the LLM news_summary as the lead takeaway above the feed', () => {
    render(<ChapterNews thesis={THESIS} catalysts={catalysts([ev({ published: '2026-05-01' })])} />)
    expect(screen.getByText('Apple momentum holds into the print.')).toBeInTheDocument()
  })

  it('sorts the feed newest-published first, with null-published rows last', () => {
    const cat = catalysts([
      ev({ headline: 'OLD', published: '2025-07-01' }),
      ev({ headline: 'UNDATED', published: null }),
      ev({ headline: 'NEW', published: '2026-05-30' }),
    ])
    render(<ChapterNews thesis={null} catalysts={cat} />)
    const rows = screen.getAllByTestId('news-feed-row')
    expect(within(rows[0]).getByText('NEW')).toBeInTheDocument()
    expect(within(rows[1]).getByText('OLD')).toBeInTheDocument()
    expect(within(rows[2]).getByText('UNDATED')).toBeInTheDocument()
  })

  it('encodes per-item sentiment on the row border tone (涨绿跌红)', () => {
    const cat = catalysts([
      ev({ headline: 'POS', sentiment: 'positive', published: '2026-05-03' }),
      ev({ headline: 'NEG', sentiment: 'negative', published: '2026-05-02' }),
      ev({ headline: 'NEU', sentiment: 'neutral', published: '2026-05-01' }),
    ])
    render(<ChapterNews thesis={null} catalysts={cat} />)
    const rows = screen.getAllByTestId('news-feed-row')
    const styleOf = (el: HTMLElement) => el.getAttribute('style') ?? ''
    expect(styleOf(rows[0])).toContain('--success') // positive
    expect(styleOf(rows[1])).toContain('--danger') // negative
    expect(styleOf(rows[2])).toContain('--warning') // neutral
  })

  it('names finnhub.io as "Finnhub" and sec.gov as "SEC EDGAR" honestly', () => {
    const cat = catalysts([
      ev({
        headline: 'Finnhub-sourced',
        published: '2026-05-02',
        url: 'https://finnhub.io/api/v1/news?id=123',
      }),
      ev({
        headline: 'SEC-sourced',
        published: '2026-05-01',
        url: 'https://www.sec.gov/Archives/edgar/data/320193/000032019326.htm',
      }),
    ])
    render(<ChapterNews thesis={null} catalysts={cat} />)
    expect(screen.getByText('Finnhub')).toBeInTheDocument()
    expect(screen.getByText('SEC EDGAR')).toBeInTheDocument()
    // Source chips are real links to the source url (no fabricated "read article").
    const finnhubChip = screen.getByText('Finnhub').closest('a')
    expect(finnhubChip).not.toBeNull()
    expect(finnhubChip?.getAttribute('href')).toBe('https://finnhub.io/api/v1/news?id=123')
  })

  it('renders a source-less row (no link) when url is null, without crashing', () => {
    const cat = catalysts([ev({ headline: 'No URL here', published: '2026-05-01', url: null })])
    const { container } = render(<ChapterNews thesis={null} catalysts={cat} />)
    expect(screen.getByText('No URL here')).toBeInTheDocument()
    // No anchor element in the feed row → no source chip link was fabricated.
    expect(container.querySelector('[data-testid="news-feed-row"] a')).toBeNull()
  })

  it('degrades to the summary + a muted note when there are no events (never blank)', () => {
    render(<ChapterNews thesis={THESIS} catalysts={catalysts([])} />)
    expect(screen.getByText('Apple momentum holds into the print.')).toBeInTheDocument()
    expect(screen.queryByTestId('news-feed-row')).toBeNull()
    expect(
      screen.getByText(/No sourced events were captured/i, { exact: false }),
    ).toBeInTheDocument()
  })

  it('degrades to the muted feed note even when catalysts is null', () => {
    render(<ChapterNews thesis={THESIS} catalysts={null} />)
    expect(screen.queryByTestId('news-feed-row')).toBeNull()
    expect(
      screen.getByText(/No sourced events were captured/i, { exact: false }),
    ).toBeInTheDocument()
  })
})

// Regression: a full-ISO `published` instant must display its SOURCE (UTC)
// calendar day, not the viewer's local day. Pre-fix, formatDate('short') used
// local getters, rolling an evening-UTC instant forward east of UTC (the moat is
// "the date matches what the source reported"). Locks the formatSourceDate wiring.
describe('ChapterNews source-date is timezone-stable', () => {
  const proc = (globalThis as unknown as { process: { env: Record<string, string | undefined> } })
    .process
  const originalTZ = proc.env.TZ
  afterEach(() => {
    if (originalTZ === undefined) delete proc.env.TZ
    else proc.env.TZ = originalTZ
  })

  it('shows the UTC source day for an evening-UTC instant in a UTC+8 viewer', () => {
    proc.env.TZ = 'Asia/Shanghai'
    const cat = catalysts([ev({ headline: 'Evening UTC', published: '2026-06-11T16:20:00Z' })])
    render(<ChapterNews thesis={null} catalysts={cat} />)
    const row = screen.getByTestId('news-feed-row')
    expect(within(row).getByText('2026-06-11')).toBeInTheDocument()
    expect(within(row).queryByText('2026-06-12')).toBeNull()
  })
})
