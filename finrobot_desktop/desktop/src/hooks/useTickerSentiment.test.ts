import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchSentimentSnapshot } from './useTickerSentiment'

describe('fetchSentimentSnapshot', () => {
  beforeEach(() => {
    vi.spyOn(globalThis, 'fetch')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('non-2xx response carries backend detail into FetchHttpError', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response('{"detail":"ticker ZZZZ 不存在"}', {
        status: 422,
        statusText: 'Unprocessable Entity',
        headers: { 'content-type': 'application/json' },
      }),
    )

    await expect(fetchSentimentSnapshot('ZZZZ')).rejects.toMatchObject({
      name: 'FetchHttpError',
      status: 422,
      statusText: 'Unprocessable Entity',
      detail: 'ticker ZZZZ 不存在',
    })
  })
})
