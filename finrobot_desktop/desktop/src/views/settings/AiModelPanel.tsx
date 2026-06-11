// ─── AI Model panel ───────────────────────────────────────────────────────────
// Provider picker (built-ins + customs + "add custom"), model id input, the
// selected provider's API key, and the live "Test connection" probe. All edit
// state lives in SettingsView (the container) so it survives panel switches —
// this component is pure render + handler composition over props.

import { api } from '../../api/client'
import { useToastStore } from '../../stores/toastStore'
import { useI18n } from '../../i18n'
import type { components } from '../../api/schema'
import { SecretInput } from './controls'
import { ProviderDropdown, type ProviderOption } from './ProviderDropdown'

type ProviderInfo = components['schemas']['ProviderInfo']
type ProviderConfig = components['schemas']['ProviderConfig']

/** Draft for the "add custom provider" form. The name doubles as the provider
 * id (no separate id field); a single model id (no list). */
export interface DraftProvider {
  name: string
  baseUrl: string
  modelId: string
  apiKey: string
}

/** Result of the most recent "Test connection" click for the selected provider. */
export interface LlmTestState {
  status: 'idle' | 'testing' | 'done'
  ok?: boolean
  code?: string
  detail?: string
}

interface AiModelPanelProps {
  providers: ProviderInfo[]
  customProviders: ProviderConfig[]
  /** settingsResp.model_name — fallback when no local edit yet. */
  serverModelName: string | undefined
  modelName: string
  setModelName: (v: string) => void
  llmApiKey: string
  setLlmApiKey: (v: string) => void
  addingCustom: boolean
  setAddingCustom: (v: boolean) => void
  draftProvider: DraftProvider
  setDraftProvider: React.Dispatch<React.SetStateAction<DraftProvider>>
  testState: LlmTestState
  setTestState: (v: LlmTestState) => void
  scheduleStandardSave: (payload: Record<string, unknown>) => void
  onClearSecret: (field: string) => void
}

export function AiModelPanel({
  providers,
  customProviders,
  serverModelName,
  modelName,
  setModelName,
  llmApiKey,
  setLlmApiKey,
  addingCustom,
  setAddingCustom,
  draftProvider,
  setDraftProvider,
  testState,
  setTestState,
  scheduleStandardSave,
  onClearSecret,
}: AiModelPanelProps): React.ReactElement {
  const { t } = useI18n()
  const addToast = useToastStore((s) => s.addToast)

  // ── Model selection (provider registry) ──────────────────────────────────
  const effectiveModelName = modelName || serverModelName || ''
  const currentProviderId = effectiveModelName.split(':')[0]
  const currentModelId = effectiveModelName.split(':').slice(1).join(':')
  const currentProviderInfo = providers.find((p) => p.id === currentProviderId)
  const currentIsCustom = currentProviderInfo ? !currentProviderInfo.is_builtin : false
  // Options for the provider dropdown.
  const providerOptions: ProviderOption[] = providers.map((p) => ({
    id: p.id,
    label: p.label,
    is_builtin: p.is_builtin,
  }))
  const llmKeyConfigured = currentProviderInfo?.key_set ?? false

  const handleProviderChange = (providerId: string) => {
    const p = providers.find((x) => x.id === providerId)
    // Keep the current model id if the new provider lists it, else fall back to
    // its first suggested model, else leave blank for the user to type one.
    const nextModel =
      p && currentModelId && p.models.includes(currentModelId)
        ? currentModelId
        : (p?.models[0] ?? '')
    const next = `${providerId}:${nextModel}`
    setModelName(next)
    setLlmApiKey('')
    setAddingCustom(false)
    setTestState({ status: 'idle' })
    scheduleStandardSave({ model_name: next })
  }
  const handleModelIdChange = (mid: string) => {
    const next = `${currentProviderId}:${mid}`
    setModelName(next)
    setTestState({ status: 'idle' })
    scheduleStandardSave({ model_name: next })
  }
  const handleLlmKeyChange = (v: string) => {
    setLlmApiKey(v)
    setTestState({ status: 'idle' })
    if (!v.trim()) return
    scheduleStandardSave({ provider_keys: { [currentProviderId]: v.trim() } })
  }
  const handleTestConnection = async () => {
    setTestState({ status: 'testing' })
    try {
      const { data, error } = await api.POST('/api/settings/test-provider', {
        body: { provider_id: currentProviderId, model_id: currentModelId || null },
      })
      if (error || !data) throw new Error('test failed')
      setTestState({ status: 'done', ok: data.ok, code: data.code, detail: data.detail })
    } catch {
      setTestState({ status: 'done', ok: false, code: 'unknown' })
    }
  }

  // ── Custom provider add / edit / delete (full-list replace) ───────────────
  // A custom provider's name doubles as its id (the "<id>:<model>" prefix), so
  // we strip any ':' from it. models holds a single suggested model id.
  const serializeCustomProviders = (list: typeof customProviders) =>
    list.map((p) => ({
      id: p.id,
      label: p.label,
      kind: p.kind,
      base_url: p.base_url,
      models: p.models,
    }))
  const handleAddCustomProvider = () => {
    const name = draftProvider.name.trim().replace(/:/g, '')
    const baseUrl = draftProvider.baseUrl.trim()
    if (!name || !baseUrl) {
      addToast({ type: 'error', title: t('settings.customProvider.incompleteTitle') })
      return
    }
    const modelId = draftProvider.modelId.trim()
    const next = [
      ...serializeCustomProviders(customProviders),
      {
        id: name,
        label: name,
        kind: 'openai-compatible' as const,
        base_url: baseUrl,
        models: modelId ? [modelId] : [],
      },
    ]
    const payload: Record<string, unknown> = {
      custom_providers: next,
      model_name: `${name}:${modelId}`,
    }
    if (draftProvider.apiKey.trim()) payload.provider_keys = { [name]: draftProvider.apiKey.trim() }
    scheduleStandardSave(payload)
    setModelName(`${name}:${modelId}`) // select the new provider
    setLlmApiKey('')
    setTestState({ status: 'idle' })
    setDraftProvider({ name: '', baseUrl: '', modelId: '', apiKey: '' })
    setAddingCustom(false)
  }
  // Inline-edit the base_url of the currently-selected custom provider.
  const handleEditCustomBaseUrl = (id: string, value: string) => {
    const next = serializeCustomProviders(customProviders).map((p) =>
      p.id === id ? { ...p, base_url: value.trim() } : p,
    )
    scheduleStandardSave({ custom_providers: next })
  }
  const handleDeleteCustomProvider = (id: string) => {
    const next = serializeCustomProviders(customProviders.filter((p) => p.id !== id))
    // Fall back to the first built-in provider after deleting the active one.
    const fallback = providers.find((p) => p.is_builtin)
    const nextModel = currentProviderId === id && fallback ? `${fallback.id}:` : undefined
    const payload: Record<string, unknown> = { custom_providers: next }
    if (nextModel) {
      payload.model_name = nextModel
      setModelName(nextModel)
    }
    scheduleStandardSave(payload)
  }

  return (
    <section className="settings-section" data-section="aiModel">
      <h2 className="settings-section-title">{t('settings.section.aiModel')}</h2>

      {!llmKeyConfigured && (
        <div className="settings-onboard">
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden>
            <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.3" />
            <path d="M8 5v3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            <circle cx="8" cy="11" r="0.6" fill="currentColor" />
          </svg>
          <div>
            <p className="settings-onboard-title">{t('settings.onboarding.title')}</p>
            <p className="settings-onboard-body">{t('settings.onboarding.body')}</p>
          </div>
        </div>
      )}

      <div className="settings-fields">
        {/* Provider — custom dropdown (built-ins + customs + "add") */}
        <div className="settings-field">
          <label className="settings-field-label">
            <span className="label-text">{t('settings.provider.label')}</span>
          </label>
          <ProviderDropdown
            options={providerOptions}
            value={currentProviderId}
            onSelect={handleProviderChange}
            onAddCustom={() => setAddingCustom(true)}
          />
        </div>

        {addingCustom ? (
          /* Add a custom OpenAI-compatible provider */
          <div className="settings-custom-box">
            <p className="settings-custom-box-title">{t('settings.customProvider.title')}</p>
            <div className="settings-field">
              <label className="settings-field-label">
                <span className="label-text">{t('settings.customProvider.name')}</span>
              </label>
              <input
                className="settings-input"
                value={draftProvider.name}
                onChange={(e) => setDraftProvider((d) => ({ ...d, name: e.target.value }))}
                placeholder="OpenRouter"
                autoComplete="off"
              />
            </div>
            <div className="settings-field">
              <label className="settings-field-label">
                <span className="label-text">{t('settings.customProvider.baseUrl')}</span>
              </label>
              <input
                className="settings-input"
                value={draftProvider.baseUrl}
                onChange={(e) =>
                  setDraftProvider((d) => ({ ...d, baseUrl: e.target.value.trim() }))
                }
                placeholder="https://openrouter.ai/api/v1"
                autoComplete="off"
                spellCheck={false}
              />
            </div>
            <div className="settings-field">
              <label className="settings-field-label">
                <span className="label-text">{t('settings.model.label')}</span>
              </label>
              <input
                className="settings-input"
                value={draftProvider.modelId}
                onChange={(e) =>
                  setDraftProvider((d) => ({ ...d, modelId: e.target.value.trim() }))
                }
                placeholder={t('settings.model.idPlaceholder')}
                autoComplete="off"
                spellCheck={false}
              />
            </div>
            <div className="settings-field">
              <label className="settings-field-label">
                <span className="label-text">{t('settings.customProvider.apiKey')}</span>
              </label>
              <SecretInput
                value={draftProvider.apiKey}
                onChange={(v) => setDraftProvider((d) => ({ ...d, apiKey: v }))}
                placeholder={t('settings.customProvider.apiKeyPlaceholder')}
              />
            </div>
            <div className="settings-form-actions">
              <button
                type="button"
                className="settings-btn is-primary"
                onClick={handleAddCustomProvider}
              >
                {t('settings.customProvider.add')}
              </button>
              <button
                type="button"
                className="settings-btn"
                onClick={() => {
                  setAddingCustom(false)
                  setDraftProvider({ name: '', baseUrl: '', modelId: '', apiKey: '' })
                }}
              >
                {t('settings.customProvider.cancel')}
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* Model id — free text, with the provider's models as hints */}
            <div className="settings-field">
              <label className="settings-field-label">
                <span className="label-text">{t('settings.model.label')}</span>
              </label>
              <input
                className="settings-input"
                list="model-id-suggestions"
                value={currentModelId}
                onChange={(e) => handleModelIdChange(e.target.value)}
                placeholder={t('settings.model.idPlaceholder')}
                autoComplete="off"
                spellCheck={false}
              />
              <datalist id="model-id-suggestions">
                {(currentProviderInfo?.models ?? []).map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>

            {/* Custom provider: editable base_url + delete (the model id
              is the shared input above). */}
            {currentIsCustom && currentProviderInfo && (
              <div className="settings-custom-box">
                <div className="settings-field">
                  <label className="settings-field-label">
                    <span className="label-text">{t('settings.customProvider.baseUrl')}</span>
                  </label>
                  <input
                    className="settings-input"
                    defaultValue={currentProviderInfo.base_url ?? ''}
                    onBlur={(e) => handleEditCustomBaseUrl(currentProviderId, e.target.value)}
                    autoComplete="off"
                    spellCheck={false}
                  />
                </div>
                <button
                  type="button"
                  className="settings-delete-link"
                  onClick={() => handleDeleteCustomProvider(currentProviderId)}
                >
                  {t('settings.customProvider.remove')}
                </button>
              </div>
            )}

            {/* API key for the selected provider */}
            <div className="settings-field">
              <label className="settings-field-label">
                <span className="label-text">
                  {t('settings.llm.apiKeyLabelFor', {
                    provider: currentProviderInfo?.label ?? currentProviderId,
                  })}
                </span>
                {llmKeyConfigured ? (
                  <span className="settings-badge is-ok">{t('settings.badge.configured')}</span>
                ) : (
                  <span className="settings-badge is-required">{t('settings.badge.required')}</span>
                )}
                {llmKeyConfigured && (
                  <button
                    type="button"
                    className="settings-clear-btn"
                    onClick={() => onClearSecret(`provider_key:${currentProviderId}`)}
                  >
                    {t('settings.clearKey.button')}
                  </button>
                )}
              </label>
              <SecretInput
                value={llmApiKey}
                onChange={handleLlmKeyChange}
                placeholder={
                  llmKeyConfigured
                    ? '••••••••'
                    : t('settings.llm.apiKeyPlaceholder', {
                        provider: currentProviderInfo?.label ?? currentProviderId,
                      })
                }
              />
              <div className="settings-test-row">
                <button
                  type="button"
                  className="settings-btn"
                  onClick={handleTestConnection}
                  disabled={testState.status === 'testing'}
                >
                  {testState.status === 'testing'
                    ? t('settings.test.testing')
                    : t('settings.test.button')}
                </button>
                {testState.status === 'done' && (
                  <span className={`settings-test-result${testState.ok ? ' is-ok' : ' is-bad'}`}>
                    {testState.ok ? '✓ ' : '✗ '}
                    {t(`settings.test.result.${testState.code ?? 'unknown'}`)}
                    {!testState.ok && testState.detail && testState.code === 'http'
                      ? ` (${testState.detail})`
                      : ''}
                  </span>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
