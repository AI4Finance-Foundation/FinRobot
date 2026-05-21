// CompositeScoreCard smoke test — verifies the section mounts without
// crashing in three states: enabled-but-empty-response, no-data (hook
// disabled), and full response. The section was the first one to crash
// when /api/compute/score returned `{}` (no mock); the isCompleteScore
// guard added there is what this test pins down.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CompositeScoreCard } from './CompositeScoreCard'

beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    if (url.endsWith('/api/data/AAPL/price')) {
      return jsonResponse({ current_price: 100, history: [] })
    }
    if (url.endsWith('/api/data/AAPL/financials')) {
      return jsonResponse({
        market: { pe_ratio: 30 },
        income: { gross_margin: 0.45 },
      })
    }
    if (url.endsWith('/api/data/AAPL/catalysts')) {
      return jsonResponse([{ sentiment: 'positive' }, { sentiment: 'negative' }])
    }
    if (url.endsWith('/api/artifacts/by-ticker/AAPL/timeline')) {
      return jsonResponse([])
    }
    if (url.endsWith('/api/compute/score')) {
      return jsonResponse({
        total: 72,
        fundamental: 80,
        valuation: 60,
        catalyst: 70,
        sentiment: 65,
        signal: 'BUY',
        breakdown: {
          fundamental: 'PEG 1.1 reasonable',
          valuation: 'DCF upside 18%',
          catalyst: 'One positive net',
          sentiment: 'Mixed',
        },
      })
    }
    return jsonResponse({})
  })
})
afterEach(() => vi.restoreAllMocks())

function jsonResponse(body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
  )
}

function renderWithQuery(ticker: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <CompositeScoreCard ticker={ticker} />
    </QueryClientProvider>,
  )
}

describe('CompositeScoreCard', () => {
  it('renders the section heading even before data resolves', () => {
    renderWithQuery('AAPL')
    expect(screen.getByText('🧮 综合评分')).toBeInTheDocument()
  })

  it('shows the BUY signal lamp and total once the score arrives', async () => {
    renderWithQuery('AAPL')
    await waitFor(() => {
      expect(screen.getByTestId('composite-signal').dataset.signal).toBe('BUY')
    })
    expect(screen.getByText('72')).toBeInTheDocument()
  })

  it('falls back to cold-state message when no fundamental inputs exist', () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = typeof input === 'string' ? input : (input as Request).url
      if (url.endsWith('/api/data/EMPTY/financials')) {
        return jsonResponse({ market: {}, income: {} })
      }
      if (url.endsWith('/api/data/EMPTY/catalysts')) return jsonResponse([])
      if (url.endsWith('/api/artifacts/by-ticker/EMPTY/timeline')) return jsonResponse([])
      return jsonResponse({})
    })
    renderWithQuery('EMPTY')
    expect(screen.getByText(/需要至少一个基本面字段/)).toBeInTheDocument()
  })
})
