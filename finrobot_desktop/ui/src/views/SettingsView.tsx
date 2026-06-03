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

// ─── Model Options ─────────────────────────────────────────────────────────

const MODEL_OPTIONS = [
  { value: 'deepseek:deepseek-chat', label: 'DeepSeek V3' },
  { value: 'deepseek:deepseek-reasoner', label: 'DeepSeek R1' },
  { value: 'anthropic:claude-sonnet-4-6', label: 'Claude Sonnet 4' },
  { value: 'openai:gpt-4o', label: 'GPT-4o' },
]

// ─── Styles ────────────────────────────────────────────────────────────────

const sectionStyle: React.CSSProperties = {
  background: 'var(--bg-2)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--r-sm)',
  padding: '20px',
  marginBottom: '16px',
}

const sectionTitleStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: '12px',
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  color: 'var(--text-primary)',
  marginBottom: '16px',
}

const fieldGroupStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '12px',
}

const fieldStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '4px',
}

const labelStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '6px',
  fontFamily: 'var(--font-mono)',
  fontSize: '11px',
  color: 'var(--text-secondary)',
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  background: 'var(--bg-3)',
  border: '1px solid var(--border)',
  borderRadius: '4px',
  padding: '8px 10px',
  fontFamily: 'var(--font-mono)',
  fontSize: '11px',
  color: 'var(--text-primary)',
  outline: 'none',
  transition: 'border-color 0.15s',
}

const hintStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: '10px',
  color: 'var(--text-muted)',
  marginTop: '2px',
}

const hintInvalidStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: '10px',
  color: 'var(--danger)',
  marginTop: '2px',
  lineHeight: 1.5,
}

const hintOkStyle: React.CSSProperties = {
  ...hintStyle,
  color: 'var(--success)',
  lineHeight: 1.5,
}

const hintWarningStyle: React.CSSProperties = {
  ...hintStyle,
  color: 'var(--warning)',
  lineHeight: 1.5,
}

const secHeaderPreviewStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: '10px',
  color: 'var(--text-muted)',
  marginTop: '0',
  lineHeight: 1.5,
}

const SEC_IDENTITY_EXAMPLE = 'Acme Research analyst@example.com'
const SEC_EMAIL_RE = /[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}/

function extractSecEmail(s: string): RegExpMatchArray | null {
  return s.match(SEC_EMAIL_RE)
}

/** Mirrors finrobot.engine.data.providers.edgar_provider._is_valid_identity.
 * SEC requires `Name email@domain` — we also reject the backend's placeholder
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

const requiredBadgeStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: '9px',
  background: 'var(--negative-bg)',
  color: 'var(--negative)',
  padding: '1px 5px',
  borderRadius: '2px',
}

const optionalBadgeStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: '9px',
  background: 'var(--bg-3)',
  color: 'var(--text-muted)',
  padding: '1px 5px',
  borderRadius: '2px',
}

const configuredBadgeStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: '9px',
  background: 'var(--positive-bg)',
  color: 'var(--positive)',
  padding: '1px 5px',
  borderRadius: '2px',
}

const pendingBadgeStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: '9px',
  background: 'var(--warning-soft)',
  color: 'var(--warning)',
  padding: '1px 5px',
  borderRadius: '2px',
}

// Source badge (e.g. "来自 .env", "来自 keychain") — neutral colour so it
// doesn't compete with the configured/required badges next to it.
const sourceBadgeStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: '9px',
  background: 'var(--bg-3)',
  color: 'var(--text-muted)',
  padding: '1px 5px',
  borderRadius: '2px',
  border: '1px solid var(--border)',
}

const SOURCE_LABEL_KEYS: Record<string, string> = {
  keychain: 'settings.source.keychain',
  settings_json: 'settings.source.settingsJson',
  env: 'settings.source.env',
  default: 'settings.source.default',
}

function SourceBadge({ source }: { source?: string | null }) {
  const { t } = useI18n()
  if (!source) return null
  const key = SOURCE_LABEL_KEYS[source]
  const label = key ? t(key) : source
  return <span style={sourceBadgeStyle}>{label}</span>
}

const ghostBtnStyle: React.CSSProperties = {
  background: 'transparent',
  border: '1px solid var(--border)',
  borderRadius: '3px',
  padding: '3px 8px',
  fontFamily: 'var(--font-mono)',
  fontSize: '10px',
  color: 'var(--text-secondary)',
  cursor: 'pointer',
  transition: 'border-color 0.15s, color 0.15s',
  whiteSpace: 'nowrap',
  flexShrink: 0,
}

function InputWithFocus({ style: s, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  const [focused, setFocused] = useState(false)
  return (
    <input
      {...props}
      style={{
        ...inputStyle,
        ...s,
        borderColor: focused ? 'var(--accent)' : 'var(--border)',
      }}
      onFocus={(e) => {
        setFocused(true)
        props.onFocus?.(e)
      }}
      onBlur={(e) => {
        setFocused(false)
        props.onBlur?.(e)
      }}
    />
  )
}

function SelectWithFocus({ style: s, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  const [focused, setFocused] = useState(false)
  return (
    <select
      {...props}
      style={{
        ...inputStyle,
        ...s,
        borderColor: focused ? 'var(--accent)' : 'var(--border)',
        cursor: 'pointer',
      }}
      onFocus={(e) => {
        setFocused(true)
        props.onFocus?.(e)
      }}
      onBlur={(e) => {
        setFocused(false)
        props.onBlur?.(e)
      }}
    />
  )
}

// ─── Auto-save indicator ───────────────────────────────────────────────────

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

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

  // ── Section 1: Data Sources ──────────────────────────────────────────────
  const [fmpKey, setFmpKey] = useState('')
  const [finnhubKey, setFinnhubKey] = useState('')
  const [secUserAgent, setSecUserAgent] = useState('')

  // ── Section 2: LLM Provider ─────────────────────────────────────────────
  const [modelName, setModelName] = useState('')
  const [llmApiKey, setLlmApiKey] = useState('')

  // Pending fields awaiting user confirmation before resetting their
  // settings.json override back to the .env default. Set by handleResetField,
  // cleared by the inline confirm modal.
  const [pendingReset, setPendingReset] = useState<string[] | null>(null)
  // Pending SECRET field awaiting confirmation before its stored keychain key
  // is deleted via POST /api/settings/clear-secret (BUG-005). Separate from
  // pendingReset because clearing a secret is a distinct, explicit action.
  const [pendingClearSecret, setPendingClearSecret] = useState<string | null>(null)

  // ── Save indicator ───────────────────────────────────────────────────────
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const initializedRef = useRef(false)
  // Last payload sent to the PUT mutation. On save failure we keep this around
  // so the "Save failed · retry" indicator can re-fire the exact same write
  // instead of silently dropping the user's edit (BUG-026).
  const lastPayloadRef = useRef<Record<string, string | number | boolean | null> | null>(null)

  // Populate from server on first load
  useEffect(() => {
    if (!settingsResp || initializedRef.current) return
    initializedRef.current = true
    if (settingsResp.model_name) setModelName(settingsResp.model_name)
    if (settingsResp.sec_user_agent) setSecUserAgent(settingsResp.sec_user_agent)
  }, [settingsResp])

  // ── PUT /api/settings mutation ───────────────────────────────────────────
  const settingsMutation = useMutation({
    mutationFn: async (body: Record<string, string | null>) => {
      const { data, error } = await api.PUT('/api/settings', {
        body: body as never,
      })
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
      // Keep the dirty payload in lastPayloadRef and stay in the 'error' state
      // (no auto-revert to idle) so the indicator stays a tappable "retry"
      // affordance until the write actually succeeds — never silently drop it.
      setSaveState('error')
      addToast({
        type: 'error',
        title: t('settings.saveFailedTitle'),
        description: mapErrorToUserMessage(err),
      })
    },
  })

  // ── POST /api/settings/reset mutation ────────────────────────────────────
  // "恢复 .env 默认" — clears the listed fields out of settings.json (and
  // keychain for secrets) so .env / env-vars regain priority. Backend does
  // NOT copy .env values into settings.json — it just removes the override.
  const resetMutation = useMutation({
    mutationFn: async (fields: string[]) => {
      const resp = await fetch(`${BASE_URL}/api/settings/reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fields }),
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
      // Wipe the local-edit state so the inputs re-bind to the server
      // values. Without this, our setStates from before the reset would
      // keep displaying the user-typed value even after the field is
      // technically reverted to .env.
      setFmpKey('')
      setFinnhubKey('')
      setLlmApiKey('')
      // Re-initialize from response so model_name / sec_user_agent reflect
      // whatever .env contains.
      const r = data as { model_name?: string; sec_user_agent?: string }
      if (r?.model_name) setModelName(r.model_name)
      if (r?.sec_user_agent !== undefined) setSecUserAgent(r.sec_user_agent ?? '')
      addToast({
        type: 'success',
        title: t('settings.reset.doneTitle'),
        description: t('settings.reset.doneBody'),
      })
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('settings.reset.failTitle'),
        description: mapErrorToUserMessage(err),
      })
    },
  })

  // ── POST /api/settings/clear-secret mutation ─────────────────────────────
  // Explicit "wipe this stored API key" for keychain-sourced secrets. The
  // backend PUT no longer deletes a secret on an empty value (BUG-005), so
  // removing a stored key is a deliberate call to this dedicated endpoint —
  // it deletes from the keychain then rebuilds runtime settings from .env.
  // Used in place of /reset for SECRET fields (source === 'keychain'); /reset
  // stays for non-secret settings.json overrides (model_name, sec_user_agent).
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
      // Drop local edits so inputs re-bind to server values (key now gone).
      setFmpKey('')
      setFinnhubKey('')
      setLlmApiKey('')
      const r = data as { model_name?: string; sec_user_agent?: string }
      if (r?.model_name) setModelName(r.model_name)
      if (r?.sec_user_agent !== undefined) setSecUserAgent(r.sec_user_agent ?? '')
      addToast({
        type: 'success',
        title: t('settings.reset.doneTitle'),
        description: t('settings.reset.doneBody'),
      })
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('settings.reset.failTitle'),
        description: mapErrorToUserMessage(err),
      })
    },
  })

  // ── Debounced auto-save for standard settings ────────────────────────────
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // useMutation returns a new `mutate` reference on each render. Stash the
  // latest mutation in a ref so the debounced callback can stay stable while
  // still calling the freshest mutate (avoids a closure over a stale instance).
  const settingsMutationRef = useRef(settingsMutation)
  useEffect(() => {
    settingsMutationRef.current = settingsMutation
  }, [settingsMutation])

  const scheduleStandardSave = useCallback(
    (payload: Record<string, string | number | boolean | null>) => {
      if (!initializedRef.current) return
      if (debounceRef.current) clearTimeout(debounceRef.current)
      // Merge into any payload still pending from a prior failed save so a
      // retry replays every dirty field, not just the most recent one.
      const merged = { ...(lastPayloadRef.current ?? {}), ...payload }
      lastPayloadRef.current = merged
      setSaveState('saving')
      debounceRef.current = setTimeout(() => {
        settingsMutationRef.current.mutate(merged as never)
      }, 500)
    },
    [],
  )

  // Re-fire the last (failed) save when the user taps the retry indicator.
  const retrySave = useCallback(() => {
    const payload = lastPayloadRef.current
    if (!payload) return
    setSaveState('saving')
    settingsMutationRef.current.mutate(payload as never)
  }, [])

  // Cleanup timers
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    }
  }, [])

  // ── Field change handlers ────────────────────────────────────────────────
  const handleModelChange = (v: string) => {
    setModelName(v)
    scheduleStandardSave({ model_name: v })
  }

  const handleLlmKeyChange = (v: string) => {
    setLlmApiKey(v)
    if (!v.trim()) return
    const provider = (modelName || settingsResp?.model_name || '').split(':')[0]
    const keyField = `${provider}_api_key` as
      | 'anthropic_api_key'
      | 'deepseek_api_key'
      | 'openai_api_key'
    scheduleStandardSave({ [keyField]: v.trim() })
  }

  const handleFmpKeyChange = (v: string) => {
    setFmpKey(v)
    if (v.trim()) scheduleStandardSave({ fmp_api_key: v.trim() })
  }

  const handleFinnhubKeyChange = (v: string) => {
    setFinnhubKey(v)
    if (v.trim()) scheduleStandardSave({ finnhub_api_key: v.trim() })
  }

  const handleSecAgentChange = (v: string) => {
    setSecUserAgent(v)
    scheduleStandardSave({ sec_user_agent: v })
  }

  // ── Derived ──────────────────────────────────────────────────────────────
  const currentProvider = (modelName || settingsResp?.model_name || '').split(':')[0]
  const fmpConfigured = settingsResp?.fmp_api_key_set ?? false
  const finnhubConfigured = settingsResp?.finnhub_api_key_set ?? false
  const fieldSources = (settingsResp?.field_sources ?? {}) as Record<string, string>
  const sourceOf = (field: string): string | null => fieldSources[field] ?? null
  const startupError = settingsResp?.startup_error ?? null
  const secIdentityLocallyValid = isValidSecIdentity(secUserAgent)
  const secIdentityActive = settingsResp?.sec_identity_active ?? false
  const secIdentityMatchesServer =
    secUserAgent.trim() === (settingsResp?.sec_user_agent ?? '').trim()
  const secIdentityPreview = secHeaderIdentityPreview(secUserAgent)
  const secIdentityHint = (() => {
    if (!secUserAgent.trim()) {
      return {
        style: hintInvalidStyle,
        text: t('settings.sec.hintEmpty', { example: SEC_IDENTITY_EXAMPLE }),
      }
    }
    if (!secIdentityLocallyValid) {
      return {
        style: hintInvalidStyle,
        text: t('settings.sec.hintInvalid', { example: SEC_IDENTITY_EXAMPLE }),
      }
    }
    if (!secIdentityMatchesServer) {
      return {
        style: hintWarningStyle,
        text: t('settings.sec.hintPending'),
      }
    }
    if (secIdentityActive) {
      return {
        style: hintOkStyle,
        text: t('settings.sec.hintActive'),
      }
    }
    return {
      style: hintWarningStyle,
      text: t('settings.sec.hintUnconfirmed'),
    }
  })()

  const handleResetField = (fields: string[]) => {
    if (!fields.length) return
    setPendingReset(fields)
  }

  // Clearing a keychain-stored secret: route to the explicit clear-secret
  // endpoint instead of /reset so the destructive delete is its own intent
  // (BUG-005). Same confirm-modal UX as a settings.json reset.
  const handleClearSecret = (field: string) => {
    if (!field) return
    setPendingClearSecret(field)
  }

  if (isLoading) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '48px',
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-mono)',
          fontSize: '11px',
        }}
      >
        {t('settings.loading')}
      </div>
    )
  }

  // ── Load-error state ───────────────────────────────────────────────────────
  // When the settings query failed (backend unreachable / error) we must NOT
  // render the editable key form: auto-save would no-op (initializedRef stays
  // false) and the user would type secrets that silently never persist
  // (BUG-026). Show a clear error + retry instead.
  if (isError || !settingsResp) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-start',
          gap: '12px',
          background: 'var(--negative-bg)',
          border: '1px solid var(--negative)',
          borderRadius: 'var(--r-sm)',
          padding: '20px 22px',
          fontFamily: 'var(--font-mono)',
        }}
        role="alert"
      >
        <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--negative)' }}>
          {t('settings.loadError.title')}
        </div>
        <div style={{ fontSize: '11px', color: 'var(--text-primary)', lineHeight: 1.6 }}>
          {t('settings.loadError.body')}
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          style={{
            background: 'var(--bg-3)',
            border: '1px solid var(--border)',
            borderRadius: '4px',
            padding: '7px 14px',
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: 'var(--text-secondary)',
            cursor: isFetching ? 'not-allowed' : 'pointer',
            opacity: isFetching ? 0.55 : 1,
          }}
        >
          {isFetching ? t('settings.loading') : t('common.retry')}
        </button>
      </div>
    )
  }

  return (
    <div>
      {/* ── Startup error banner ── */}
      {/* Surfaces validate_runtime_config() failures captured at server boot
          so users see "ANTHROPIC_API_KEY missing" instead of a silent
          server crash or a 60-second pipeline hang. */}
      {startupError && (
        <div
          style={{
            background: 'var(--negative-bg)',
            border: '1px solid var(--negative)',
            borderRadius: 'var(--r-sm)',
            padding: '12px 14px',
            marginBottom: '12px',
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: 'var(--negative)',
            display: 'flex',
            flexDirection: 'column',
            gap: '6px',
          }}
        >
          <div style={{ fontWeight: 600 }}>{t('settings.startupError.title')}</div>
          <div style={{ color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>{startupError}</div>
          <div style={{ color: 'var(--text-muted)', fontSize: '10px' }}>
            {t('settings.startupError.hint')}
          </div>
        </div>
      )}

      {/* ── Save indicator ── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          marginBottom: '12px',
          height: '18px',
        }}
      >
        {saveState === 'saving' && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '10px',
              color: 'var(--text-muted)',
            }}
          >
            {t('settings.saving')}
          </span>
        )}
        {saveState === 'saved' && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '10px',
              color: 'var(--positive)',
            }}
          >
            {t('settings.savedOk')}
          </span>
        )}
        {saveState === 'error' && (
          <button
            type="button"
            onClick={retrySave}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '10px',
              color: 'var(--negative)',
              background: 'transparent',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              textDecoration: 'underline',
            }}
          >
            {t('settings.saveFailedRetry')}
          </button>
        )}
      </div>

      {/* ═════════════════════════════════════════════
          Section 1: Data Sources
          ═════════════════════════════════════════════ */}
      <section style={sectionStyle}>
        <h2 style={sectionTitleStyle}>{t('settings.section.dataSources')}</h2>
        <div style={fieldGroupStyle}>
          {/* FMP */}
          <div style={fieldStyle}>
            <div style={labelStyle}>
              <span>{t('settings.fmp.label')}</span>
              {fmpConfigured ? (
                <span style={configuredBadgeStyle}>{t('settings.badge.configured')}</span>
              ) : (
                <span style={requiredBadgeStyle}>{t('settings.badge.required')}</span>
              )}
              <SourceBadge source={sourceOf('fmp_api_key')} />
              {sourceOf('fmp_api_key') === 'keychain' && (
                <button
                  style={ghostBtnStyle}
                  onClick={() => handleClearSecret('fmp_api_key')}
                  title={t('settings.resetToEnv.titleKeychain')}
                >
                  {t('settings.resetToEnv')}
                </button>
              )}
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <InputWithFocus
                type="password"
                value={fmpKey}
                onChange={(e) => handleFmpKeyChange(e.target.value)}
                placeholder={fmpConfigured ? '••••••••' : t('settings.fmp.placeholder')}
              />
            </div>
            <p style={hintStyle}>{t('settings.fmp.hint')}</p>
          </div>

          {/* Finnhub */}
          <div style={fieldStyle}>
            <div style={labelStyle}>
              <span>{t('settings.finnhub.label')}</span>
              {finnhubConfigured ? (
                <span style={configuredBadgeStyle}>{t('settings.badge.configured')}</span>
              ) : (
                <span style={optionalBadgeStyle}>{t('settings.badge.optional')}</span>
              )}
              <SourceBadge source={sourceOf('finnhub_api_key')} />
              {sourceOf('finnhub_api_key') === 'keychain' && (
                <button
                  style={ghostBtnStyle}
                  onClick={() => handleClearSecret('finnhub_api_key')}
                  title={t('settings.resetToEnv.titleKeychain')}
                >
                  {t('settings.resetToEnv')}
                </button>
              )}
            </div>
            <InputWithFocus
              type="password"
              value={finnhubKey}
              onChange={(e) => handleFinnhubKeyChange(e.target.value)}
              placeholder={finnhubConfigured ? '••••••••' : t('settings.finnhub.placeholder')}
            />
            <p style={hintStyle}>{t('settings.finnhub.hint')}</p>
          </div>

          {/* SEC EDGAR */}
          <div style={fieldStyle}>
            <div style={labelStyle}>
              <span>{t('settings.sec.label')}</span>
              {secIdentityActive ? (
                <span style={configuredBadgeStyle}>{t('settings.badge.active')}</span>
              ) : secIdentityLocallyValid ? (
                <span style={pendingBadgeStyle}>{t('settings.badge.pending')}</span>
              ) : (
                <span style={requiredBadgeStyle}>{t('settings.badge.required')}</span>
              )}
              <SourceBadge source={sourceOf('sec_user_agent')} />
              {sourceOf('sec_user_agent') === 'settings_json' && (
                <button
                  style={ghostBtnStyle}
                  onClick={() => handleResetField(['sec_user_agent'])}
                  title={t('settings.resetToEnv.titleSettingsJson')}
                >
                  {t('settings.resetToEnv')}
                </button>
              )}
            </div>
            <InputWithFocus
              type="text"
              value={secUserAgent}
              onChange={(e) => handleSecAgentChange(e.target.value)}
              placeholder={t('settings.sec.placeholder')}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={!secIdentityLocallyValid}
              data-invalid={!secIdentityLocallyValid || undefined}
              style={
                !secIdentityLocallyValid
                  ? {
                      borderColor: 'var(--danger)',
                      boxShadow: '0 0 0 1px var(--danger-glow-soft)',
                    }
                  : undefined
              }
            />
            <p style={secIdentityHint.style}>{secIdentityHint.text}</p>
            {secIdentityPreview && (
              <p style={secHeaderPreviewStyle}>
                {t('settings.sec.preview')}
                {secIdentityPreview}
              </p>
            )}
          </div>
        </div>
      </section>

      {/* ═════════════════════════════════════════════
          Section 1b: SEC 13F Institutional Holdings
          ═════════════════════════════════════════════ */}
      <SecHoldingsSection />

      {/* ═════════════════════════════════════════════
          Section 2: LLM Provider
          ═════════════════════════════════════════════ */}
      <section style={sectionStyle}>
        <h2 style={sectionTitleStyle}>{t('settings.section.aiModel')}</h2>
        <div style={fieldGroupStyle}>
          <div style={fieldStyle}>
            <div style={labelStyle}>
              <span>{t('settings.model.label')}</span>
              <SourceBadge source={sourceOf('model_name')} />
              {sourceOf('model_name') === 'settings_json' && (
                <button
                  style={ghostBtnStyle}
                  onClick={() => handleResetField(['model_name'])}
                  title={t('settings.resetToEnv.titleModel')}
                >
                  {t('settings.resetToEnv')}
                </button>
              )}
            </div>
            <SelectWithFocus
              value={modelName || settingsResp?.model_name || ''}
              onChange={(e) => handleModelChange(e.target.value)}
            >
              {MODEL_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </SelectWithFocus>
          </div>

          <div style={fieldStyle}>
            <div style={labelStyle}>
              <span>API Key</span>
              {(() => {
                const keyField = `${currentProvider}_api_key_set` as keyof typeof settingsResp
                const isSet = settingsResp?.[keyField]
                return isSet ? (
                  <span style={configuredBadgeStyle}>{t('settings.badge.configured')}</span>
                ) : (
                  <span style={requiredBadgeStyle}>{t('settings.badge.required')}</span>
                )
              })()}
              <SourceBadge source={sourceOf(`${currentProvider}_api_key`)} />
              {sourceOf(`${currentProvider}_api_key`) === 'keychain' && (
                <button
                  style={ghostBtnStyle}
                  onClick={() => handleClearSecret(`${currentProvider}_api_key`)}
                  title={t('settings.resetToEnv.titleKeychain')}
                >
                  {t('settings.resetToEnv')}
                </button>
              )}
            </div>
            <InputWithFocus
              type="password"
              value={llmApiKey}
              onChange={(e) => handleLlmKeyChange(e.target.value)}
              placeholder={(() => {
                const keyField = `${currentProvider}_api_key_set` as keyof typeof settingsResp
                return settingsResp?.[keyField] ? '••••••••' : `Enter ${currentProvider} API key`
              })()}
            />
          </div>
        </div>
      </section>

      <CosmicAppearanceSection />

      {pendingReset && (
        <ResetConfirmModal
          fields={pendingReset}
          onCancel={() => setPendingReset(null)}
          onConfirm={() => {
            const f = pendingReset
            setPendingReset(null)
            resetMutation.mutate(f)
          }}
        />
      )}

      {pendingClearSecret && (
        <ResetConfirmModal
          fields={[pendingClearSecret]}
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

function ResetConfirmModal({
  fields,
  onCancel,
  onConfirm,
}: {
  fields: string[]
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
        background: 'color-mix(in srgb, var(--bg-void) 72%, transparent)',
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
          padding: '20px 22px',
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          boxShadow: '0 16px 40px color-mix(in srgb, var(--bg-void) 40%, transparent)',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
      >
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            letterSpacing: '0.06em',
            color: 'var(--warning)',
          }}
        >
          {t('settings.reset.confirmTitle')}
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.55 }}>
          {t('settings.reset.confirmBodyPrefix')}{' '}
          <code style={{ color: 'var(--accent-cyan)' }}>{fields.join(', ')}</code>
          {t('settings.reset.confirmBodySuffix')}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
          <button
            type="button"
            onClick={onCancel}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              padding: '7px 14px',
              borderRadius: 6,
              border: '1px solid var(--border-soft)',
              background: 'transparent',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
            }}
          >
            {t('settings.reset.cancel')}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              padding: '7px 14px',
              borderRadius: 6,
              border: 'none',
              background: 'var(--warning)',
              color: 'var(--bg-void)',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            {t('settings.reset.confirm')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── SEC 13F institutional-holdings section ─────────────────────────────────
// The 13F reverse index is OFF by default (building it downloads a whole
// quarter of market-wide filings — ~1-2h). This section lets the user see
// cache state, flip auto-sync, and trigger a manual build. Without it the
// 13F report chapter is permanently cold and the old UI lied that a sync
// was already running. Polls /status while a refresh is in flight.

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

function SecHoldingsSection(): React.ReactElement {
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
    // Poll only while a build is running so the row count / status update
    // live; otherwise stay quiet (the cache changes at most quarterly).
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

  // Gate the heavy 13F build behind an explicit confirm (BUG-009): a single
  // click used to kick off a ~1-2h market-wide download with no warning.
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
    <section style={sectionStyle}>
      <h2 style={sectionTitleStyle}>{t('settings.section.secHoldings')}</h2>
      <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 16px', lineHeight: 1.6 }}>
        {t('settings.secHoldings.intro')}
      </p>

      {/* Cache status + manual trigger */}
      <div style={fieldStyle}>
        <div style={labelStyle}>
          <span>{statusLine}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <button
            type="button"
            disabled={!identityOk || running}
            onClick={() => setConfirmOpen(true)}
            style={{
              background: 'var(--bg-3)',
              border: '1px solid var(--border)',
              borderRadius: '4px',
              padding: '7px 14px',
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              color: 'var(--text-secondary)',
              cursor: !identityOk || running ? 'not-allowed' : 'pointer',
              opacity: !identityOk || running ? 0.55 : 1,
              transition: 'all 0.15s',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            {/* Refresh icon — inline SVG per style guide */}
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
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
            <span style={{ ...hintWarningStyle, marginTop: 0 }}>
              {t('settings.secHoldings.identityRequired')}
            </span>
          )}
        </div>
        {running && (
          <>
            {startedAtLabel && (
              <p style={{ ...hintStyle, marginTop: '6px', lineHeight: 1.5 }}>{startedAtLabel}</p>
            )}
            <p style={{ ...hintStyle, marginTop: '6px', lineHeight: 1.5 }}>
              {t('settings.secHoldings.runningHint')}
            </p>
          </>
        )}
        {refreshMutation.isError && !running && (
          <p style={{ ...hintInvalidStyle, marginTop: '6px', lineHeight: 1.5 }}>
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
                fontSize: '10px',
                cursor: 'pointer',
                textDecoration: 'underline',
              }}
            >
              {t('common.retry')}
            </button>
          </p>
        )}
      </div>

      {/* Auto-sync toggle */}
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

// Confirm dialog gating the heavy 13F build (BUG-009). Reuses the cosmic modal
// chrome from ResetConfirmModal but with a "start sync" affirmative.
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
        background: 'color-mix(in srgb, var(--bg-void) 72%, transparent)',
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
          padding: '20px 22px',
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          boxShadow: '0 16px 40px color-mix(in srgb, var(--bg-void) 40%, transparent)',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
      >
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            letterSpacing: '0.06em',
            color: 'var(--warning)',
          }}
        >
          {t('settings.secHoldings.confirmTitle')}
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.55 }}>
          {t('settings.secHoldings.confirmBody')}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
          <button
            type="button"
            onClick={onCancel}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              padding: '7px 14px',
              borderRadius: 6,
              border: '1px solid var(--border-soft)',
              background: 'transparent',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
            }}
          >
            {t('settings.reset.cancel')}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              padding: '7px 14px',
              borderRadius: 6,
              border: 'none',
              background: 'var(--warning)',
              color: 'var(--bg-void)',
              cursor: 'pointer',
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

// ── Cosmic appearance section (桌面动效 toggles) ───────────────────────────
function CosmicAppearanceSection(): React.ReactElement {
  const { t } = useI18n()
  const cursorOn = useUiStore((s) => s.cursorTrailEnabled)
  const splineOn = useUiStore((s) => s.splineEnabled)
  const setCursor = useUiStore((s) => s.setCursorTrailEnabled)
  const setSpline = useUiStore((s) => s.setSplineEnabled)

  // 省电模式 = 所有装饰动效全关。开关 ON 时表示「正在省电」。
  const saverOn = !cursorOn && !splineOn
  function toggleSaver() {
    if (saverOn) {
      setCursor(true)
      setSpline(true)
    } else {
      setCursor(false)
      setSpline(false)
    }
  }

  return (
    <section style={sectionStyle}>
      <h2 style={sectionTitleStyle}>{t('settings.appearance.title')}</h2>
      <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 16px' }}>
        {t('settings.appearance.intro')}
      </p>

      <ToggleRow
        label={t('settings.appearance.saver')}
        desc={t('settings.appearance.saverDesc')}
        enabled={saverOn}
        onToggle={toggleSaver}
      />
      <ToggleRow
        label={t('settings.appearance.cursor')}
        desc={t('settings.appearance.cursorDesc')}
        enabled={cursorOn}
        onToggle={() => setCursor(!cursorOn)}
      />
      <ToggleRow
        label={t('settings.appearance.spline')}
        desc={t('settings.appearance.splineDesc')}
        enabled={splineOn}
        onToggle={() => setSpline(!splineOn)}
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
        padding: '12px 0',
        borderTop: '1px solid var(--border-soft)',
      }}
    >
      <div style={{ paddingRight: 24 }}>
        <div style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 500 }}>{label}</div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, lineHeight: 1.5 }}>
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
