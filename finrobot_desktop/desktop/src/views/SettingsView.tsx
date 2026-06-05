import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, BASE_URL } from '../api/client'
import { useToastStore } from '../stores/toastStore'
import { useUiStore } from '../stores/uiStore'
import { mapErrorToUserMessage, FetchHttpError } from '../utils/errorMessage'
import { useI18n, tSync } from '../i18n'

interface Props {
  onComplete: () => void
}

// ─── SEC identity validation (mirrors edgar_provider._is_valid_identity) ──────

const SEC_IDENTITY_EXAMPLE = 'Acme Research analyst@example.com'
const SEC_EMAIL_RE = /[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}/

function extractSecEmail(s: string): RegExpMatchArray | null {
  return s.match(SEC_EMAIL_RE)
}

/** SEC requires `Name email@domain` — we also reject the backend's placeholder
 * default `FinRobot admin@example.com` so the user has to set a real one. */
export function isValidSecIdentity(s: string | null | undefined): boolean {
  if (!s) return false
  const trimmed = s.trim()
  if (!trimmed.includes('@') || !trimmed.includes(' ')) return false
  if (trimmed === 'FinRobot admin@example.com') return false
  return extractSecEmail(trimmed) !== null
}

export function secHeaderIdentityPreview(s: string | null | undefined): string | null {
  if (!s || !isValidSecIdentity(s)) return null
  const raw = s.trim()
  const match = extractSecEmail(raw)
  if (!match || match.index === undefined) return null
  const email = match[0]
  const nameBeforeEmail = raw.slice(0, match.index).trim()
  const nameAfterEmail = raw.slice(match.index + email.length).trim()
  const displayName = nameBeforeEmail || nameAfterEmail
  const asciiName = [...displayName]
    .map((ch) => (ch.charCodeAt(0) < 128 ? ch : ' '))
    .join('')
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
  return `${asciiName || 'FinRobot'} ${email}`
}

// ─── Small inline icons (cosmic spec: simple glyphs as inline SVG) ────────────

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d={d}
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
const ICON_MODEL = 'M8 1.5 14 5v6l-6 3.5L2 11V5l6-3.5ZM8 8 14 5M8 8v6.5M8 8 2 5'
const ICON_DATA =
  'M2.5 4c0-1.1 2.5-2 5.5-2s5.5.9 5.5 2-2.5 2-5.5 2-5.5-.9-5.5-2Zm0 0v8c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2V4'
const ICON_SEC = 'M8 1.5 13.5 4v4c0 3.5-2.4 5.6-5.5 6.5C4.9 13.6 2.5 11.5 2.5 8V4L8 1.5Z'
const ICON_DISPLAY = 'M2 3.5h12v7H2v-7Zm4 9.5h4M8 10.5V13'

// ─── Password input with show/hide toggle ────────────────────────────────────

function SecretInput({
  value,
  onChange,
  placeholder,
  invalid,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  invalid?: boolean
}) {
  const { t } = useI18n()
  const [revealed, setRevealed] = useState(false)
  return (
    <div className="settings-input-wrap">
      <input
        className={`settings-input has-trailing${invalid ? ' is-invalid' : ''}`}
        type={revealed ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
      />
      <button
        type="button"
        className="settings-eye"
        aria-label={revealed ? t('settings.key.hide') : t('settings.key.show')}
        title={revealed ? t('settings.key.hide') : t('settings.key.show')}
        onClick={() => setRevealed((r) => !r)}
      >
        {revealed ? (
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden>
            <path
              d="M2 8s2.4-4 6-4 6 4 6 4-2.4 4-6 4-6-4-6-4Z"
              stroke="currentColor"
              strokeWidth="1.3"
            />
            <circle cx="8" cy="8" r="1.8" stroke="currentColor" strokeWidth="1.3" />
          </svg>
        ) : (
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden>
            <path
              d="M2 8s2.4-4 6-4 6 4 6 4-2.4 4-6 4-6-4-6-4Z"
              stroke="currentColor"
              strokeWidth="1.3"
            />
            <path d="m3 3 10 10" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          </svg>
        )}
      </button>
    </div>
  )
}

// ─── Provider dropdown (cosmic-styled, not a native <select>) ────────────────

interface ProviderOption {
  id: string
  label: string
  is_builtin: boolean
}

function ProviderDropdown({
  options,
  value,
  onSelect,
  onAddCustom,
}: {
  options: ProviderOption[]
  value: string
  onSelect: (id: string) => void
  onAddCustom: () => void
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])
  const selected = options.find((o) => o.id === value)
  return (
    <div className="settings-dd" ref={ref}>
      <button
        type="button"
        className="settings-dd-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span>{selected?.label ?? value}</span>
        <svg
          className={`settings-dd-caret${open ? ' is-open' : ''}`}
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          aria-hidden
        >
          <path
            d="M3 4.5 6 7.5 9 4.5"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {open && (
        <ul className="settings-dd-menu" role="listbox">
          {options.map((o) => (
            <li
              key={o.id}
              role="option"
              aria-selected={o.id === value}
              className={`settings-dd-item${o.id === value ? ' is-selected' : ''}`}
              onClick={() => {
                onSelect(o.id)
                setOpen(false)
              }}
            >
              <span className="settings-dd-item-label">{o.label}</span>
              {!o.is_builtin && (
                <span className="settings-dd-tag">{t('settings.provider.customTag')}</span>
              )}
              {o.id === value && (
                <svg
                  className="settings-dd-check"
                  width="13"
                  height="13"
                  viewBox="0 0 16 16"
                  fill="none"
                  aria-hidden
                >
                  <path
                    d="M3 8.5 6.5 12 13 4"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
            </li>
          ))}
          <li
            className="settings-dd-add"
            onClick={() => {
              onAddCustom()
              setOpen(false)
            }}
          >
            <span>＋</span>
            <span>{t('settings.customProvider.addEntry')}</span>
          </li>
        </ul>
      )}
    </div>
  )
}

// ─── Auto-save indicator ───────────────────────────────────────────────────

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

// ─── Section nav (left rail) ─────────────────────────────────────────────────

const NAV_ITEMS = [
  { id: 'aiModel', icon: ICON_MODEL, labelKey: 'settings.section.aiModel' },
  { id: 'dataSources', icon: ICON_DATA, labelKey: 'settings.section.dataSources' },
  { id: 'secHoldings', icon: ICON_SEC, labelKey: 'settings.nav.secHoldings' },
  { id: 'display', icon: ICON_DISPLAY, labelKey: 'settings.appearance.title' },
] as const

// ─── Main component ────────────────────────────────────────────────────────

export default function SettingsView({ onComplete: _onComplete }: Props) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const addToast = useToastStore((s) => s.addToast)

  // ── Remote settings ──────────────────────────────────────────────────────
  const {
    data: settingsResp,
    isLoading,
    isError,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['settings'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/settings')
      if (error) throw new Error(tSync('settings.loadFailed'))
      return data
    },
  })

  // ── Editable local state ───────────────────────────────────────────────────
  const [fmpKey, setFmpKey] = useState('')
  const [finnhubKey, setFinnhubKey] = useState('')
  const [adanosKey, setAdanosKey] = useState('')
  const [alphaVantageKey, setAlphaVantageKey] = useState('')
  const [secUserAgent, setSecUserAgent] = useState('')
  const [modelName, setModelName] = useState('')
  const [llmApiKey, setLlmApiKey] = useState('')
  // When true, the AI Model section shows the "add a custom provider" form
  // (triggered from the provider dropdown's "＋ add" entry).
  const [addingCustom, setAddingCustom] = useState(false)
  // Draft for the "add custom provider" form. The name doubles as the provider
  // id (no separate id field); a single model id (no list).
  const [draftProvider, setDraftProvider] = useState({
    name: '',
    baseUrl: '',
    modelId: '',
    apiKey: '',
  })
  // Result of the most recent "Test connection" click for the selected provider.
  const [testState, setTestState] = useState<{
    status: 'idle' | 'testing' | 'done'
    ok?: boolean
    code?: string
    detail?: string
  }>({ status: 'idle' })
  // Same, but per data-source ("fmp" | "finnhub") — each key field tests on its own.
  const [dataTestState, setDataTestState] = useState<
    Record<
      string,
      { status: 'idle' | 'testing' | 'done'; ok?: boolean; code?: string; detail?: string }
    >
  >({})

  // Pending SECRET field awaiting confirmation before its stored keychain key is
  // deleted via POST /api/settings/clear-secret (BUG-005).
  const [pendingClearSecret, setPendingClearSecret] = useState<string | null>(null)

  // ── Save indicator ───────────────────────────────────────────────────────
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const initializedRef = useRef(false)
  const lastPayloadRef = useRef<Record<string, unknown> | null>(null)

  // ── Active nav section (scroll-spy) ──────────────────────────────────────
  const [activeSection, setActiveSection] = useState<string>('aiModel')
  const sectionRefs = useRef<Record<string, HTMLElement | null>>({})

  // Populate editable fields from the server on first load.
  useEffect(() => {
    if (!settingsResp || initializedRef.current) return
    initializedRef.current = true
    if (settingsResp.model_name) setModelName(settingsResp.model_name)
    if (settingsResp.sec_user_agent) setSecUserAgent(settingsResp.sec_user_agent)
  }, [settingsResp])

  // Highlight the nav item for whichever section is nearest the top.
  useEffect(() => {
    if (isLoading || isError) return
    if (typeof IntersectionObserver === 'undefined') return // jsdom / older runtimes
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]?.target instanceof HTMLElement) {
          const id = visible[0].target.dataset.section
          if (id) setActiveSection(id)
        }
      },
      { rootMargin: '-10% 0px -70% 0px', threshold: 0 },
    )
    for (const el of Object.values(sectionRefs.current)) {
      if (el) observer.observe(el)
    }
    return () => observer.disconnect()
  }, [isLoading, isError, settingsResp])

  const scrollToSection = (id: string) => {
    setActiveSection(id)
    sectionRefs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  // ── PUT /api/settings mutation (debounced auto-save) ─────────────────────
  const settingsMutation = useMutation({
    mutationFn: async (body: Record<string, string | null>) => {
      const { data, error } = await api.PUT('/api/settings', { body: body as never })
      if (error) {
        const detail = (error as { detail?: string }).detail
        throw new Error(detail || 'Settings update failed')
      }
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['settings'], data)
      lastPayloadRef.current = null
      setSaveState('saved')
      saveTimerRef.current = setTimeout(() => setSaveState('idle'), 2500)
    },
    onError: (err: Error) => {
      setSaveState('error')
      addToast({
        type: 'error',
        title: t('settings.saveFailedTitle'),
        description: mapErrorToUserMessage(err),
      })
    },
  })

  // ── POST /api/settings/clear-secret mutation ─────────────────────────────
  // Explicit "wipe this stored API key" — the backend PUT never deletes a
  // secret on an empty value (BUG-005), so removing a stored key is this
  // deliberate call. Deletes from the keychain, then rebuilds runtime settings.
  const clearSecretMutation = useMutation({
    mutationFn: async (field: string) => {
      const resp = await fetch(`${BASE_URL}/api/settings/clear-secret`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ field }),
      })
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}))
        if (j?.detail) throw new Error(j.detail)
        throw new FetchHttpError(resp.status, resp.statusText)
      }
      return (await resp.json()) as never
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['settings'], data)
      setFmpKey('')
      setFinnhubKey('')
      setAdanosKey('')
      setAlphaVantageKey('')
      setLlmApiKey('')
      const r = data as { model_name?: string; sec_user_agent?: string }
      if (r?.model_name) setModelName(r.model_name)
      if (r?.sec_user_agent !== undefined) setSecUserAgent(r.sec_user_agent ?? '')
      addToast({
        type: 'success',
        title: t('settings.clearKey.doneTitle'),
        description: t('settings.clearKey.doneBody'),
      })
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('settings.clearKey.failTitle'),
        description: mapErrorToUserMessage(err),
      })
    },
  })

  // ── Debounced auto-save ────────────────────────────────────────────────────
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const settingsMutationRef = useRef(settingsMutation)
  useEffect(() => {
    settingsMutationRef.current = settingsMutation
  }, [settingsMutation])

  const scheduleStandardSave = useCallback((payload: Record<string, unknown>) => {
    if (!initializedRef.current) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    const merged = { ...(lastPayloadRef.current ?? {}), ...payload }
    lastPayloadRef.current = merged
    setSaveState('saving')
    debounceRef.current = setTimeout(() => {
      settingsMutationRef.current.mutate(merged as never)
    }, 500)
  }, [])

  const retrySave = useCallback(() => {
    const payload = lastPayloadRef.current
    if (!payload) return
    setSaveState('saving')
    settingsMutationRef.current.mutate(payload as never)
  }, [])

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    }
  }, [])

  // ── Field change handlers ────────────────────────────────────────────────
  // ── Model selection (provider registry) ──────────────────────────────────
  const providers = settingsResp?.providers ?? []
  const customProviders = settingsResp?.custom_providers ?? []
  const effectiveModelName = modelName || settingsResp?.model_name || ''
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
  const handleFmpKeyChange = (v: string) => {
    setFmpKey(v)
    setDataTestState((s) => ({ ...s, fmp: { status: 'idle' } }))
    if (v.trim()) scheduleStandardSave({ fmp_api_key: v.trim() })
  }
  const handleFinnhubKeyChange = (v: string) => {
    setFinnhubKey(v)
    setDataTestState((s) => ({ ...s, finnhub: { status: 'idle' } }))
    if (v.trim()) scheduleStandardSave({ finnhub_api_key: v.trim() })
  }
  const handleAdanosKeyChange = (v: string) => {
    setAdanosKey(v)
    setDataTestState((s) => ({ ...s, adanos: { status: 'idle' } }))
    if (v.trim()) scheduleStandardSave({ adanos_api_key: v.trim() })
  }
  const handleAlphaVantageKeyChange = (v: string) => {
    setAlphaVantageKey(v)
    setDataTestState((s) => ({ ...s, alpha_vantage: { status: 'idle' } }))
    if (v.trim()) scheduleStandardSave({ alpha_vantage_api_key: v.trim() })
  }
  // Live connectivity test for a data-source key. Flushes any unsaved edit first
  // so the backend tests the key the user is looking at, then probes it.
  const handleTestDataProvider = async (provider: string, field: string, key: string) => {
    setDataTestState((s) => ({ ...s, [provider]: { status: 'testing' } }))
    try {
      const trimmed = key.trim()
      if (trimmed) {
        if (debounceRef.current) clearTimeout(debounceRef.current)
        const merged = { ...(lastPayloadRef.current ?? {}), [field]: trimmed }
        lastPayloadRef.current = null
        await settingsMutationRef.current.mutateAsync(merged as never)
      }
      const { data, error } = await api.POST('/api/settings/test-data-provider', {
        body: { provider },
      })
      if (error || !data) throw new Error('test failed')
      setDataTestState((s) => ({
        ...s,
        [provider]: { status: 'done', ok: data.ok, code: data.code, detail: data.detail },
      }))
    } catch {
      setDataTestState((s) => ({
        ...s,
        [provider]: { status: 'done', ok: false, code: 'unknown' },
      }))
    }
  }
  const renderDataTestRow = (provider: string, field: string, key: string): React.ReactElement => {
    const st = dataTestState[provider] ?? { status: 'idle' as const }
    return (
      <div className="settings-test-row">
        <button
          type="button"
          className="settings-btn"
          onClick={() => handleTestDataProvider(provider, field, key)}
          disabled={st.status === 'testing'}
        >
          {st.status === 'testing' ? t('settings.test.testing') : t('settings.test.button')}
        </button>
        {st.status === 'done' && (
          <span className={`settings-test-result${st.ok ? ' is-ok' : ' is-bad'}`}>
            {st.ok ? '✓ ' : '✗ '}
            {t(`settings.dataTest.result.${st.code ?? 'unknown'}`)}
            {!st.ok && st.detail && st.code === 'http' ? ` (${st.detail})` : ''}
          </span>
        )}
      </div>
    )
  }
  const handleSecAgentChange = (v: string) => {
    setSecUserAgent(v)
    scheduleStandardSave({ sec_user_agent: v })
  }
  const handleClearSecret = (field: string) => {
    if (field) setPendingClearSecret(field)
  }

  // ── Derived ──────────────────────────────────────────────────────────────
  const fmpConfigured = settingsResp?.fmp_api_key_set ?? false
  const finnhubConfigured = settingsResp?.finnhub_api_key_set ?? false
  const adanosConfigured = settingsResp?.adanos_api_key_set ?? false
  const alphaVantageConfigured = settingsResp?.alpha_vantage_api_key_set ?? false
  const llmKeyConfigured = currentProviderInfo?.key_set ?? false
  const startupError = settingsResp?.startup_error ?? null
  const secIdentityLocallyValid = isValidSecIdentity(secUserAgent)
  const secIdentityActive = settingsResp?.sec_identity_active ?? false
  const secIdentityMatchesServer =
    secUserAgent.trim() === (settingsResp?.sec_user_agent ?? '').trim()
  const secIdentityPreview = secHeaderIdentityPreview(secUserAgent)
  const secIdentityHint = (() => {
    if (!secUserAgent.trim())
      return { cls: 'is-bad', text: t('settings.sec.hintEmpty', { example: SEC_IDENTITY_EXAMPLE }) }
    if (!secIdentityLocallyValid)
      return {
        cls: 'is-bad',
        text: t('settings.sec.hintInvalid', { example: SEC_IDENTITY_EXAMPLE }),
      }
    if (!secIdentityMatchesServer) return { cls: 'is-warn', text: t('settings.sec.hintPending') }
    if (secIdentityActive) return { cls: 'is-ok', text: t('settings.sec.hintActive') }
    return { cls: 'is-warn', text: t('settings.sec.hintUnconfirmed') }
  })()

  // ── Loading / load-error gates ──────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="settings-shell">
        <div
          className="settings-frame"
          style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 12 }}
        >
          {t('settings.loading')}
        </div>
      </div>
    )
  }

  // BUG-026: a failed load must NOT render the editable key form (auto-save
  // would no-op and the user would type secrets that silently never persist).
  if (isError || !settingsResp) {
    return (
      <div className="settings-shell">
        <div className="settings-frame">
          <div
            role="alert"
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-start',
              gap: 12,
              background: 'var(--negative-bg)',
              border: '1px solid var(--negative)',
              borderRadius: 'var(--r-md)',
              padding: '20px 22px',
              fontFamily: 'var(--font-mono)',
              maxWidth: 520,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--negative)' }}>
              {t('settings.loadError.title')}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-primary)', lineHeight: 1.6 }}>
              {t('settings.loadError.body')}
            </div>
            <button
              type="button"
              className="btn"
              onClick={() => refetch()}
              disabled={isFetching}
              style={{ opacity: isFetching ? 0.55 : 1 }}
            >
              {isFetching ? t('settings.loading') : t('common.retry')}
            </button>
          </div>
        </div>
      </div>
    )
  }

  const setSectionRef = (id: string) => (el: HTMLElement | null) => {
    sectionRefs.current[id] = el
  }

  return (
    <div className="settings-shell">
      <div className="settings-frame">
        {/* Header: title + subtitle + save indicator */}
        <div className="settings-head">
          <div>
            <h1 className="settings-title">{t('settings.title')}</h1>
            <p className="settings-subtitle">{t('settings.subtitle')}</p>
          </div>
          <div
            className={`settings-save${
              saveState === 'saving' ? ' is-saving' : saveState === 'saved' ? ' is-saved' : ''
            }`}
          >
            {saveState === 'saving' && <span>{t('settings.saving')}</span>}
            {saveState === 'saved' && <span>✓ {t('settings.savedOk')}</span>}
            {saveState === 'error' && (
              <button type="button" className="settings-save-retry" onClick={retrySave}>
                {t('settings.saveFailedRetry')}
              </button>
            )}
          </div>
        </div>

        {/* Startup error banner (validate_runtime_config failure at boot) */}
        {startupError && (
          <div
            style={{
              background: 'var(--negative-bg)',
              border: '1px solid var(--negative)',
              borderRadius: 'var(--r-md)',
              padding: '12px 16px',
              marginBottom: 'var(--sp-5)',
              fontSize: 12,
              color: 'var(--negative)',
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
            }}
          >
            <div style={{ fontWeight: 600 }}>{t('settings.startupError.title')}</div>
            <div style={{ color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>
              {startupError}
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>
              {t('settings.startupError.hint')}
            </div>
          </div>
        )}

        <div className="settings-body">
          {/* Left nav rail */}
          <nav className="settings-nav" aria-label={t('settings.title')}>
            {NAV_ITEMS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`settings-nav-item${activeSection === item.id ? ' active' : ''}`}
                onClick={() => scrollToSection(item.id)}
              >
                <Icon d={item.icon} />
                {t(item.labelKey)}
              </button>
            ))}
          </nav>

          {/* Right content */}
          <div className="settings-content">
            {/* ── AI Model ── */}
            <section
              className="settings-section"
              data-section="aiModel"
              ref={setSectionRef('aiModel')}
            >
              <h2 className="settings-section-title">{t('settings.section.aiModel')}</h2>

              {!llmKeyConfigured && (
                <div className="settings-onboard">
                  <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden>
                    <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.3" />
                    <path
                      d="M8 5v3.5"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    />
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
                    <p className="settings-custom-box-title">
                      {t('settings.customProvider.title')}
                    </p>
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
                            <span className="label-text">
                              {t('settings.customProvider.baseUrl')}
                            </span>
                          </label>
                          <input
                            className="settings-input"
                            defaultValue={currentProviderInfo.base_url ?? ''}
                            onBlur={(e) =>
                              handleEditCustomBaseUrl(currentProviderId, e.target.value)
                            }
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
                          <span className="settings-badge is-ok">
                            {t('settings.badge.configured')}
                          </span>
                        ) : (
                          <span className="settings-badge is-required">
                            {t('settings.badge.required')}
                          </span>
                        )}
                        {llmKeyConfigured && (
                          <button
                            type="button"
                            className="settings-clear-btn"
                            onClick={() => handleClearSecret(`provider_key:${currentProviderId}`)}
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
                          <span
                            className={`settings-test-result${testState.ok ? ' is-ok' : ' is-bad'}`}
                          >
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

            {/* ── Data Sources ── */}
            <section
              className="settings-section"
              data-section="dataSources"
              ref={setSectionRef('dataSources')}
            >
              <h2 className="settings-section-title">{t('settings.section.dataSources')}</h2>
              <div className="settings-fields">
                {/* FMP */}
                <div className="settings-field">
                  <label className="settings-field-label">
                    <span className="label-text">{t('settings.fmp.label')}</span>
                    {fmpConfigured ? (
                      <span className="settings-badge is-ok">{t('settings.badge.configured')}</span>
                    ) : (
                      <span className="settings-badge is-required">
                        {t('settings.badge.required')}
                      </span>
                    )}
                    {fmpConfigured && (
                      <button
                        type="button"
                        className="settings-clear-btn"
                        onClick={() => handleClearSecret('fmp_api_key')}
                      >
                        {t('settings.clearKey.button')}
                      </button>
                    )}
                  </label>
                  <SecretInput
                    value={fmpKey}
                    onChange={handleFmpKeyChange}
                    placeholder={fmpConfigured ? '••••••••' : t('settings.fmp.placeholder')}
                  />
                  <p className="settings-hint">{t('settings.fmp.hint')}</p>
                  {renderDataTestRow('fmp', 'fmp_api_key', fmpKey)}
                </div>

                {/* Finnhub */}
                <div className="settings-field">
                  <label className="settings-field-label">
                    <span className="label-text">{t('settings.finnhub.label')}</span>
                    {finnhubConfigured ? (
                      <span className="settings-badge is-ok">{t('settings.badge.configured')}</span>
                    ) : (
                      <span className="settings-badge is-optional">
                        {t('settings.badge.optional')}
                      </span>
                    )}
                    {finnhubConfigured && (
                      <button
                        type="button"
                        className="settings-clear-btn"
                        onClick={() => handleClearSecret('finnhub_api_key')}
                      >
                        {t('settings.clearKey.button')}
                      </button>
                    )}
                  </label>
                  <SecretInput
                    value={finnhubKey}
                    onChange={handleFinnhubKeyChange}
                    placeholder={finnhubConfigured ? '••••••••' : t('settings.finnhub.placeholder')}
                  />
                  <p className="settings-hint">{t('settings.finnhub.hint')}</p>
                  {renderDataTestRow('finnhub', 'finnhub_api_key', finnhubKey)}
                </div>

                {/* Adanos — retail sentiment (Reddit / X / Polymarket) */}
                <div className="settings-field">
                  <label className="settings-field-label">
                    <span className="label-text">{t('settings.adanos.label')}</span>
                    {adanosConfigured ? (
                      <span className="settings-badge is-ok">{t('settings.badge.configured')}</span>
                    ) : (
                      <span className="settings-badge is-optional">
                        {t('settings.badge.optional')}
                      </span>
                    )}
                    {adanosConfigured && (
                      <button
                        type="button"
                        className="settings-clear-btn"
                        onClick={() => handleClearSecret('adanos_api_key')}
                      >
                        {t('settings.clearKey.button')}
                      </button>
                    )}
                  </label>
                  <SecretInput
                    value={adanosKey}
                    onChange={handleAdanosKeyChange}
                    placeholder={adanosConfigured ? '••••••••' : t('settings.adanos.placeholder')}
                  />
                  <p className="settings-hint">{t('settings.adanos.hint')}</p>
                  {renderDataTestRow('adanos', 'adanos_api_key', adanosKey)}
                </div>

                {/* Alpha Vantage — news sentiment enrichment */}
                <div className="settings-field">
                  <label className="settings-field-label">
                    <span className="label-text">{t('settings.alphaVantage.label')}</span>
                    {alphaVantageConfigured ? (
                      <span className="settings-badge is-ok">{t('settings.badge.configured')}</span>
                    ) : (
                      <span className="settings-badge is-optional">
                        {t('settings.badge.optional')}
                      </span>
                    )}
                    {alphaVantageConfigured && (
                      <button
                        type="button"
                        className="settings-clear-btn"
                        onClick={() => handleClearSecret('alpha_vantage_api_key')}
                      >
                        {t('settings.clearKey.button')}
                      </button>
                    )}
                  </label>
                  <SecretInput
                    value={alphaVantageKey}
                    onChange={handleAlphaVantageKeyChange}
                    placeholder={
                      alphaVantageConfigured ? '••••••••' : t('settings.alphaVantage.placeholder')
                    }
                  />
                  <p className="settings-hint">{t('settings.alphaVantage.hint')}</p>
                  {renderDataTestRow('alpha_vantage', 'alpha_vantage_api_key', alphaVantageKey)}
                </div>

                {/* SEC EDGAR identity */}
                <div className="settings-field">
                  <label className="settings-field-label">
                    <span className="label-text">{t('settings.sec.label')}</span>
                    {secIdentityActive ? (
                      <span className="settings-badge is-ok">{t('settings.badge.active')}</span>
                    ) : secIdentityLocallyValid ? (
                      <span className="settings-badge is-pending">
                        {t('settings.badge.pending')}
                      </span>
                    ) : (
                      <span className="settings-badge is-required">
                        {t('settings.badge.required')}
                      </span>
                    )}
                  </label>
                  <input
                    className={`settings-input${secIdentityLocallyValid ? '' : ' is-invalid'}`}
                    type="text"
                    value={secUserAgent}
                    onChange={(e) => handleSecAgentChange(e.target.value)}
                    placeholder={t('settings.sec.placeholder')}
                    autoComplete="off"
                    spellCheck={false}
                    aria-invalid={!secIdentityLocallyValid}
                  />
                  <p className={`settings-hint ${secIdentityHint.cls}`}>{secIdentityHint.text}</p>
                  {secIdentityPreview && (
                    <p className="settings-hint">
                      {t('settings.sec.preview')}
                      {secIdentityPreview}
                    </p>
                  )}
                </div>
              </div>
            </section>

            {/* ── SEC 13F holdings ── */}
            <SecHoldingsSection sectionRef={setSectionRef('secHoldings')} />

            {/* ── Appearance & language ── */}
            <DisplaySection sectionRef={setSectionRef('display')} />
          </div>
        </div>
      </div>

      {pendingClearSecret && (
        <ClearKeyConfirmModal
          onCancel={() => setPendingClearSecret(null)}
          onConfirm={() => {
            const f = pendingClearSecret
            setPendingClearSecret(null)
            clearSecretMutation.mutate(f)
          }}
        />
      )}
    </div>
  )
}

// ─── Clear-key confirm modal ─────────────────────────────────────────────────

function ClearKeyConfirmModal({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void
  onConfirm: () => void
}): React.ReactElement {
  const { t } = useI18n()
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onCancel}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'var(--scrim)',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
        display: 'grid',
        placeItems: 'center',
        zIndex: 200,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          minWidth: 360,
          maxWidth: 440,
          padding: '22px 24px',
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-lg)',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
          {t('settings.clearKey.confirmTitle')}
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          {t('settings.clearKey.confirmBody')}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
          <button type="button" className="btn" onClick={onCancel}>
            {t('settings.clearKey.cancel')}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="btn"
            style={{
              background: 'var(--danger)',
              borderColor: 'var(--danger)',
              color: 'var(--text-on-primary)',
              fontWeight: 600,
            }}
          >
            {t('settings.clearKey.confirm')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── SEC 13F institutional-holdings section ─────────────────────────────────
// The 13F reverse index is OFF by default (building it downloads a whole
// quarter of market-wide filings — ~1-2h). This section shows cache state,
// flips auto-sync, and triggers a manual build behind a confirm (BUG-009).

interface RefreshRuntime {
  status: 'idle' | 'running' | 'done' | 'error'
  period_end: string | null
  started_at: string | null
  finished_at: string | null
  error: string | null
}

interface SecHoldingsStatusShape {
  populated: boolean
  row_count: number
  latest_period_end: string | null
  distinct_tickers: number
  identity_configured: boolean
  auto_refresh: boolean
  refresh: RefreshRuntime
}

function SecHoldingsSection({
  sectionRef,
}: {
  sectionRef: (el: HTMLElement | null) => void
}): React.ReactElement {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const addToast = useToastStore((s) => s.addToast)

  const { data: status } = useQuery<SecHoldingsStatusShape>({
    queryKey: ['sec-holdings-status'],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/sec-holdings/status`)
      if (!resp.ok) throw new FetchHttpError(resp.status, resp.statusText)
      return (await resp.json()) as SecHoldingsStatusShape
    },
    refetchInterval: (query) => (query.state.data?.refresh.status === 'running' ? 2000 : false),
  })

  const refreshMutation = useMutation({
    mutationFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/sec-holdings/refresh`, { method: 'POST' })
      if (!resp.ok) throw new FetchHttpError(resp.status, resp.statusText)
      return (await resp.json()) as SecHoldingsStatusShape
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['sec-holdings-status'], data)
      if (data.refresh.status === 'error') {
        addToast({
          type: 'error',
          title: t('settings.secHoldings.syncFailed'),
          description:
            data.refresh.error === 'identity_missing'
              ? t('settings.secHoldings.identityRequired')
              : (data.refresh.error ?? t('settings.secHoldings.syncFailed')),
        })
      }
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('settings.secHoldings.syncFailed'),
        description: mapErrorToUserMessage(err),
      })
    },
  })

  const autoRefreshMutation = useMutation({
    mutationFn: async (v: boolean) => {
      const { data, error } = await api.PUT('/api/settings', {
        body: { sec_holdings_auto_refresh: v } as never,
      })
      if (error) throw new Error('settings update failed')
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sec-holdings-status'] })
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })

  const [confirmOpen, setConfirmOpen] = useState(false)

  const running = status?.refresh.status === 'running' || refreshMutation.isPending
  const identityOk = status?.identity_configured ?? false
  const startedAt = status?.refresh.started_at ?? null
  const startedAtLabel = (() => {
    if (!running || !startedAt) return null
    const d = new Date(startedAt)
    if (Number.isNaN(d.getTime())) return null
    return t('settings.secHoldings.startedAt', { time: d.toLocaleString() })
  })()

  const statusLine = (() => {
    if (!status) return ''
    if (status.populated && status.latest_period_end) {
      return t('settings.secHoldings.statusPopulated', {
        rows: status.row_count.toLocaleString(),
        tickers: status.distinct_tickers.toLocaleString(),
        period: status.latest_period_end,
      })
    }
    return t('settings.secHoldings.statusEmpty')
  })()

  return (
    <section className="settings-section" data-section="secHoldings" ref={sectionRef}>
      <h2 className="settings-section-title">{t('settings.section.secHoldings')}</h2>
      <p className="settings-section-desc">{t('settings.secHoldings.intro')}</p>

      <div className="settings-field">
        <p className="settings-hint" style={{ fontFamily: 'var(--font-mono)' }}>
          {statusLine}
        </p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn"
            disabled={!identityOk || running}
            onClick={() => setConfirmOpen(true)}
          >
            <svg width="13" height="13" viewBox="0 0 12 12" fill="none" aria-hidden>
              <path
                d="M10.5 6a4.5 4.5 0 1 1-1.32-3.18M10.5 1.5V4H8"
                stroke="currentColor"
                strokeWidth="1.3"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            {running ? t('settings.secHoldings.syncing') : t('settings.secHoldings.syncNow')}
          </button>
          {!identityOk && (
            <span className="settings-hint is-warn">
              {t('settings.secHoldings.identityRequired')}
            </span>
          )}
        </div>
        {running && (
          <>
            {startedAtLabel && (
              <p className="settings-hint" style={{ marginTop: 6 }}>
                {startedAtLabel}
              </p>
            )}
            <p className="settings-hint" style={{ marginTop: 6 }}>
              {t('settings.secHoldings.runningHint')}
            </p>
          </>
        )}
        {refreshMutation.isError && !running && (
          <p className="settings-hint is-bad" style={{ marginTop: 6 }}>
            {t('settings.secHoldings.syncError')}{' '}
            <button
              type="button"
              onClick={() => refreshMutation.mutate()}
              style={{
                background: 'transparent',
                border: 'none',
                padding: 0,
                color: 'var(--danger)',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.75rem',
                cursor: 'pointer',
                textDecoration: 'underline',
              }}
            >
              {t('common.retry')}
            </button>
          </p>
        )}
      </div>

      <ToggleRow
        label={t('settings.secHoldings.autoRefresh')}
        desc={t('settings.secHoldings.autoRefreshDesc')}
        enabled={status?.auto_refresh ?? false}
        onToggle={() => autoRefreshMutation.mutate(!(status?.auto_refresh ?? false))}
      />

      {confirmOpen && (
        <SecHoldingsConfirmModal
          onCancel={() => setConfirmOpen(false)}
          onConfirm={() => {
            setConfirmOpen(false)
            refreshMutation.mutate()
          }}
        />
      )}
    </section>
  )
}

function SecHoldingsConfirmModal({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void
  onConfirm: () => void
}): React.ReactElement {
  const { t } = useI18n()
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onCancel}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'var(--scrim)',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
        display: 'grid',
        placeItems: 'center',
        zIndex: 200,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          minWidth: 360,
          maxWidth: 460,
          padding: '22px 24px',
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-lg)',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--warning)' }}>
          {t('settings.secHoldings.confirmTitle')}
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--text-primary)', lineHeight: 1.6 }}>
          {t('settings.secHoldings.confirmBody')}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
          <button type="button" className="btn" onClick={onCancel}>
            {t('settings.clearKey.cancel')}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="btn"
            style={{
              background: 'var(--warning)',
              borderColor: 'var(--warning)',
              color: 'var(--text-on-warning)',
              fontWeight: 600,
            }}
          >
            {t('settings.secHoldings.confirmProceed')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Appearance & language section ──────────────────────────────────────────

function DisplaySection({
  sectionRef,
}: {
  sectionRef: (el: HTMLElement | null) => void
}): React.ReactElement {
  const { t } = useI18n()
  const cursorOn = useUiStore((s) => s.cursorTrailEnabled)
  const setCursor = useUiStore((s) => s.setCursorTrailEnabled)

  return (
    <section className="settings-section" data-section="display" ref={sectionRef}>
      <h2 className="settings-section-title">{t('settings.appearance.title')}</h2>
      <p className="settings-section-desc">{t('settings.appearance.intro')}</p>

      <ToggleRow
        label={t('settings.appearance.cursor')}
        desc={t('settings.appearance.cursorDesc')}
        enabled={cursorOn}
        onToggle={() => setCursor(!cursorOn)}
      />
    </section>
  )
}

function ToggleRow({
  label,
  desc,
  enabled,
  onToggle,
}: {
  label: string
  desc: string
  enabled: boolean
  onToggle: () => void
}): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '14px 0',
        borderTop: '1px solid var(--border-soft)',
      }}
    >
      <div style={{ paddingRight: 24 }}>
        <div style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 500 }}>{label}</div>
        <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 4, lineHeight: 1.5 }}>
          {desc}
        </div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label={label}
        onClick={onToggle}
        style={{
          position: 'relative',
          width: 44,
          height: 24,
          flexShrink: 0,
          borderRadius: 12,
          border: '1px solid var(--border-soft)',
          background: enabled ? 'var(--primary-soft)' : 'var(--bg-card)',
          cursor: 'pointer',
          transition: 'all 0.2s',
          padding: 0,
        }}
      >
        <span
          style={{
            position: 'absolute',
            top: 2,
            left: enabled ? 22 : 2,
            width: 18,
            height: 18,
            borderRadius: '50%',
            background: enabled ? 'var(--primary)' : 'var(--text-muted)',
            boxShadow: enabled ? 'var(--glow-blue)' : 'none',
            transition: 'all 0.2s',
          }}
        />
      </button>
    </div>
  )
}
