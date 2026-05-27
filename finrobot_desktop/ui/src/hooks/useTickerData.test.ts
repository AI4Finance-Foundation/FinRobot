import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fetchJsonOrThrowHttp } from './useTickerData'
import { FetchHttpError } from '../utils/errorMessage'

describe('fetchJsonOrThrowHttp', () => {
  beforeEach(() => {
    vi.spyOn(globalThis, 'fetch')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('200 response → returns parsed JSON', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ current_price: 200 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    const result = await fetchJsonOrThrowHttp<{ current_price: number }>('http://test/api')
    expect(result.current_price).toBe(200)
  })

  it('422 → throws FetchHttpError with status=422', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response('{"detail":"未知 ticker"}', {
        status: 422,
        statusText: 'Unprocessable Entity',
        headers: { 'content-type': 'application/json' },
      }),
    )
    await expect(fetchJsonOrThrowHttp('http://test/api')).rejects.toMatchObject({
      name: 'FetchHttpError',
      status: 422,
      statusText: 'Unprocessable Entity',
    })
  })

  it('502 → throws FetchHttpError with status=502', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response('{"detail":"数据源暂不可用"}', {
        status: 502,
        statusText: 'Bad Gateway',
        headers: { 'content-type': 'application/json' },
      }),
    )
    await expect(fetchJsonOrThrowHttp('http://test/api')).rejects.toMatchObject({
      name: 'FetchHttpError',
      status: 502,
    })
  })

  it('error thrown is instanceof FetchHttpError', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(new Response('{}', { status: 500 }))
    try {
      await fetchJsonOrThrowHttp('http://test/api')
      throw new Error('should have thrown')
    } catch (err) {
      expect(err).toBeInstanceOf(FetchHttpError)
      expect((err as FetchHttpError).status).toBe(500)
    }
  })

  it('network error (fetch rejects) → re-throws original error', async () => {
    vi.mocked(globalThis.fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await expect(fetchJsonOrThrowHttp('http://test/api')).rejects.toMatchObject({
      name: 'TypeError',
    })
  })
})
