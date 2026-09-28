// SettingsView — container for the tabbed settings surface (left nav rail +
// one panel rendered at a time: AI Model / Data Sources / Updates). All edit
// state lives here (not in the panels) so it survives panel switches and so
// the clear-secret flow can reset every key field in one place; the panels in
// ./settings/ are pure render + handler composition over props.

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, BASE_URL } from '../api/client'
import { fetchWithTimeout } from '../api/fetch'
import { useToastStore } from '../stores/toastStore'
import { mapErrorToUserMessage, FetchHttpError } from '../utils/errorMessage'
import { useI18n, tSync } from '../i18n'
import { Icon, ICON_MODEL, ICON_DATA, ICON_UPDATE } from './settings/controls'
import { useSettingsSave } from './settings/useSettingsSave'
import { AiModelPanel, type DraftProvider, type LlmTestState } from './settings/AiModelPanel'
import {
  DataSourcesPanel,
  type DataTestState,
  type ProviderHealthEntryShape,
} from './settings/DataSourcesPanel'
import { SecHoldingsSection } from './settings/SecHoldingsSection'
import { UpdatesSection } from './settings/UpdatesSection'
import { ClearKeyConfirmModal } from './settings/ClearKeyConfirmModal'
import { AI_CHAT_ENABLED } from '../config/features'

// Re-exported so the SEC-identity validators keep their historical import path
// (`views/SettingsView`) for tests and any future consumer.
export { isValidSecIdentity, secHeaderIdentityPreview } from './settings/secIdentity'

// ─── Panel nav (left rail) ────────────────────────────────────────────────────
// True tabbed panels, not a scroll-spy over one long page: clicking a nav item
// renders ONLY that panel. SEC 13F holdings lives inside Data Sources.

const NAV_ITEMS = [
  { id: 'aiModel', icon: ICON_MODEL, labelKey: 'settings.section.aiModel' },
  { id: 'dataSources', icon: ICON_DATA, labelKey: 'settings.section.dataSources' },
  { id: 'updates', icon: ICON_UPDATE, labelKey: 'settings.nav.updates' },
] as const

type SettingsPanel = (typeof NAV_ITEMS)[number]['id']

// ─── Main component ────────────────────────────────────────────────────────

export default function SettingsView() {
  const { t, locale } = useI18n()
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

  // ── Live provider health (门五②) ──────────────────────────────────────────
  // Real ProviderHealth breaker signals for the unified data-source rows,
  // never a mocked green panel. Failure degrades to dim dots, not a crash.
  const { data: healthResp, isError: healthError } = useQuery<{
    providers: ProviderHealthEntryShape[]
  }>({
    queryKey: ['provider-health'],
    queryFn: async () => {
      const resp = await fetchWithTimeout(`${BASE_URL}/api/settings/provider-health`)
      if (!resp.ok) throw new FetchHttpError(resp.status, resp.statusText)
      return (await resp.json()) as { providers: ProviderHealthEntryShape[] }
    },
    refetchInterval: 30_000,
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
  const [draftProvider, setDraftProvider] = useState<DraftProvider>({
    name: '',
    baseUrl: '',
    modelId: '',
    apiKey: '',
  })
  const [testState, setTestState] = useState<LlmTestState>({ status: 'idle' })
  const [dataTestState, setDataTestState] = useState<DataTestState>({})

  // Pending SECRET field awaiting confirmation before its stored keychain key is
  // deleted via POST /api/settings/clear-secret (BUG-005).
  const [pendingClearSecret, setPendingClearSecret] = useState<string | null>(null)

  // ── Debounced auto-save machinery (PUT /api/settings) ────────────────────
  const { saveState, scheduleStandardSave, retrySave, flushPending, initializedRef } =
    useSettingsSave()

  // ── Active panel (tabbed nav — only the selected panel renders) ──────────
  const [activePanel, setActivePanel] = useState<SettingsPanel>('aiModel')

  // Populate editable fields from the server on first load.
  useEffect(() => {
    if (!settingsResp || initializedRef.current) return
    initializedRef.current = true
    if (settingsResp.model_name) setModelName(settingsResp.model_name)
    if (settingsResp.sec_user_agent) setSecUserAgent(settingsResp.sec_user_agent)
  }, [settingsResp, initializedRef])

  // ── POST /api/settings/clear-secret mutation ─────────────────────────────
  // Explicit "wipe this stored API key" — the backend PUT never deletes a
  // secret on an empty value (BUG-005), so removing a stored key is this
  // deliberate call. Deletes from the keychain, then rebuilds runtime settings.
  const clearSecretMutation = useMutation({
    mutationFn: async (field: string) => {
      const resp = await fetchWithTimeout(`${BASE_URL}/api/settings/clear-secret`, {
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
    onSuccess: (data, field) => {
      queryClient.setQueryData(['settings'], data)
      // Clearing the Adanos key drops the sentiment provider server-side — drop
      // the cached snapshot so the card flips back to the configure CTA at once.
      if (field === 'adanos_api_key') {
        void queryClient.invalidateQueries({ queryKey: ['ticker-sentiment'] })
      }
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

  const handleClearSecret = (field: string) => {
    if (field) setPendingClearSecret(field)
  }

  // ── Derived ──────────────────────────────────────────────────────────────
  const fmpConfigured = settingsResp?.fmp_api_key_set ?? false
  const finnhubConfigured = settingsResp?.finnhub_api_key_set ?? false
  const adanosConfigured = settingsResp?.adanos_api_key_set ?? false
  const alphaVantageConfigured = settingsResp?.alpha_vantage_api_key_set ?? false
  const startupError = settingsResp?.startup_error ?? null
  // True when a usable LLM is selected. False on a fresh install (no model yet)
  // — that's onboarding, NOT an error, so it gets a friendly notice rather than
  // the red startupError banner. Default true while settings load (no flash).
  const modelConfigured = settingsResp?.model_configured ?? true
  // The AI Model nav item flags an attention dot whenever the LLM needs the
  // user: a hard config error (startupError) OR the first-run "no model" state.
  // So the cue survives even when the user is on another panel.
  const aiModelNeedsAttention = startupError != null || !modelConfigured

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

        {/* Honest secret-storage disclosure. The backend stores secrets in the
            OS keychain where it can; on an unsigned macOS build / Linux without a
            keyring it falls back to a local file, and `secret_storage_mode` then
            reports 'plaintext'. Surface that NEUTRALLY (it's a normal state, not
            an error — muted, not red) so a user knows where their keys live. Page
            level because it covers every secret across all panels. */}
        {settingsResp.secret_storage_mode === 'plaintext' && (
          <div
            data-testid="secret-storage-plaintext"
            style={{
              background: 'var(--bg-card-faint)',
              border: '1px solid var(--border-soft)',
              borderRadius: 'var(--r-md)',
              padding: '10px 14px',
              marginBottom: 'var(--sp-5)',
              fontFamily: 'var(--font-mono)',
              fontSize: 11.5,
              lineHeight: 1.5,
              color: 'var(--text-secondary)',
            }}
          >
            {t('settings.secretStorage.localFile')}
          </div>
        )}

        {/* Startup error banner (a chosen-but-broken LLM config). Scoped to the
            AI Model panel — a boot config error is an LLM concern, so dangling
            it over Data Sources / Updates only confused (it read like every
            panel was broken). The nav rail keeps a dot so it stays discoverable
            from other panels. */}
        {startupError && activePanel === 'aiModel' && (
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

        {/* First-run notice (no model chosen yet) — friendly, NOT an error.
            Distinct from startupError: empty model_name is the expected fresh
            install state. Tells the user what works without any key vs what
            needs a model, so picking one below feels optional-but-unlocking. */}
        {!startupError && !modelConfigured && activePanel === 'aiModel' && (
          <div
            style={{
              background: 'color-mix(in srgb, var(--accent) 8%, transparent)',
              border: '1px solid var(--accent)',
              borderRadius: 'var(--r-md)',
              padding: '12px 16px',
              marginBottom: 'var(--sp-5)',
              fontSize: 12,
              color: 'var(--text-primary)',
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
            }}
          >
            <div style={{ fontWeight: 600, color: 'var(--accent)' }}>
              {locale === 'zh'
                ? '选一个 AI 模型即可解锁研报'
                : 'Pick an AI model to unlock reports'}
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: 11, lineHeight: 1.5 }}>
              {locale === 'zh'
                ? `价格、财务、估值(DCF / LBO / 可比公司)等所有确定性数字无需配置即可使用;只有 AI 研报${AI_CHAT_ENABLED ? '、AI 对话' : ''}需要一个模型。在下方选择 provider、填入 key 即可开始。`
                : `Prices, financials, and valuations (DCF / LBO / comps) — every deterministic number — work with no key. Only AI reports${AI_CHAT_ENABLED ? ' and AI chat' : ''} need a model. Pick a provider below and add its key to begin.`}
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
                className={`settings-nav-item${activePanel === item.id ? ' active' : ''}`}
                aria-current={activePanel === item.id ? 'page' : undefined}
                onClick={() => setActivePanel(item.id)}
              >
                <Icon d={item.icon} />
                {t(item.labelKey)}
                {/* Attention dot: AI Model needs the user (no model chosen, or a
                    broken key). Stays visible from any panel so the cue isn't
                    lost when the banner is scoped away to the AI Model panel. */}
                {item.id === 'aiModel' && aiModelNeedsAttention && (
                  <span
                    aria-hidden
                    style={{
                      marginLeft: 'auto',
                      width: 7,
                      height: 7,
                      borderRadius: '50%',
                      background: startupError ? 'var(--negative)' : 'var(--accent)',
                      boxShadow: startupError ? '0 0 6px var(--negative)' : '0 0 6px var(--accent)',
                    }}
                  />
                )}
              </button>
            ))}
          </nav>

          {/* Right content — only the selected panel renders */}
          <div className="settings-content">
            {activePanel === 'aiModel' && (
              <AiModelPanel
                providers={settingsResp.providers ?? []}
                customProviders={settingsResp.custom_providers ?? []}
                serverModelName={settingsResp.model_name}
                modelName={modelName}
                setModelName={setModelName}
                llmApiKey={llmApiKey}
                setLlmApiKey={setLlmApiKey}
                addingCustom={addingCustom}
                setAddingCustom={setAddingCustom}
                draftProvider={draftProvider}
                setDraftProvider={setDraftProvider}
                testState={testState}
                setTestState={setTestState}
                scheduleStandardSave={scheduleStandardSave}
                flushPending={flushPending}
                onClearSecret={handleClearSecret}
              />
            )}

            {activePanel === 'dataSources' && (
              <>
                <DataSourcesPanel
                  healthResp={healthResp}
                  healthError={healthError}
                  fmpConfigured={fmpConfigured}
                  finnhubConfigured={finnhubConfigured}
                  adanosConfigured={adanosConfigured}
                  alphaVantageConfigured={alphaVantageConfigured}
                  fmpKey={fmpKey}
                  setFmpKey={setFmpKey}
                  finnhubKey={finnhubKey}
                  setFinnhubKey={setFinnhubKey}
                  adanosKey={adanosKey}
                  setAdanosKey={setAdanosKey}
                  alphaVantageKey={alphaVantageKey}
                  setAlphaVantageKey={setAlphaVantageKey}
                  dataTestState={dataTestState}
                  setDataTestState={setDataTestState}
                  scheduleStandardSave={scheduleStandardSave}
                  flushPending={flushPending}
                  onClearSecret={handleClearSecret}
                  secUserAgent={secUserAgent}
                  setSecUserAgent={setSecUserAgent}
                  serverSecUserAgent={settingsResp.sec_user_agent ?? ''}
                  secIdentityActive={settingsResp.sec_identity_active ?? false}
                />

                {/* SEC 13F holdings — part of the Data Sources panel */}
                <SecHoldingsSection />
              </>
            )}

            {activePanel === 'updates' && <UpdatesSection />}
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
