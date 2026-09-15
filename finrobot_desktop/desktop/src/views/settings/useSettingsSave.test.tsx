import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useSettingsSave } from './useSettingsSave'

vi.mock('../../api/client', () => ({
  api: { PUT: vi.fn() },
}))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (k: string) => k }) }))
vi.mock('../../stores/toastStore', () => ({ useToastStore: () => vi.fn() }))

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('useSettingsSave', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('keeps a failed flush payload available for Retry', async () => {
    vi.mocked(api.PUT)
      .mockResolvedValueOnce({ data: undefined, error: { detail: 'backend down' } } as never)
      .mockResolvedValueOnce({ data: { model_name: 'openai:gpt-4o' }, error: undefined } as never)

    const { result } = renderHook(() => useSettingsSave(), { wrapper })

    act(() => {
      result.current.initializedRef.current = true
      result.current.scheduleStandardSave({ model_name: 'openai:gpt-4o' })
    })

    let thrown: unknown
    await act(async () => {
      try {
        await result.current.flushPending()
      } catch (err) {
        thrown = err
      }
    })

    expect(thrown).toBeInstanceOf(Error)
    expect(api.PUT).toHaveBeenCalledTimes(1)

    act(() => {
      result.current.retrySave()
    })

    await waitFor(() => expect(api.PUT).toHaveBeenCalledTimes(2))
    expect(api.PUT).toHaveBeenLastCalledWith('/api/settings', {
      body: { model_name: 'openai:gpt-4o' },
    })
  })
})
