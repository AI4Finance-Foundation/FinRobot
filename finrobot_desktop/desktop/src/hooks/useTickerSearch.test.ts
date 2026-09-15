import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'

import { useTickerSearch } from './useTickerSearch'
import * as searchApi from '../api/search'

vi.mock('../api/search', () => ({ searchSymbols: vi.fn() }))
const mockSearch = vi.mocked(searchApi.searchSymbols)

const AAPL = { symbol: 'AAPL', name: 'Apple Inc.' }

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

describe('useTickerSearch', () => {
  beforeEach(() => mockSearch.mockReset())

  it('debounces a query then returns suggestions', async () => {
    mockSearch.mockResolvedValue([AAPL])
    const { result, rerender } = renderHook(({ q }) => useTickerSearch(q), {
      initialProps: { q: '' },
    })
    expect(result.current).toEqual([])
    rerender({ q: 'ap' })
    await waitFor(() => expect(result.current).toEqual([AAPL]))
    expect(mockSearch).toHaveBeenCalledWith('ap')
  })

  it('clears results and does not fetch for an empty query', async () => {
    mockSearch.mockResolvedValue([AAPL])
    const { result, rerender } = renderHook(({ q }) => useTickerSearch(q), {
      initialProps: { q: 'ap' },
    })
    await waitFor(() => expect(result.current).toEqual([AAPL]))
    mockSearch.mockClear()
    rerender({ q: '   ' })
    await waitFor(() => expect(result.current).toEqual([]))
    expect(mockSearch).not.toHaveBeenCalled()
  })

  it('drops a stale slow response so it cannot overwrite a newer one', async () => {
    let resolveSlow: (v: (typeof AAPL)[]) => void = () => {}
    mockSearch.mockImplementation((q: string) =>
      q === 'a'
        ? new Promise<(typeof AAPL)[]>((res) => {
            resolveSlow = res
          })
        : Promise.resolve([{ symbol: 'AP', name: 'Ampco-Pittsburgh' }]),
    )
    const { result, rerender } = renderHook(({ q }) => useTickerSearch(q), {
      initialProps: { q: 'a' },
    })
    await sleep(220) // 'a' debounce fires; searchSymbols('a') now pending (slow)
    rerender({ q: 'ap' })
    await waitFor(() =>
      expect(result.current).toEqual([{ symbol: 'AP', name: 'Ampco-Pittsburgh' }]),
    )
    resolveSlow([{ symbol: 'A', name: 'Agilent' }]) // late stale response
    await sleep(20)
    expect(result.current).toEqual([{ symbol: 'AP', name: 'Ampco-Pittsburgh' }])
  })
})
