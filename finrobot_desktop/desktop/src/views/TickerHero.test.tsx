import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { TickerHero } from './TickerHero'

// Mock i18n: provide tSync for the format helpers used by the freshness pill.
vi.mock('../i18n', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../i18n')
  return {
    ...actual,
    tSync: (key: string, params?: Record<string, unknown>) => {
      const n = params?.n ?? ''
      const date = params?.date ?? ''
      const map: Record<string, string> = {
        'marketdata.age.justNow': '刚刚',
        'marketdata.age.sAgo': `${n}s 前`,
        'marketdata.age.minAgo': `${n}min 前`,
        'marketdata.age.hAgo': `${n}h 前`,
        'marketdata.tier.fresh': '近实时',
        'marketdata.tier.delayed': '延迟',
        'marketdata.tier.stale': '陈旧',
        'workspace.hero.usMarket': '美股',
        'workspace.hero.closedAsOf': `收盘 · ${date}`,
      }
      return map[key] ?? key
    },
    useI18n: () => ({
      locale: 'zh',
      t: (key: string, params?: Record<string, unknown>) => {
        const n = params?.n ?? ''
        const date = params?.date ?? ''
        const map: Record<string, string> = {
          'marketdata.age.justNow': '刚刚',
          'marketdata.age.sAgo': `${n}s 前`,
          'marketdata.age.minAgo': `${n}min 前`,
          'marketdata.age.hAgo': `${n}h 前`,
          'marketdata.tier.fresh': '近实时',
          'marketdata.tier.delayed': '延迟',
          'marketdata.tier.stale': '陈旧',
          'workspace.hero.usMarket': '美股',
          'workspace.hero.closedAsOf': `收盘 · ${date}`,
        }
        return map[key] ?? key
      },
    }),
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

  it('session_state closed → pill 显示 收盘 · MM-DD (绑后端判定，不看本地日期)', async () => {
    setupFetch({
      current_price: 200,
      change_pct: 0.5,
      change: 1.0,
      exchange: 'NasdaqGS',
      fetched_at: '2026-05-27T11:59:58Z',
      as_of: '2026-05-26',
      session_state: 'closed',
    })
    renderHero('AAPL')
    expect(await screen.findByText(/收盘 · 05-26/)).toBeInTheDocument()
    expect(screen.queryByText(/近实时/)).not.toBeInTheDocument()
  })

  it('session_state live → 走 tier 标签，绝不标 收盘（即便本地已跨过午夜）', async () => {
    setupFetch({
      current_price: 200,
      change_pct: 0.5,
      change: 1.0,
      exchange: 'NasdaqGS',
      fetched_at: '2026-05-27T11:59:58Z',
      // as_of "昨天" + live：旧实现会按本地日期误标收盘，新实现读 session_state。
      as_of: '2026-05-26',
      session_state: 'live',
    })
    renderHero('AAPL')
    expect(await screen.findByText(/近实时/)).toBeInTheDocument()
    expect(screen.queryByText(/收盘/)).not.toBeInTheDocument()
  })

  it('as_of carries a time component → 收盘 仍只显示 MM-DD（不吐时间戳）', async () => {
    setupFetch({
      current_price: 200,
      change_pct: 0.5,
      change: 1.0,
      exchange: 'NasdaqGS',
      fetched_at: '2026-05-27T11:59:58Z',
      as_of: '2026-05-26T20:00:00Z',
      session_state: 'closed',
    })
    renderHero('AAPL')
    expect(await screen.findByText(/收盘 · 05-26/)).toBeInTheDocument()
    expect(screen.queryByText(/T20:00/)).not.toBeInTheDocument()
  })
})
