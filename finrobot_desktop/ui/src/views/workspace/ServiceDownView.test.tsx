import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { ServiceDownView } from './ServiceDownView'

vi.mock('../../i18n', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../i18n')
  return {
    ...actual,
    useI18n: () => ({
      locale: 'zh',
      t: (key: string, params?: Record<string, unknown>) => {
        const n = params?.n ?? ''
        const attempt = params?.attempt ?? ''
        const ticker = params?.ticker ?? ''
        const map: Record<string, string> = {
          'service.down.title': '数据源暂不可用',
          'service.down.description': `${ticker} · yfinance 返回错误，等待恢复中`,
          'service.down.countdown': `${n}s 后自动重试（第 ${attempt} 次）`,
          'service.down.retryNow': '立即重试',
          'nav.stocks': '股票',
        }
        return map[key] ?? key
      },
    }),
    tSync: (key: string, params?: Record<string, unknown>) => {
      const n = params?.n ?? ''
      const attempt = params?.attempt ?? ''
      const ticker = params?.ticker ?? ''
      const map: Record<string, string> = {
        'service.down.title': '数据源暂不可用',
        'service.down.description': `${ticker} · yfinance 返回错误，等待恢复中`,
        'service.down.countdown': `${n}s 后自动重试（第 ${attempt} 次）`,
        'service.down.retryNow': '立即重试',
      }
      return map[key] ?? key
    },
  }
})

describe('ServiceDownView', () => {
  beforeEach(() => {
    // 只 fake Date / setTimeout / clearTimeout，避免影响 TanStack Query Promise 调度
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('initial render: countdown = 30s, attempt 1', () => {
    const onRetry = vi.fn()
    render(
      <MemoryRouter>
        <ServiceDownView ticker="AAPL" onRetry={onRetry} />
      </MemoryRouter>,
    )
    expect(screen.getByText(/数据源暂不可用/)).toBeInTheDocument()
    expect(screen.getByText(/30s 后自动重试（第 1 次）/)).toBeInTheDocument()
    expect(onRetry).not.toHaveBeenCalled()
  })

  it('countdown ticks down each second', () => {
    const onRetry = vi.fn()
    render(
      <MemoryRouter>
        <ServiceDownView ticker="AAPL" onRetry={onRetry} />
      </MemoryRouter>,
    )
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(screen.getByText(/25s 后自动重试/)).toBeInTheDocument()
  })

  // CRITICAL REGRESSION: countdown reaching 0 must call onRetry ONLY ONCE.
  // Previous spec review found an effect-ordering bug: 2-effect impl would
  // re-fire onRetry on the attempts-change re-render before the 2nd effect
  // reset countdown. Single-effect fix below is mandatory.
  it('countdown hitting 0 calls onRetry exactly once', () => {
    const onRetry = vi.fn()
    render(
      <MemoryRouter>
        <ServiceDownView ticker="AAPL" onRetry={onRetry} />
      </MemoryRouter>,
    )
    act(() => {
      vi.advanceTimersByTime(30_000)
    })
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('after first auto-retry, countdown becomes 60s (backoff 2x)', () => {
    const onRetry = vi.fn()
    render(
      <MemoryRouter>
        <ServiceDownView ticker="AAPL" onRetry={onRetry} />
      </MemoryRouter>,
    )
    act(() => {
      vi.advanceTimersByTime(30_000)
    })
    expect(screen.getByText(/60s 后自动重试（第 2 次）/)).toBeInTheDocument()
  })

  it('repeated retries hit the 300s cap (no exponential explosion)', () => {
    const onRetry = vi.fn()
    render(
      <MemoryRouter>
        <ServiceDownView ticker="AAPL" onRetry={onRetry} />
      </MemoryRouter>,
    )
    // attempt 1 → 30s wait, attempt 2 → 60s, 3 → 120s, 4 → 240s, 5 → cap 300s
    act(() => {
      vi.advanceTimersByTime(30_000)
    })
    act(() => {
      vi.advanceTimersByTime(60_000)
    })
    act(() => {
      vi.advanceTimersByTime(120_000)
    })
    act(() => {
      vi.advanceTimersByTime(240_000)
    })
    expect(screen.getByText(/300s 后自动重试（第 5 次）/)).toBeInTheDocument()
    expect(onRetry).toHaveBeenCalledTimes(4)
  })

  it('manual retry resets attempts to 1 and countdown to 30s', () => {
    const onRetry = vi.fn()
    render(
      <MemoryRouter>
        <ServiceDownView ticker="AAPL" onRetry={onRetry} />
      </MemoryRouter>,
    )
    act(() => {
      vi.advanceTimersByTime(30_000)
    })
    expect(onRetry).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByText(/立即重试/))
    expect(onRetry).toHaveBeenCalledTimes(2)
    expect(screen.getByText(/30s 后自动重试（第 1 次）/)).toBeInTheDocument()
  })
})
