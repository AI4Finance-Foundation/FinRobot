import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getCapabilityToken, __resetCapabilityTokenCache } from './capability'
import { fetchBackendStream, fetchWithTimeout, RequestTimeoutError } from './fetch'
import { HEAVY_LANE_LIMIT, __resetRequestLanes } from './requestLanes'

vi.mock('./capability', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./capability')>()
  return { ...actual, getCapabilityToken: vi.fn() }
})

const mockGetToken = vi.mocked(getCapabilityToken)

function lastFetchHeaders(): Headers {
  const call = vi.mocked(globalThis.fetch).mock.calls.at(-1)!
  const [input, init] = call
  // string/URL input → header in init; Request input → header on the Request.
  if (input instanceof Request) return input.headers
  return new Headers((init as RequestInit)?.headers)
}

beforeEach(() => {
  __resetCapabilityTokenCache()
  __resetRequestLanes()
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

describe('fetchWithTimeout capability-token injection', () => {
  it('attaches Authorization to a backend URL when a token exists', async () => {
    mockGetToken.mockResolvedValue('cap-123')
    await fetchWithTimeout('/api/settings')
    expect(lastFetchHeaders().get('Authorization')).toBe('Bearer cap-123')
  })

  it('attaches Authorization to the absolute loopback backend URL', async () => {
    mockGetToken.mockResolvedValue('cap-123')
    await fetchWithTimeout('http://127.0.0.1:8321/api/settings')
    expect(lastFetchHeaders().get('Authorization')).toBe('Bearer cap-123')
  })

  it('does NOT attach the token to a third-party host (no off-box leak)', async () => {
    mockGetToken.mockResolvedValue('cap-123')
    await fetchWithTimeout('https://evil.example.com/collect')
    expect(lastFetchHeaders().get('Authorization')).toBeNull()
    expect(mockGetToken).not.toHaveBeenCalled()
  })

  it('does NOT attach the token when an external URL only mentions the backend', async () => {
    mockGetToken.mockResolvedValue('cap-123')
    await fetchWithTimeout(
      'https://evil.example.com/collect?next=http://localhost:8321/api/settings',
    )
    expect(lastFetchHeaders().get('Authorization')).toBeNull()
    expect(mockGetToken).not.toHaveBeenCalled()
  })

  it('does NOT attach the token to a protocol-relative URL', async () => {
    mockGetToken.mockResolvedValue('cap-123')
    await fetchWithTimeout('//evil.example.com/collect')
    expect(lastFetchHeaders().get('Authorization')).toBeNull()
    expect(mockGetToken).not.toHaveBeenCalled()
  })

  it('is a no-op when there is no token (browser dev)', async () => {
    mockGetToken.mockResolvedValue(null)
    await fetchWithTimeout('/api/settings')
    expect(lastFetchHeaders().get('Authorization')).toBeNull()
  })

  it('preserves caller-supplied headers while adding Authorization', async () => {
    mockGetToken.mockResolvedValue('cap-123')
    await fetchWithTimeout('/api/x', { headers: { 'Content-Type': 'application/json' } })
    const h = lastFetchHeaders()
    expect(h.get('Content-Type')).toBe('application/json')
    expect(h.get('Authorization')).toBe('Bearer cap-123')
  })
})

describe('fetchBackendStream', () => {
  it('injects the token for the chat stream', async () => {
    mockGetToken.mockResolvedValue('cap-123')
    await fetchBackendStream('/chat', { method: 'POST' })
    expect(lastFetchHeaders().get('Authorization')).toBe('Bearer cap-123')
  })
})

describe('fetchWithTimeout heavy-lane throttling', () => {
  async function flushMicrotasks(): Promise<void> {
    for (let i = 0; i < 5; i++) await Promise.resolve()
  }

  // A fetch mock whose promises we settle by hand and that honours abort —
  // without abort rejection the lane slot would never free on timeout.
  function deferredFetchMock() {
    const pending: Array<(r: Response) => void> = []
    vi.mocked(globalThis.fetch).mockImplementation(
      (_input, init) =>
        new Promise<Response>((resolve, reject) => {
          init?.signal?.addEventListener('abort', () =>
            reject(new DOMException('The operation was aborted.', 'AbortError')),
          )
          pending.push(resolve)
        }),
    )
    return pending
  }

  it(`dispatches at most ${HEAVY_LANE_LIMIT} concurrent heavy calls`, async () => {
    mockGetToken.mockResolvedValue(null)
    const pending = deferredFetchMock()

    const calls = Array.from({ length: HEAVY_LANE_LIMIT + 1 }, (_, i) =>
      fetchWithTimeout(`/api/data/T${i}/price`),
    )
    await flushMicrotasks()
    expect(globalThis.fetch).toHaveBeenCalledTimes(HEAVY_LANE_LIMIT)

    pending[0](new Response('{}', { status: 200 }))
    await flushMicrotasks()
    expect(globalThis.fetch).toHaveBeenCalledTimes(HEAVY_LANE_LIMIT + 1)

    for (const resolve of pending.slice(1)) resolve(new Response('{}', { status: 200 }))
    await Promise.all(calls)
  })

  it('lets fast local reads bypass a saturated heavy lane', async () => {
    mockGetToken.mockResolvedValue(null)
    const pending = deferredFetchMock()

    const heavy = Array.from({ length: HEAVY_LANE_LIMIT + 2 }, (_, i) =>
      fetchWithTimeout(`/api/data/T${i}/price`),
    )
    await flushMicrotasks()
    expect(globalThis.fetch).toHaveBeenCalledTimes(HEAVY_LANE_LIMIT)

    // The local-DB read must go straight through — this IS the workspace bug.
    const timeline = fetchWithTimeout('/api/artifacts/by-ticker/MSFT/timeline?limit=200')
    await flushMicrotasks()
    expect(globalThis.fetch).toHaveBeenCalledTimes(HEAVY_LANE_LIMIT + 1)

    for (const resolve of pending) resolve(new Response('{}', { status: 200 }))
    await flushMicrotasks()
    for (const resolve of pending) resolve(new Response('{}', { status: 200 }))
    await Promise.all([...heavy, timeline])
  })

  it('starts the timeout clock at dispatch, not while queued', async () => {
    vi.useFakeTimers()
    try {
      mockGetToken.mockResolvedValue(null)
      const pending = deferredFetchMock()

      const blockers = Array.from({ length: HEAVY_LANE_LIMIT }, (_, i) =>
        fetchWithTimeout(`/api/data/B${i}/price`, {}, 60_000),
      )
      await flushMicrotasks()

      let outcome: 'pending' | 'resolved' | 'rejected' = 'pending'
      // Observer chain never rejects (it swallows the error into its value),
      // so nothing is ever "unhandled" no matter when the rejection lands.
      const observed = fetchWithTimeout('/api/data/Q/price', {}, 50).then(
        () => {
          outcome = 'resolved'
          return null
        },
        (err: unknown) => {
          outcome = 'rejected'
          return err
        },
      )
      // 1 s in the queue — far past its own 50 ms budget — must NOT time out.
      await vi.advanceTimersByTimeAsync(1_000)
      expect(outcome).toBe('pending')

      // Free a slot → dispatch → its 50 ms clock starts NOW.
      pending[0](new Response('{}', { status: 200 }))
      await flushMicrotasks()
      await vi.advanceTimersByTimeAsync(50)
      expect(outcome).toBe('rejected')
      expect(await observed).toBeInstanceOf(RequestTimeoutError)

      for (const resolve of pending.slice(1)) resolve(new Response('{}', { status: 200 }))
      await Promise.all(blockers)
    } finally {
      vi.useRealTimers()
    }
  })

  it('frees the lane slot when an abort cancels a queued heavy call', async () => {
    mockGetToken.mockResolvedValue(null)
    const pending = deferredFetchMock()

    const blockers = Array.from({ length: HEAVY_LANE_LIMIT }, (_, i) =>
      fetchWithTimeout(`/api/data/B${i}/price`),
    )
    await flushMicrotasks()

    const controller = new AbortController()
    const queued = fetchWithTimeout('/api/data/Q/price', { signal: controller.signal })
    controller.abort()
    await expect(queued).rejects.toMatchObject({ name: 'AbortError' })
    // It never reached fetch.
    expect(globalThis.fetch).toHaveBeenCalledTimes(HEAVY_LANE_LIMIT)

    // Capacity intact: freeing one slot dispatches exactly one more.
    const extra = fetchWithTimeout('/api/data/E/price')
    await flushMicrotasks()
    expect(globalThis.fetch).toHaveBeenCalledTimes(HEAVY_LANE_LIMIT)
    pending[0](new Response('{}', { status: 200 }))
    await flushMicrotasks()
    expect(globalThis.fetch).toHaveBeenCalledTimes(HEAVY_LANE_LIMIT + 1)

    for (const resolve of pending.slice(1)) resolve(new Response('{}', { status: 200 }))
    await flushMicrotasks()
    for (const resolve of pending) resolve(new Response('{}', { status: 200 }))
    await Promise.all([...blockers, extra])
  })
})
