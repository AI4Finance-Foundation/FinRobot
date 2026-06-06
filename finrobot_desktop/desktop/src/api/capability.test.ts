import { afterEach, describe, expect, it, vi } from 'vitest'

import { isTauri } from '../lib/tauri'
import { invoke } from '@tauri-apps/api/core'
import { __resetCapabilityTokenCache, getCapabilityToken, withCapabilityToken } from './capability'

vi.mock('../lib/tauri', () => ({ isTauri: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))

const mockIsTauri = vi.mocked(isTauri)
const mockInvoke = vi.mocked(invoke)

afterEach(() => {
  __resetCapabilityTokenCache()
  vi.clearAllMocks()
})

describe('getCapabilityToken', () => {
  it('returns null in a plain browser (not Tauri) and never invokes', async () => {
    mockIsTauri.mockReturnValue(false)
    expect(await getCapabilityToken()).toBeNull()
    expect(mockInvoke).not.toHaveBeenCalled()
  })

  it('reads the token from the Tauri command when in Tauri', async () => {
    mockIsTauri.mockReturnValue(true)
    mockInvoke.mockResolvedValue('cap-tok-123')
    expect(await getCapabilityToken()).toBe('cap-tok-123')
    expect(mockInvoke).toHaveBeenCalledWith('capability_token')
  })

  it('memoizes — the command is only crossed once across many calls', async () => {
    mockIsTauri.mockReturnValue(true)
    mockInvoke.mockResolvedValue('cap-tok-123')
    await Promise.all([getCapabilityToken(), getCapabilityToken(), getCapabilityToken()])
    await getCapabilityToken()
    expect(mockInvoke).toHaveBeenCalledTimes(1)
  })

  it('resolves null (does not throw) when the command fails', async () => {
    mockIsTauri.mockReturnValue(true)
    mockInvoke.mockRejectedValue(new Error('no such command'))
    expect(await getCapabilityToken()).toBeNull()
  })
})

describe('withCapabilityToken', () => {
  it('appends ?token= when no existing query', async () => {
    mockIsTauri.mockReturnValue(true)
    mockInvoke.mockResolvedValue('abc')
    expect(await withCapabilityToken('http://x/events')).toBe('http://x/events?token=abc')
  })

  it('appends &token= when a query already exists, url-encoding the token', async () => {
    mockIsTauri.mockReturnValue(true)
    mockInvoke.mockResolvedValue('a/b+c')
    expect(await withCapabilityToken('http://x/e?foo=1')).toBe('http://x/e?foo=1&token=a%2Fb%2Bc')
  })

  it('returns the url unchanged in browser dev (no token)', async () => {
    mockIsTauri.mockReturnValue(false)
    expect(await withCapabilityToken('http://x/events')).toBe('http://x/events')
  })
})
