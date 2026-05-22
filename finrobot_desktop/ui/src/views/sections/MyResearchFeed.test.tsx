// Regression for the live-trace crash reported on 2026-05-21:
//   "undefined is not an object (evaluating 'artifact.target_price.toFixed')"
//   ArtifactCard@MyResearchFeed.tsx:185
//
// Root cause was a `!== null` guard that let `undefined` pass through. Backend
// returns target_price/entry_price as null (and legacy summaries omit them
// entirely → undefined). The fix is a `typeof === 'number'` guard; this test
// pins it down so a future refactor can't regress.

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MyResearchFeed } from './MyResearchFeed'
import type { ArtifactSummaryV5 } from '../../types/v5'

function makeArtifact(overrides: Partial<ArtifactSummaryV5> = {}): ArtifactSummaryV5 {
  return {
    id: 'art_2026-05-21T09:51:07_NVDA_equity_research',
    ticker: 'NVDA',
    cross_tickers: [],
    type: 'equity_research',
    created_at: '2026-05-21T09:51:07Z',
    headline: 'AI 完整研报',
    source: 'pipeline:equity_research',
    archived: false,
    ...overrides,
  }
}

function renderWithFixture(artifacts: ArtifactSummaryV5[]) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(
    async () =>
      ({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => artifacts,
      }) as Response,
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <MyResearchFeed ticker="NVDA" />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('MyResearchFeed — target_price guard regression', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('does not crash when target_price/entry_price are undefined (legacy summary)', async () => {
    // Legacy artifacts written before ADR-0001 v5 omit these fields entirely;
    // FastAPI serialises absent Optional[float] as `undefined` for the client.
    renderWithFixture([makeArtifact()])
    const card = await screen.findByTestId(
      'artifact-card-art_2026-05-21T09:51:07_NVDA_equity_research',
    )
    expect(card).toBeInTheDocument()
    // No target/entry row when the values aren't available.
    expect(card.textContent ?? '').not.toMatch(/target \$/)
  })

  it('does not crash when target_price/entry_price are null (v5 summary, no thesis)', async () => {
    renderWithFixture([
      makeArtifact({ target_price: null, entry_price: null, signal: null }),
    ])
    const card = await screen.findByTestId(
      'artifact-card-art_2026-05-21T09:51:07_NVDA_equity_research',
    )
    expect(card).toBeInTheDocument()
    expect(card.textContent ?? '').not.toMatch(/target \$/)
  })

  it('renders target/entry row when both are real numbers', async () => {
    renderWithFixture([
      makeArtifact({
        target_price: 85.99,
        entry_price: 302.25,
        signal: 'watching',
      }),
    ])
    const card = await screen.findByTestId(
      'artifact-card-art_2026-05-21T09:51:07_NVDA_equity_research',
    )
    expect(card.textContent ?? '').toMatch(/target \$85\.99/)
    expect(card.textContent ?? '').toMatch(/entry \$302\.25/)
  })

  it('does not crash when only one of target/entry is present', async () => {
    // Defensive: a partially-filled summary (entry but no target, or vice
    // versa) must still render the card body without throwing.
    renderWithFixture([
      makeArtifact({ target_price: 100, entry_price: null }),
    ])
    const card = await screen.findByTestId(
      'artifact-card-art_2026-05-21T09:51:07_NVDA_equity_research',
    )
    expect(card).toBeInTheDocument()
    // Both must be numbers before the price row renders.
    expect(card.textContent ?? '').not.toMatch(/target \$/)
  })
})
