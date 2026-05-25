import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, BASE_URL } from '../api/client'
import { useToastStore } from '../stores/toastStore'
import { useUiStore } from '../stores/uiStore'
import { mapErrorToUserMessage, FetchHttpError } from '../utils/errorMessage'

interface Props {
  onComplete: () => void
}

// ─── Model Options ─────────────────────────────────────────────────────────

const MODEL_OPTIONS = [
  { value: 'deepseek:deepseek-chat', label: 'DeepSeek V3' },
  { value: 'deepseek:deepseek-reasoner', label: 'DeepSeek R1' },
  { value: 'anthropic:claude-sonnet-4-6', label: 'Claude Sonnet 4' },
  { value: 'openai:gpt-4o', label: 'GPT-4o' },
  { value: 'openai:qwen3-235b-a22b', label: 'Qwen3 235B' },
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

const SOURCE_LABELS: Record<string, string> = {
  keychain: '来自 keychain',
  settings_json: '来自 settings.json',
  env: '来自 .env',
  default: '默认值',
}

function SourceBadge({ source }: { source?: string | null }) {
  if (!source) return null
  const label = SOURCE_LABELS[source] ?? source
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

// ─── Notification Channel Row ──────────────────────────────────────────────

type TestState = 'idle' | 'loading' | 'ok' | 'fail'

function TestButton({ channel, disabled }: { channel: string; disabled?: boolean }) {
  const [state, setState] = useState<TestState>('idle')

  const handleTest = async () => {
    setState('loading')
    try {
      const resp = await fetch(`${BASE_URL}/api/notify/test/${channel}`, {
        method: 'POST',
      })
      const json = await resp.json()
      setState(json?.success ? 'ok' : 'fail')
    } catch {
      setState('fail')
    }
    // Reset after 3s
    setTimeout(() => setState('idle'), 3000)
  }

  const label = state === 'loading' ? '...' : state === 'ok' ? '✓' : state === 'fail' ? '✗' : '测试'

  const style: React.CSSProperties = {
    ...ghostBtnStyle,
    color:
      state === 'ok'
        ? 'var(--positive)'
        : state === 'fail'
          ? 'var(--negative)'
          : 'var(--text-secondary)',
    borderColor:
      state === 'ok' ? 'var(--positive)' : state === 'fail' ? 'var(--negative)' : 'var(--border)',
    opacity: disabled ? 0.4 : 1,
    cursor: disabled ? 'not-allowed' : 'pointer',
    minWidth: '36px',
    textAlign: 'center',
  }

  return (
    <button style={style} onClick={handleTest} disabled={disabled || state === 'loading'}>
      {label}
    </button>
  )
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
  const queryClient = useQueryClient()
  const addToast = useToastStore((s) => s.addToast)

  // ── Remote settings ──────────────────────────────────────────────────────
  const { data: settingsResp, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/settings')
      if (error) throw new Error('加载设置失败')
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

  // ── Section 3: Notifications (managed locally, saved via direct fetch) ───
  const [notifyDesktop, _setNotifyDesktop] = useState(true)

  const [feishuEnabled, setFeishuEnabled] = useState(false)
  const [feishuUrl, setFeishuUrl] = useState('')

  const [telegramEnabled, setTelegramEnabled] = useState(false)
  const [telegramToken, setTelegramToken] = useState('')
  const [telegramChatId, setTelegramChatId] = useState('')

  const [discordEnabled, setDiscordEnabled] = useState(false)
  const [discordUrl, setDiscordUrl] = useState('')

  const [emailEnabled, setEmailEnabled] = useState(false)
  const [emailTo, setEmailTo] = useState('')
  const [emailSmtpHost, setEmailSmtpHost] = useState('')
  const [emailSmtpPort, setEmailSmtpPort] = useState('587')

  const [webhookEnabled, setWebhookEnabled] = useState(false)
  const [webhookUrl, setWebhookUrl] = useState('')

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
      addToast({ type: 'error', title: '保存失败', description: mapErrorToUserMessage(err) })
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
        title: '已恢复 .env 默认',
        description: 'settings.json 中的覆盖已清除，重启后从环境变量重新加载',
      })
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: '恢复失败', description: mapErrorToUserMessage(err) })
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
    (payload: Record<string, string | null>) => {
      if (!initializedRef.current) return
      if (debounceRef.current) clearTimeout(debounceRef.current)
      setSaveState('saving')
      debounceRef.current = setTimeout(() => {
        settingsMutationRef.current.mutate(payload)
      }, 500)
    },
    [],
  )

  // ── Notify field save (direct fetch, no schema constraint) ───────────────
  const notifyDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const scheduleNotifySave = useCallback(
    (fields: Record<string, string>) => {
      if (!initializedRef.current) return
      if (notifyDebounceRef.current) clearTimeout(notifyDebounceRef.current)
      setSaveState('saving')
      notifyDebounceRef.current = setTimeout(async () => {
        try {
          const resp = await fetch(`${BASE_URL}/api/settings`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(fields),
          })
          if (!resp.ok) {
            const j = await resp.json().catch(() => ({}))
            throw new Error(j?.detail || 'Notification settings save failed')
          }
          setSaveState('saved')
          saveTimerRef.current = setTimeout(() => setSaveState('idle'), 2500)
        } catch (err) {
          setSaveState('error')
          addToast({
            type: 'error',
            title: '保存失败',
            description: (err as Error).message,
          })
          saveTimerRef.current = setTimeout(() => setSaveState('idle'), 3000)
        }
      }, 500)
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  // Cleanup timers
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      if (notifyDebounceRef.current) clearTimeout(notifyDebounceRef.current)
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

  // Notification field helpers
  const handleFeishuUrl = (v: string) => {
    setFeishuUrl(v)
    scheduleNotifySave({ feishu_webhook_url: v })
  }
  const handleTelegramToken = (v: string) => {
    setTelegramToken(v)
    scheduleNotifySave({ telegram_bot_token: v })
  }
  const handleTelegramChatId = (v: string) => {
    setTelegramChatId(v)
    scheduleNotifySave({ telegram_chat_id: v })
  }
  const handleDiscordUrl = (v: string) => {
    setDiscordUrl(v)
    scheduleNotifySave({ discord_webhook_url: v })
  }
  const handleEmailTo = (v: string) => {
    setEmailTo(v)
    scheduleNotifySave({ email_to: v })
  }
  const handleSmtpHost = (v: string) => {
    setEmailSmtpHost(v)
    scheduleNotifySave({ email_smtp_host: v })
  }
  const handleSmtpPort = (v: string) => {
    setEmailSmtpPort(v)
    const port = parseInt(v)
    if (!isNaN(port)) scheduleNotifySave({ email_smtp_port: String(port) })
  }
  const handleWebhookUrl = (v: string) => {
    setWebhookUrl(v)
    scheduleNotifySave({ custom_webhook_url: v })
  }

  // ── Derived ──────────────────────────────────────────────────────────────
  const currentProvider = (modelName || settingsResp?.model_name || '').split(':')[0]
  const fmpConfigured = settingsResp?.fmp_api_key_set ?? false
  const finnhubConfigured = settingsResp?.finnhub_api_key_set ?? false
  const fieldSources = (settingsResp?.field_sources ?? {}) as Record<string, string>
  const sourceOf = (field: string): string | null => fieldSources[field] ?? null
  const startupError = settingsResp?.startup_error ?? null

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
        加载设置中...
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
          <div style={{ fontWeight: 600 }}>启动配置错误</div>
          <div style={{ color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>{startupError}</div>
          <div style={{ color: 'var(--text-muted)', fontSize: '10px' }}>
            修复下方字段后会自动重新校验。LLM 路由将在配置修复前返回 503。
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
            保存中…
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
            ✓ 已保存
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
            ✗ 保存失败
          </span>
        )}
      </div>

      {/* ═════════════════════════════════════════════
          Section 1: Data Sources
          ═════════════════════════════════════════════ */}
      <section style={sectionStyle}>
        <h2 style={sectionTitleStyle}>数据源</h2>
        <div style={fieldGroupStyle}>
          {/* FMP */}
          <div style={fieldStyle}>
            <div style={labelStyle}>
              <span>FMP API 密钥</span>
              {fmpConfigured ? (
                <span style={configuredBadgeStyle}>已配置</span>
              ) : (
                <span style={requiredBadgeStyle}>必填</span>
              )}
              <SourceBadge source={sourceOf('fmp_api_key')} />
              {sourceOf('fmp_api_key') === 'keychain' && (
                <button
                  style={ghostBtnStyle}
                  onClick={() => handleResetField(['fmp_api_key'])}
                  title="清除 keychain 中的覆盖，让 .env 重新生效"
                >
                  恢复 .env
                </button>
              )}
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <InputWithFocus
                type="password"
                value={fmpKey}
                onChange={(e) => handleFmpKeyChange(e.target.value)}
                placeholder={fmpConfigured ? '••••••••' : '输入 FMP API 密钥'}
              />
            </div>
            <p style={hintStyle}>完整准确性所需 — 在 financialmodelingprep.com 免费注册</p>
          </div>

          {/* Finnhub */}
          <div style={fieldStyle}>
            <div style={labelStyle}>
              <span>Finnhub API 密钥</span>
              {finnhubConfigured ? (
                <span style={configuredBadgeStyle}>已配置</span>
              ) : (
                <span style={optionalBadgeStyle}>可选</span>
              )}
              <SourceBadge source={sourceOf('finnhub_api_key')} />
              {sourceOf('finnhub_api_key') === 'keychain' && (
                <button
                  style={ghostBtnStyle}
                  onClick={() => handleResetField(['finnhub_api_key'])}
                  title="清除 keychain 中的覆盖，让 .env 重新生效"
                >
                  恢复 .env
                </button>
              )}
            </div>
            <InputWithFocus
              type="password"
              value={finnhubKey}
              onChange={(e) => handleFinnhubKeyChange(e.target.value)}
              placeholder={finnhubConfigured ? '••••••••' : '输入 Finnhub API 密钥'}
            />
            <p style={hintStyle}>启用：实时新闻 + WebSocket 行情</p>
          </div>

          {/* SEC EDGAR */}
          <div style={fieldStyle}>
            <div style={labelStyle}>
              <span>SEC EDGAR User-Agent</span>
              <span style={optionalBadgeStyle}>可选</span>
              <SourceBadge source={sourceOf('sec_user_agent')} />
              {sourceOf('sec_user_agent') === 'settings_json' && (
                <button
                  style={ghostBtnStyle}
                  onClick={() => handleResetField(['sec_user_agent'])}
                  title="清除 settings.json 中的覆盖，让 .env 重新生效"
                >
                  恢复 .env
                </button>
              )}
            </div>
            <InputWithFocus
              type="email"
              value={secUserAgent}
              onChange={(e) => handleSecAgentChange(e.target.value)}
              placeholder="例如：公司名 admin@example.com"
            />
            <p style={hintStyle}>启用：10-K 年报问答 — SEC EDGAR 条款要求</p>
          </div>
        </div>
      </section>

      {/* ═════════════════════════════════════════════
          Section 2: LLM Provider
          ═════════════════════════════════════════════ */}
      <section style={sectionStyle}>
        <h2 style={sectionTitleStyle}>AI 模型</h2>
        <div style={fieldGroupStyle}>
          <div style={fieldStyle}>
            <div style={labelStyle}>
              <span>模型</span>
              <SourceBadge source={sourceOf('model_name')} />
              {sourceOf('model_name') === 'settings_json' && (
                <button
                  style={ghostBtnStyle}
                  onClick={() => handleResetField(['model_name'])}
                  title="清除 settings.json 中的 model_name 覆盖，让 .env 重新生效"
                >
                  恢复 .env
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
                  <span style={configuredBadgeStyle}>已配置</span>
                ) : (
                  <span style={requiredBadgeStyle}>必填</span>
                )
              })()}
              <SourceBadge source={sourceOf(`${currentProvider}_api_key`)} />
              {sourceOf(`${currentProvider}_api_key`) === 'keychain' && (
                <button
                  style={ghostBtnStyle}
                  onClick={() => handleResetField([`${currentProvider}_api_key`])}
                  title="清除 keychain 中的覆盖，让 .env 重新生效"
                >
                  恢复 .env
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
          Section 3: Notification Channels
          ═════════════════════════════════════════════ */}
      <section style={sectionStyle}>
        <h2 style={sectionTitleStyle}>通知通道</h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {/* Desktop — always on via Tauri native notification API; not
              user-configurable, so we render a read-only status row rather
              than a disabled checkbox the user would otherwise click in
              vain. */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span
              aria-hidden
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: 'var(--positive)',
                boxShadow: '0 0 8px var(--positive)',
                flexShrink: 0,
              }}
            />
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                color: 'var(--text-primary)',
              }}
            >
              桌面通知
            </span>
            <span style={{ ...configuredBadgeStyle, marginLeft: '4px' }}>默认开启</span>
            <span
              style={{
                marginLeft: 'auto',
                fontFamily: 'var(--font-mono)',
                fontSize: '10px',
                color: 'var(--text-muted)',
              }}
            >
              系统级 · 在 macOS 通知中心管理
            </span>
            {/* Reference notifyDesktop so the local-state hook keeps satisfying
                the lint check; the value itself is always true today. */}
            {!notifyDesktop && null}
          </div>

          {/* Feishu */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Checkbox checked={feishuEnabled} onChange={setFeishuEnabled} />
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: 'var(--text-primary)',
                }}
              >
                Feishu Webhook
              </span>
            </div>
            {feishuEnabled && (
              <div style={{ display: 'flex', gap: '8px', paddingLeft: '22px' }}>
                <InputWithFocus
                  type="url"
                  value={feishuUrl}
                  onChange={(e) => handleFeishuUrl(e.target.value)}
                  placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
                />
                <TestButton channel="feishu" disabled={!feishuUrl.trim()} />
              </div>
            )}
          </div>

          {/* Telegram */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Checkbox checked={telegramEnabled} onChange={setTelegramEnabled} />
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: 'var(--text-primary)',
                }}
              >
                Telegram Bot
              </span>
            </div>
            {telegramEnabled && (
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                  paddingLeft: '22px',
                }}
              >
                <InputWithFocus
                  type="password"
                  value={telegramToken}
                  onChange={(e) => handleTelegramToken(e.target.value)}
                  placeholder="Bot Token（@BotFather 获取）"
                />
                <div style={{ display: 'flex', gap: '8px' }}>
                  <InputWithFocus
                    type="text"
                    value={telegramChatId}
                    onChange={(e) => handleTelegramChatId(e.target.value)}
                    placeholder="Chat ID（会话 ID）"
                  />
                  <TestButton
                    channel="telegram"
                    disabled={!telegramToken.trim() || !telegramChatId.trim()}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Discord */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Checkbox checked={discordEnabled} onChange={setDiscordEnabled} />
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: 'var(--text-primary)',
                }}
              >
                Discord Webhook
              </span>
            </div>
            {discordEnabled && (
              <div style={{ display: 'flex', gap: '8px', paddingLeft: '22px' }}>
                <InputWithFocus
                  type="url"
                  value={discordUrl}
                  onChange={(e) => handleDiscordUrl(e.target.value)}
                  placeholder="https://discord.com/api/webhooks/..."
                />
                <TestButton channel="discord" disabled={!discordUrl.trim()} />
              </div>
            )}
          </div>

          {/* Email */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Checkbox checked={emailEnabled} onChange={setEmailEnabled} />
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: 'var(--text-primary)',
                }}
              >
                Email
              </span>
            </div>
            {emailEnabled && (
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                  paddingLeft: '22px',
                }}
              >
                <InputWithFocus
                  type="email"
                  value={emailTo}
                  onChange={(e) => handleEmailTo(e.target.value)}
                  placeholder="收件人邮箱地址"
                />
                <div style={{ display: 'flex', gap: '8px' }}>
                  <InputWithFocus
                    type="text"
                    value={emailSmtpHost}
                    onChange={(e) => handleSmtpHost(e.target.value)}
                    placeholder="SMTP 主机（如 smtp.gmail.com）"
                    style={{ flex: 1 }}
                  />
                  <InputWithFocus
                    type="number"
                    value={emailSmtpPort}
                    onChange={(e) => handleSmtpPort(e.target.value)}
                    placeholder="587"
                    style={{ width: '70px' }}
                  />
                  <TestButton channel="email" disabled={!emailTo.trim() || !emailSmtpHost.trim()} />
                </div>
              </div>
            )}
          </div>

          {/* Custom Webhook */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Checkbox checked={webhookEnabled} onChange={setWebhookEnabled} />
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: 'var(--text-primary)',
                }}
              >
                Custom Webhook
              </span>
            </div>
            {webhookEnabled && (
              <div style={{ display: 'flex', gap: '8px', paddingLeft: '22px' }}>
                <InputWithFocus
                  type="url"
                  value={webhookUrl}
                  onChange={(e) => handleWebhookUrl(e.target.value)}
                  placeholder="https://your-endpoint.example.com/hook"
                />
                <TestButton channel="webhook" disabled={!webhookUrl.trim()} />
              </div>
            )}
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
          确认恢复默认
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.55 }}>
          将 <code style={{ color: 'var(--accent-cyan)' }}>{fields.join(', ')}</code> 恢复为 .env
          默认值，会清除当前覆盖。
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
            取消
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
            确认恢复
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Cosmic appearance section (桌面动效 toggles) ───────────────────────────
function CosmicAppearanceSection(): React.ReactElement {
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
      <h2 style={sectionTitleStyle}>外观与电量</h2>
      <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 16px' }}>
        关掉装饰动效可以省电、降低风扇噪音。不影响任何数据和分析结果。
      </p>

      <ToggleRow
        label="省电模式"
        desc="一键关闭下面所有动效。笔记本用电池时建议开启。"
        enabled={saverOn}
        onToggle={toggleSaver}
      />
      <ToggleRow
        label="鼠标光带"
        desc="鼠标移动时跟随的彩色尾迹，纯装饰。"
        enabled={cursorOn}
        onToggle={() => setCursor(!cursorOn)}
      />
      <ToggleRow
        label="首页 3D 机器人"
        desc="股票首页背景上漂浮的 3D 模型，纯装饰。打开分析页时不会出现。"
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
