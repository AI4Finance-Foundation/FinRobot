import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

interface Props {
  onComplete: () => void
}

const MODEL_OPTIONS = [
  { value: 'deepseek:deepseek-chat', label: 'DeepSeek Chat' },
  { value: 'anthropic:claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
  { value: 'anthropic:claude-opus-4-6', label: 'Claude Opus 4.6' },
  { value: 'openai:gpt-4o', label: 'GPT-4o' },
]

export default function SettingsView({ onComplete }: Props) {
  const queryClient = useQueryClient()

  const { data: settingsResp, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/settings')
      if (error) throw new Error('Failed to load settings')
      return data
    },
  })

  const [modelName, setModelName] = useState('')
  const [keys, setKeys] = useState<Record<string, string>>({})
  const [secUserAgent, setSecUserAgent] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  // Sync model_name from server on first load
  const settings = settingsResp
  if (settings && !modelName) {
    setModelName(settings.model_name)
    setSecUserAgent(settings.sec_user_agent)
  }

  const mutation = useMutation({
    mutationFn: async (body: Record<string, string>) => {
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
      setKeys({})
      setError(null)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
    onError: (err: Error) => {
      setError(err.message)
    },
  })

  const handleSave = () => {
    const body: Record<string, string> = {}
    if (modelName) body.model_name = modelName
    if (secUserAgent) body.sec_user_agent = secUserAgent
    for (const [k, v] of Object.entries(keys)) {
      if (v.trim()) body[k] = v.trim()
    }
    mutation.mutate(body)
  }

  const currentProvider = (modelName || settings?.model_name || '').split(':')[0]

  const isReady = (() => {
    if (!settings) return false
    if (currentProvider === 'test') return true
    const keyField = `${currentProvider}_api_key_set` as keyof typeof settings
    return Boolean(settings[keyField])
  })()

  if (isLoading) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        color: 'var(--text-muted)',
      }}>
        Loading settings...
      </div>
    )
  }

  return (
    <div style={{
      maxWidth: '560px',
      margin: '0 auto',
      padding: 'var(--sp-8) var(--sp-6)',
    }}>
      <h2 style={{
        fontSize: '1.1rem',
        fontWeight: 700,
        color: 'var(--text-primary)',
        marginBottom: 'var(--sp-2)',
      }}>Settings</h2>

      {!isReady && (
        <div className="warning-banner" style={{ marginBottom: 'var(--sp-5)' }}>
          <svg viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 1L1 14h14L8 1zm0 4.5v4m0 2v.5" />
          </svg>
          <div>
            Configure an API key for <strong>{currentProvider}</strong> to continue.
          </div>
        </div>
      )}

      {/* LLM Provider */}
      <div className="card" style={{ marginBottom: 'var(--sp-5)' }}>
        <div className="card-header">
          <span className="card-title">LLM Provider</span>
        </div>
        <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: 'var(--sp-1)' }}>
              Model
            </label>
            <select
              className="input-field"
              value={modelName || settings?.model_name || ''}
              onChange={(e) => setModelName(e.target.value)}
            >
              {MODEL_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {(['anthropic', 'deepseek', 'openai'] as const).map((provider) => {
            const keyField = `${provider}_api_key`
            const isSet = settings?.[`${provider}_api_key_set` as keyof typeof settings]
            const isRequired = provider === currentProvider
            return (
              <div key={provider} style={{ opacity: isRequired ? 1 : 0.5, transition: 'opacity 0.15s' }}>
                <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: 'var(--sp-1)' }}>
                  {provider.charAt(0).toUpperCase() + provider.slice(1)} API Key
                  {isRequired && !isSet && (
                    <span style={{
                      marginLeft: 'var(--sp-2)',
                      fontSize: '0.68rem',
                      color: 'var(--gold)',
                      fontWeight: 600,
                    }}>required</span>
                  )}
                  {!isRequired && !isSet && (
                    <span style={{
                      marginLeft: 'var(--sp-2)',
                      fontSize: '0.68rem',
                      color: 'var(--text-muted)',
                    }}>optional</span>
                  )}
                  {isSet && (
                    <span style={{
                      marginLeft: 'var(--sp-2)',
                      fontSize: '0.68rem',
                      color: 'var(--positive)',
                    }}>configured</span>
                  )}
                </label>
                <input
                  type="password"
                  className="input-field"
                  value={keys[keyField] || ''}
                  onChange={(e) => setKeys({ ...keys, [keyField]: e.target.value })}
                  placeholder={isSet ? '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022' : 'Not set'}
                />
              </div>
            )
          })}
        </div>
      </div>

      {/* Data Providers */}
      <div className="card" style={{ marginBottom: 'var(--sp-5)' }}>
        <div className="card-header">
          <span className="card-title">Data Providers</span>
          <span className="card-badge">Optional</span>
        </div>
        <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
          {(['fmp', 'finnhub'] as const).map((provider) => {
            const keyField = `${provider}_api_key`
            const isSet = settings?.[`${provider}_api_key_set` as keyof typeof settings]
            return (
              <div key={provider}>
                <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: 'var(--sp-1)' }}>
                  {provider.toUpperCase()} API Key
                  {isSet && (
                    <span style={{
                      marginLeft: 'var(--sp-2)',
                      fontSize: '0.68rem',
                      color: 'var(--positive)',
                    }}>configured</span>
                  )}
                </label>
                <input
                  type="password"
                  className="input-field"
                  value={keys[keyField] || ''}
                  onChange={(e) => setKeys({ ...keys, [keyField]: e.target.value })}
                  placeholder={isSet ? '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022' : 'Not set'}
                />
              </div>
            )
          })}
          <div>
            <label style={{ display: 'block', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: 'var(--sp-1)' }}>
              SEC User-Agent
            </label>
            <input
              type="text"
              className="input-field"
              value={secUserAgent}
              onChange={(e) => setSecUserAgent(e.target.value)}
              placeholder="Company Name admin@example.com"
            />
          </div>
        </div>
      </div>

      {/* Status */}
      {settings && (
        <div style={{
          fontSize: '0.78rem',
          color: 'var(--text-secondary)',
          marginBottom: 'var(--sp-5)',
        }}>
          Available providers:{' '}
          <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
            {settings.available_providers.join(', ')}
          </span>
        </div>
      )}

      {/* Actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-4)' }}>
        <button
          className="btn btn-primary"
          onClick={handleSave}
          disabled={mutation.isPending}
        >
          {mutation.isPending ? 'Saving...' : 'Save Settings'}
        </button>
        {isReady && (
          <button className="btn" onClick={onComplete}>
            Continue to Workspace
          </button>
        )}
        {saved && (
          <span style={{ fontSize: '0.78rem', color: 'var(--positive)' }}>Saved</span>
        )}
      </div>

      {error && <div className="error-msg" style={{ marginTop: 'var(--sp-4)' }}>{error}</div>}
    </div>
  )
}
