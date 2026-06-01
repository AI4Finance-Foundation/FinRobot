import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, BASE_URL, exportDiagnosticsLogs } from '../api/client'
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

// ─── Custom Checkbox ───────────────────────────────────────────────────────

function Checkbox({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <button
      role="checkbox"
      aria-checked={checked}
      onClick={() => !disabled && onChange(!checked)}
      style={{
        width: '14px',
        height: '14px',
        flexShrink: 0,
        border: `1px solid ${checked ? 'var(--accent)' : 'var(--border)'}`,
        borderRadius: '2px',
        background: checked ? 'var(--accent-dim)' : 'var(--bg-3)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: disabled ? 'not-allowed' : 'pointer',
        padding: 0,
        transition: 'all 0.12s',
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {checked && (
        <svg width="9" height="7" viewBox="0 0 9 7" fill="none">
          <path
            d="M1 3.5L3.5 6L8 1"
            stroke="var(--accent)"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
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
  const { data: settingsResp, isLoading } = useQuery({
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

  // ── Section 3: Logging / Diagnostics ────────────────────────────────────
  const [logLevel, setLogLevel] = useState('INFO')
  const [logToFile, setLogToFile] = useState(false)
  const [logRetentionDays, setLogRetentionDays] = useState(7)
  const [exportState, setExportState] = useState<'idle' | 'loading' | 'error'>('idle')

  // Pending fields awaiting user confirmation before resetting their
  // settings.json override back to the .env default. Set by handleResetField,
  // cleared by the inline confirm modal.
  const [pendingReset, setPendingReset] = useState<string[] | null>(null)

  // ── Save indicator ───────────────────────────────────────────────────────
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const initializedRef = useRef(false)

  // Populate from server on first load
  useEffect(() => {
    if (!settingsResp || initializedRef.current) return
    initializedRef.current = true
    if (settingsResp.model_name) setModelName(settingsResp.model_name)
    if (settingsResp.sec_user_agent) setSecUserAgent(settingsResp.sec_user_agent)
    if (settingsResp.log_level) setLogLevel(settingsResp.log_level)
    setLogToFile(settingsResp.log_to_file)
    setLogRetentionDays(settingsResp.log_retention_days)
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
      saveTimerRef.current = setTimeout(() => setSaveState('idle'), 3000)
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
      setSaveState('saving')
      debounceRef.current = setTimeout(() => {
        settingsMutationRef.current.mutate(payload as never)
      }, 500)
    },
    [],
  )

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

  // Logging field helpers
  const handleLogLevelChange = (v: string) => {
    setLogLevel(v)
    scheduleStandardSave({ log_level: v })
  }

  const handleLogToFileChange = (v: boolean) => {
    setLogToFile(v)
    scheduleStandardSave({ log_to_file: v })
  }

  const handleLogRetentionDaysChange = (v: number) => {
    setLogRetentionDays(v)
    scheduleStandardSave({ log_retention_days: v })
  }

  const handleExportLogs = async () => {
    setExportState('loading')
    try {
      const blob = await exportDiagnosticsLogs()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'finrobot-logs.zip'
      a.click()
      URL.revokeObjectURL(url)
      setExportState('idle')
    } catch (err) {
      setExportState('error')
      addToast({
        type: 'error',
        title: t('settings.export.failTitle'),
        description: (err as Error).message,
      })
      setTimeout(() => setExportState('idle'), 3000)
    }
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
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '10px',
              color: 'var(--negative)',
            }}
          >
            {t('settings.saveFailedShort')}
          </span>
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
                  onClick={() => handleResetField(['fmp_api_key'])}
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
                  onClick={() => handleResetField(['finnhub_api_key'])}
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
                  onClick={() => handleResetField([`${currentProvider}_api_key`])}
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

      {/* ═════════════════════════════════════════════
          Section 3: Logging / Diagnostics
          ═════════════════════════════════════════════ */}
      <section style={sectionStyle}>
        <h2 style={sectionTitleStyle}>{t('settings.section.logging')}</h2>
        <div style={fieldGroupStyle}>
          {/* Log level */}
          <div style={fieldStyle}>
            <div style={labelStyle}>
              <span>{t('settings.log.level')}</span>
            </div>
            <SelectWithFocus
              value={logLevel}
              onChange={(e) => handleLogLevelChange(e.target.value)}
            >
              {(['DEBUG', 'INFO', 'WARNING', 'ERROR'] as const).map((lvl) => (
                <option key={lvl} value={lvl}>
                  {lvl}
                </option>
              ))}
            </SelectWithFocus>
            <p style={hintStyle}>{t('settings.log.levelHint')}</p>
          </div>

          {/* Log to file toggle */}
          <div style={fieldStyle}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              <Checkbox checked={logToFile} onChange={handleLogToFileChange} />
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: 'var(--text-primary)',
                }}
              >
                {t('settings.log.toFile')}
              </span>
            </div>
            <p style={{ ...hintStyle, marginTop: '4px' }}>{t('settings.log.toFileHint')}</p>
          </div>

          {/* Retention days */}
          <div style={fieldStyle}>
            <div style={labelStyle}>
              <span>{t('settings.log.retention')}</span>
            </div>
            <InputWithFocus
              type="number"
              value={logRetentionDays}
              min={1}
              onChange={(e) => {
                const n = parseInt(e.target.value)
                if (!isNaN(n) && n >= 1) handleLogRetentionDaysChange(n)
              }}
              style={{ width: '100px' }}
            />
            <p style={hintStyle}>{t('settings.log.retentionHint')}</p>
          </div>

          {/* Export button */}
          <div style={fieldStyle}>
            <div style={labelStyle}>
              <span>{t('settings.log.diagnostics')}</span>
            </div>
            <div>
              <button
                type="button"
                disabled={exportState === 'loading'}
                onClick={handleExportLogs}
                style={{
                  background: exportState === 'error' ? 'var(--negative-bg)' : 'var(--bg-3)',
                  border: `1px solid ${exportState === 'error' ? 'var(--negative)' : 'var(--border)'}`,
                  borderRadius: '4px',
                  padding: '7px 14px',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: exportState === 'error' ? 'var(--negative)' : 'var(--text-secondary)',
                  cursor: exportState === 'loading' ? 'not-allowed' : 'pointer',
                  opacity: exportState === 'loading' ? 0.6 : 1,
                  transition: 'all 0.15s',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                {/* Download icon — inline SVG per style guide */}
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
                  <path
                    d="M6 1v7M3.5 5.5L6 8l2.5-2.5M2 10h8"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                {exportState === 'loading'
                  ? t('settings.export.packing')
                  : exportState === 'error'
                    ? t('settings.export.failTitle')
                    : t('settings.export.button')}
              </button>
            </div>
            <p style={hintStyle}>{t('settings.export.hint')}</p>
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
        background: 'rgba(5,5,13,0.72)',
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
          boxShadow: '0 16px 40px rgba(0,0,0,0.4)',
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
              color: '#1a1207',
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
