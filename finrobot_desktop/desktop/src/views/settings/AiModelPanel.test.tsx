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
    flushPending: vi.fn().mockResolvedValue(undefined),
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

  it('does not show the provider first suggestion as a fake model default', () => {
    renderPanel({ modelName: 'anthropic:', serverModelName: 'anthropic:' })

    expect(screen.getByPlaceholderText('settings.model.idPlaceholder')).toBeEnabled()
    expect(screen.queryByPlaceholderText('claude-sonnet-4-6')).not.toBeInTheDocument()
  })

  it('disables model/key/test controls until a provider is selected', () => {
    renderPanel({ modelName: '', serverModelName: '' })

    expect(screen.getByPlaceholderText('settings.model.idPlaceholder')).toBeDisabled()
    expect(keyInput()).toBeDisabled()
    expect(screen.getByRole('button', { name: 'settings.test.button' })).toBeDisabled()

    fireEvent.change(keyInput(), { target: { value: 'sk-should-not-save' } })
    expect(saveSpy).not.toHaveBeenCalled()
  })

  it('normalizes a custom provider id before saving model_name and provider_keys', async () => {
    renderPanel({
      addingCustom: true,
      draftProvider: {
        name: 'OpenRouter',
        baseUrl: 'https://openrouter.ai/api/v1',
        modelId: 'openai/gpt-4o-mini',
        apiKey: 'sk-openrouter',
      },
    })

    fireEvent.click(screen.getByRole('button', { name: 'settings.customProvider.add' }))

    expect(saveSpy).toHaveBeenCalledWith(
      {
        custom_providers: [
          {
            id: 'openrouter',
            label: 'OpenRouter',
            kind: 'openai-compatible',
            base_url: 'https://openrouter.ai/api/v1',
            models: ['openai/gpt-4o-mini'],
          },
        ],
        model_name: 'openrouter:openai/gpt-4o-mini',
        provider_keys: { openrouter: 'sk-openrouter' },
      },
      expect.any(Function),
    )
    await vi.waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith('/api/settings/test-provider', {
        body: { provider_id: 'openrouter', model_id: 'openai/gpt-4o-mini' },
      }),
    )
  })

  it('flushes the pending save BEFORE the manual Test probe (no test-before-save race)', async () => {
    // Regression for "every key had to be configured 2-3 times": clicking Test
    // inside the 500ms auto-save window must persist the on-screen key FIRST,
    // else the backend probes a key it hasn't stored yet and reports "no key".
    const flushPending = vi.fn().mockResolvedValue(undefined)
    renderPanel({ flushPending })
    fireEvent.click(screen.getByRole('button', { name: 'settings.test.button' }))

    await vi.waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith('/api/settings/test-provider', {
        body: { provider_id: 'anthropic', model_id: 'claude-sonnet-4-6' },
      }),
    )
    expect(flushPending).toHaveBeenCalled()
    // Ordering is the whole point: flush must complete before the probe fires.
    expect(flushPending.mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(api.POST).mock.invocationCallOrder[0],
    )
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
