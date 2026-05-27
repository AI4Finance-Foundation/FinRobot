import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { TickerHero } from './TickerHero'

// Mock i18n: provide tSync for format helpers + useI18n for WorkspaceBreadcrumb
vi.mock('../i18n', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../i18n')
  return {
    ...actual,
    tSync: (key: string, params?: Record<string, unknown>) => {
      const n = params?.n ?? ''
      const map: Record<string, string> = {
        'marketdata.age.justNow': '刚刚',
        'marketdata.age.sAgo': `${n}s 前`,
        'marketdata.age.minAgo': `${n}min 前`,
        'marketdata.age.hAgo': `${n}h 前`,
        'marketdata.tier.fresh': '近实时',
        'marketdata.tier.delayed': '延迟',
        'marketdata.tier.stale': '陈旧',
      }
      return map[key] ?? key
    },
    useI18n: () => ({ locale: 'zh', t: (k: string) => k }),
  }
})

function setupFetch(priceData: Record<string, unknown>) {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    if (url.includes('/api/data/') && url.includes('/price')) {
      return Promise.resolve(
        new Response(JSON.stringify(priceData), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      )
    }
    return Promise.resolve(new Response('{}', { status: 200 }))
  })
}

function renderHero(ticker = 'AAPL') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TickerHero ticker={ticker} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('TickerHero freshness pill', () => {
  beforeEach(() => {
    // Only fake Date — leave setTimeout/Promise timers real so TanStack Query
    // fetch promises can settle and findByText doesn't hang.
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-05-27T12:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('fetched_at = ~now → pill 显示 近实时 + 刚刚', async () => {
    setupFetch({
      current_price: 200,
      change_pct: 0.5,
      change: 1.0,
      exchange: 'NasdaqGS',
      fetched_at: '2026-05-27T11:59:58Z', // 2s ago
    })
    renderHero('AAPL')
    expect(await screen.findByText(/近实时/)).toBeInTheDocument()
    expect(screen.getByText(/刚刚/)).toBeInTheDocument()
    expect(screen.getByText(/NASDAQ/)).toBeInTheDocument()
  })

  it('fetched_at = 10min ago → pill 显示 延迟', async () => {
    setupFetch({
      current_price: 200,
      change_pct: 0.5,
      change: 1.0,
      exchange: 'NasdaqGS',
      fetched_at: '2026-05-27T11:50:00Z',
    })
    renderHero('AAPL')
    expect(await screen.findByText(/延迟/)).toBeInTheDocument()
    expect(screen.getByText(/10min 前/)).toBeInTheDocument()
  })

  it('fetched_at = 45min ago → pill 显示 陈旧', async () => {
    setupFetch({
      current_price: 200,
      change_pct: 0.5,
      change: 1.0,
      exchange: 'NasdaqGS',
      fetched_at: '2026-05-27T11:15:00Z',
    })
    renderHero('AAPL')
    expect(await screen.findByText(/陈旧/)).toBeInTheDocument()
  })

  it('fetched_at = null → treated as stale, no 近实时 label', async () => {
    setupFetch({
      current_price: 200,
      change_pct: 0.5,
      change: 1.0,
      exchange: 'NasdaqGS',
      fetched_at: null,
    })
    renderHero('AAPL')
    expect(await screen.findByText(/陈旧/)).toBeInTheDocument()
    expect(screen.queryByText(/近实时/)).not.toBeInTheDocument()
  })
})
