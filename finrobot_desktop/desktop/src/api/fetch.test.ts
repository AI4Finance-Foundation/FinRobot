import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getCapabilityToken, __resetCapabilityTokenCache } from './capability'
import { fetchBackendStream, fetchWithTimeout } from './fetch'

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
