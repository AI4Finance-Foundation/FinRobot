import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { api } from '../../api/client'
import { AiModelPanel, type DraftProvider, type LlmTestState } from './AiModelPanel'

// Auto-test-on-save wiring: the instant a COMPLETE provider+model+key config is
// saved, AiModelPanel fires the live /test-provider probe so a wrong key shows
// ✗ at config time (soft-block — the key is still saved, the user just retries).
// scheduleStandardSave is stubbed to invoke its onSaved synchronously, so these
// assert the wiring without the real debounce/react-query timing (non-flaky).

vi.mock('../../api/client', () => ({
  api: { POST: vi.fn(), PUT: vi.fn() },
  BASE_URL: 'http://127.0.0.1:8321',
}))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (k: string) => k, locale: 'en' }) }))
vi.mock('../../stores/toastStore', () => ({ useToastStore: () => vi.fn() }))

const ANTHROPIC = {
  id: 'anthropic',
  label: 'Anthropic',
  kind: 'anthropic',
  base_url: null,
  models: ['claude-sonnet-4-6'],
  key_set: false,
  is_builtin: true,
}

// scheduleStandardSave stub that runs onSaved immediately (stands in for "the
// debounced PUT landed"). Exposed so tests can assert the saved payload too.
const saveSpy = vi.fn((_payload: Record<string, unknown>, onSaved?: () => void) => onSaved?.())

function renderPanel(over: Partial<React.ComponentProps<typeof AiModelPanel>> = {}) {
  const props: React.ComponentProps<typeof AiModelPanel> = {
    providers: [ANTHROPIC],
    customProviders: [],
    serverModelName: 'anthropic:claude-sonnet-4-6',
    modelName: 'anthropic:claude-sonnet-4-6',
    setModelName: vi.fn(),
    llmApiKey: '',
    setLlmApiKey: vi.fn(),
    addingCustom: false,
    setAddingCustom: vi.fn(),
    draftProvider: { name: '', baseUrl: '', modelId: '', apiKey: '' } as DraftProvider,
    setDraftProvider: vi.fn(),
    testState: { status: 'idle' } as LlmTestState,
    setTestState: vi.fn(),
    scheduleStandardSave: saveSpy,
    onClearSecret: vi.fn(),
    ...over,
  }
  return render(<AiModelPanel {...props} />)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.POST).mockResolvedValue({
    data: { ok: false, code: 'auth', detail: 'invalid key' },
    error: undefined,
  } as never)
})

const keyInput = () => screen.getByPlaceholderText('settings.llm.apiKeyPlaceholder')

describe('AiModelPanel auto-test on save', () => {
  it('saves the key AND auto-runs /test-provider when a model is selected', async () => {
    renderPanel()
    fireEvent.change(keyInput(), { target: { value: 'sk-bad-key' } })

    // Soft-block: the key is still persisted...
    expect(saveSpy).toHaveBeenCalledWith(
      { provider_keys: { anthropic: 'sk-bad-key' } },
      expect.any(Function),
    )
    // ...and the live probe fired with the exact provider+model.
    expect(api.POST).toHaveBeenCalledWith('/api/settings/test-provider', {
      body: { provider_id: 'anthropic', model_id: 'claude-sonnet-4-6' },
    })
  })

  it('does NOT auto-test when no model is chosen yet (probe has nothing to call)', () => {
    renderPanel({ modelName: 'anthropic:', serverModelName: 'anthropic:' })
    fireEvent.change(keyInput(), { target: { value: 'sk-x' } })

    // Key still saved, but onSaved is undefined → no probe.
    expect(saveSpy).toHaveBeenCalledWith({ provider_keys: { anthropic: 'sk-x' } }, undefined)
    expect(api.POST).not.toHaveBeenCalled()
  })

  it('surfaces the failure verdict (✗ auth) without rolling back the save', async () => {
    const setTestState = vi.fn()
    renderPanel({ setTestState })
    fireEvent.change(keyInput(), { target: { value: 'sk-bad-key' } })

    // testConnection flips to "testing" then resolves to the failed verdict.
    expect(setTestState).toHaveBeenCalledWith({ status: 'testing' })
    await vi.waitFor(() =>
      expect(setTestState).toHaveBeenCalledWith({
        status: 'done',
        ok: false,
        code: 'auth',
        detail: 'invalid key',
      }),
    )
  })
})
