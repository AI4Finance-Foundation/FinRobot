import { beforeEach, describe, expect, it } from 'vitest'

import {
  HEAVY_LANE_LIMIT,
  __resetRequestLanes,
  acquireHeavySlot,
  isHeavyApiPath,
} from './requestLanes'

beforeEach(() => {
  __resetRequestLanes()
})

// Resolves once microtasks have drained — lets us assert "still queued".
async function flushMicrotasks(): Promise<void> {
  for (let i = 0; i < 5; i++) await Promise.resolve()
}

describe('isHeavyApiPath', () => {
  it.each([
    '/api/data/AAPL/price?period=1y',
    '/api/data/MSFT/catalysts',
    '/api/sentiment/MSFT?days=7',
    '/api/valuation/historical-bands/MSFT',
    '/api/compute/dcf-seed',
    '/api/search?q=apple',
    '/api/sec-holdings/AAPL/holders',
    'http://127.0.0.1:8321/api/compute/dcf-seed',
  ])('classifies %s as heavy (live provider / compute)', (url) => {
    expect(isHeavyApiPath(url)).toBe(true)
  })

  it.each([
    '/api/artifacts/by-ticker/MSFT/timeline?limit=200&include_signals=false',
    '/api/artifacts/art_123',
    '/api/runs?status=created,running',
    '/api/coverage/overview',
    '/api/settings',
    '/api/health/quotes-warmed',
    '/api/chat-sessions',
    '/api/dashboard/hit-rate',
    '/openapi.json',
  ])('classifies %s as fast (local read — must never queue)', (url) => {
    expect(isHeavyApiPath(url)).toBe(false)
  })

  it('classifies a prebuilt Request object by its URL', () => {
    expect(isHeavyApiPath(new Request('http://127.0.0.1:8321/api/data/AAPL/price'))).toBe(true)
    expect(
      isHeavyApiPath(new Request('http://127.0.0.1:8321/api/artifacts/by-ticker/A/timeline')),
    ).toBe(false)
  })

  it('classifies a URL object', () => {
    expect(isHeavyApiPath(new URL('http://127.0.0.1:8321/api/sentiment/KO?days=30'))).toBe(true)
  })

  it('does not treat a heavy path mentioned in a query string as heavy', () => {
    expect(isHeavyApiPath('/api/artifacts/x?next=/api/data/AAPL/price')).toBe(false)
  })
})

describe('acquireHeavySlot', () => {
  it(`grants up to ${HEAVY_LANE_LIMIT} slots immediately and queues the next`, async () => {
    const releases: Array<() => void> = []
    for (let i = 0; i < HEAVY_LANE_LIMIT; i++) releases.push(await acquireHeavySlot())

    let granted = false
    const queued = acquireHeavySlot().then((r) => {
      granted = true
      return r
    })
    await flushMicrotasks()
    expect(granted).toBe(false)

    releases[0]()
    await flushMicrotasks()
    expect(granted).toBe(true)
    ;(await queued)()
    for (const r of releases.slice(1)) r()
  })

  it('wakes queued waiters in FIFO order', async () => {
    const releases: Array<() => void> = []
    for (let i = 0; i < HEAVY_LANE_LIMIT; i++) releases.push(await acquireHeavySlot())

    const order: string[] = []
    const a = acquireHeavySlot().then((r) => {
      order.push('a')
      return r
    })
    const b = acquireHeavySlot().then((r) => {
      order.push('b')
      return r
    })

    releases[0]()
    await flushMicrotasks()
    expect(order).toEqual(['a'])
    releases[1]()
    await flushMicrotasks()
    expect(order).toEqual(['a', 'b'])
    ;(await a)()
    ;(await b)()
  })

  it('rejects with AbortError when aborted while queued and gives up the spot', async () => {
    const releases: Array<() => void> = []
    for (let i = 0; i < HEAVY_LANE_LIMIT; i++) releases.push(await acquireHeavySlot())

    const controller = new AbortController()
    const abortedWaiter = acquireHeavySlot(controller.signal)
    let nextGranted = false
    const nextWaiter = acquireHeavySlot().then((r) => {
      nextGranted = true
      return r
    })

    controller.abort()
    await expect(abortedWaiter).rejects.toMatchObject({ name: 'AbortError' })

    // The aborted waiter must not consume the freed slot — the next one gets it.
    releases[0]()
    await flushMicrotasks()
    expect(nextGranted).toBe(true)
    ;(await nextWaiter)()
  })

  it('rejects immediately on a pre-aborted signal without taking a slot', async () => {
    const controller = new AbortController()
    controller.abort()
    await expect(acquireHeavySlot(controller.signal)).rejects.toMatchObject({
      name: 'AbortError',
    })
    // Lane must still have full capacity.
    const releases: Array<() => void> = []
    for (let i = 0; i < HEAVY_LANE_LIMIT; i++) releases.push(await acquireHeavySlot())
    releases.forEach((r) => r())
  })

  it('ignores double-release (idempotent) so capacity never inflates', async () => {
    const first = await acquireHeavySlot()
    const releases: Array<() => void> = []
    for (let i = 1; i < HEAVY_LANE_LIMIT; i++) releases.push(await acquireHeavySlot())

    first()
    first() // double-release must be a no-op

    // Only ONE slot is actually free: the first new acquire is immediate,
    // the second must queue.
    await acquireHeavySlot()
    let granted = false
    void acquireHeavySlot().then((r) => {
      granted = true
      r()
    })
    await flushMicrotasks()
    expect(granted).toBe(false)
    releases.forEach((r) => r())
  })
})
