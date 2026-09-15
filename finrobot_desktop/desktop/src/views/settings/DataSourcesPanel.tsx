// ─── Data Sources panel — one row per provider: live circuit dot + key state
// + inline key entry + test. Merges the old read-only status panel with the
// tiered key form below it, which listed the same providers twice. SEC EDGAR
// identity lives here too (the 13F section renders as a sibling in
// SettingsView). All edit state lives in SettingsView (the container) so it
// survives panel switches — this component is pure render + handler
// composition over props.

import { api } from '../../api/client'
import { useQueryClient } from '@tanstack/react-query'
import { useI18n } from '../../i18n'
import { formatDate } from '../../utils/format'
import { openExternal } from '../../lib/tauri'
import { SecretInput } from './controls'
import { SEC_IDENTITY_EXAMPLE, isValidSecIdentity, secHeaderIdentityPreview } from './secIdentity'

/** Where a user signs up for each data-source API key. Shown as a "Get a key"
 * link next to every provider's hint so an analyst never has to guess where to
 * register. FMP's page sits behind Cloudflare bot-protection (server fetches
 * 403), so it isn't HTTP-reachable from CI — verified the other three return
 * 200 and confirmed FMP's register path against their docs. */
const DATA_SOURCE_SIGNUP_URLS = {
  fmp: 'https://site.financialmodelingprep.com/register',
  finnhub: 'https://finnhub.io/register',
  adanos: 'https://adanos.org/register',
  alphaVantage: 'https://www.alphavantage.co/support/#api-key',
} as const

// ── Unified data-source row (门五②) ─────────────────────────────────────────
// Mirror of finrobot.routes.settings.ProviderHealthEntry — live ProviderHealth
// breaker signals, never mocked. circuit_state tokens: 'closed' | 'open'.
export interface ProviderHealthEntryShape {
  name: string
  key_required: boolean
  key_configured: boolean | null
  available: boolean
  circuit_state: 'closed' | 'open'
  cooldown_until: string | null
  consecutive_failures: number
  last_success: string | null
  last_failure: string | null
  last_rate_limited: boolean
}

// Brand names — i18n-exempt (金融术语豁免清单); raw provider id falls through.
const PROVIDER_DISPLAY_NAMES: Record<string, string> = {
  fmp: 'FMP',
  yfinance: 'Yahoo Finance',
  finnhub: 'Finnhub',
  edgar_tools: 'SEC EDGAR',
  adanos: 'Adanos',
  alpha_vantage: 'Alpha Vantage',
  news_aggregator: 'News Aggregator',
}

// Providers that already get a dedicated config row in the Data Sources list;
// live-feed entries outside this set render as plain status rows at the end.
const KEYED_PROVIDER_ROWS = new Set([
  'yfinance',
  'fmp',
  'edgar_tools',
  'finnhub',
  'adanos',
  'alpha_vantage',
])

/** One data-source row: live circuit dot + name + state badge + inline config
 * controls on a single line, hint copy underneath. `health` undefined = the
 * provider isn't in the live breaker feed (dim dot, config still works). The
 * row deliberately shows no last-call timestamp — the dot already carries the
 * live state; per-call telemetry is noise here. */
function DataSourceRow({
  health,
  name,
  badge,
  control,
  result,
  hint,
}: {
  health: ProviderHealthEntryShape | undefined
  name: string
  badge?: React.ReactNode
  control?: React.ReactNode
  /** Test outcome / transient feedback — own status line under the controls,
   * so a long message can never squeeze the input or wrap the buttons. */
  result?: React.ReactNode
  hint?: React.ReactNode
}): React.ReactElement {
  const { t, locale } = useI18n()
  const open = health?.circuit_state === 'open'
  const dot = health === undefined ? 'is-na' : open ? 'is-bad' : 'is-ok'
  // The dot is live telemetry (is the source answering right now), NOT config
  // state — a saved key (CONFIGURED) with a tripped circuit (red dot) is a
  // normal combination. Tooltip spells that out on hover.
  const dotTitle =
    health === undefined
      ? t('settings.providerStatus.dotNa')
      : open
        ? t('settings.providerStatus.dotOpen')
        : t('settings.providerStatus.dotOk')
  return (
    <div
      className={`settings-provider-row${open ? ' is-open' : ''}${control ? ' has-control' : ''}`}
    >
      <div className="settings-provider-line">
        <div className="settings-provider-meta">
          <span
            className={`settings-provider-dot ${dot}`}
            role="img"
            aria-label={dotTitle}
            title={dotTitle}
          />
          <span className="settings-provider-name">{name}</span>
          {/* One badge slot per row — a live problem (COOLDOWN) outranks config
            state; both at once is noisy AND overflows the ~750px column,
            wrapping tripped rows taller than healthy ones. Cooldown-end time
            on hover; a saved key still shows via Clear + the •••• placeholder. */}
          {open ? (
            <span
              className="settings-badge is-required"
              title={
                health?.cooldown_until
                  ? `${t('settings.providerStatus.cooldownUntil')} ${formatDate(health.cooldown_until, locale, 'time')}`
                  : undefined
              }
            >
              {t('settings.providerStatus.cooldown')}
              {health?.last_rate_limited ? ' · 429' : ''}
            </span>
          ) : (
            badge
          )}
        </div>
        {control && <div className="settings-provider-control">{control}</div>}
      </div>
      {result && <div className="settings-provider-status">{result}</div>}
      {hint && <div className="settings-provider-hint">{hint}</div>}
    </div>
  )
}

/** Per data-source connectivity test state ("fmp" | "finnhub" | …) — each key
 * field tests on its own. */
export type DataTestState = Record<
  string,
  { status: 'idle' | 'testing' | 'done'; ok?: boolean; code?: string; detail?: string }
>

interface DataSourcesPanelProps {
  healthResp: { providers: ProviderHealthEntryShape[] } | undefined
  healthError: boolean
  fmpConfigured: boolean
  finnhubConfigured: boolean
  adanosConfigured: boolean
  alphaVantageConfigured: boolean
  fmpKey: string
  setFmpKey: (v: string) => void
  finnhubKey: string
  setFinnhubKey: (v: string) => void
  adanosKey: string
  setAdanosKey: (v: string) => void
  alphaVantageKey: string
  setAlphaVantageKey: (v: string) => void
  dataTestState: DataTestState
  setDataTestState: React.Dispatch<React.SetStateAction<DataTestState>>
  scheduleStandardSave: (payload: Record<string, unknown>) => void
  /** Persists any in-flight debounced edit before the connectivity probe, so the
   * backend tests the key the user just typed — not the value the 500ms auto-save
   * hasn't written yet (see useSettingsSave.flushPending). */
  flushPending: () => Promise<void>
  onClearSecret: (field: string) => void
  secUserAgent: string
  setSecUserAgent: (v: string) => void
  /** settingsResp.sec_user_agent — what the server currently holds. */
  serverSecUserAgent: string
  secIdentityActive: boolean
}

export function DataSourcesPanel({
  healthResp,
  healthError,
  fmpConfigured,
  finnhubConfigured,
  adanosConfigured,
  alphaVantageConfigured,
  fmpKey,
  setFmpKey,
  finnhubKey,
  setFinnhubKey,
  adanosKey,
  setAdanosKey,
  alphaVantageKey,
  setAlphaVantageKey,
  dataTestState,
  setDataTestState,
  scheduleStandardSave,
  flushPending,
  onClearSecret,
  secUserAgent,
  setSecUserAgent,
  serverSecUserAgent,
  secIdentityActive,
}: DataSourcesPanelProps): React.ReactElement {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  // ── Derived ──────────────────────────────────────────────────────────────
  // Shape-guard, not just null-guard: an unexpected health payload (proxy
  // error page, wrong endpoint) must degrade to dim dots, never crash.
  const healthEntries = Array.isArray(healthResp?.providers) ? healthResp.providers : []
  const healthByName = new Map(healthEntries.map((p) => [p.name, p]))
  const secIdentityLocallyValid = isValidSecIdentity(secUserAgent)
  const secIdentityMatchesServer = secUserAgent.trim() === serverSecUserAgent.trim()
  const secIdentityPreview = secHeaderIdentityPreview(secUserAgent)
  // Empty ≠ error: SEC is recommended-not-required, so an untouched field shows
  // calm guidance. Red only kicks in once the user has typed something invalid.
  const secIdentityInvalidInput = secUserAgent.trim() !== '' && !secIdentityLocallyValid
  const secIdentityHint = (() => {
    if (!secUserAgent.trim())
      return { cls: '', text: t('settings.sec.hintEmpty', { example: SEC_IDENTITY_EXAMPLE }) }
    if (!secIdentityLocallyValid)
      return {
        cls: 'is-bad',
        text: t('settings.sec.hintInvalid', { example: SEC_IDENTITY_EXAMPLE }),
      }
    if (!secIdentityMatchesServer) return { cls: 'is-warn', text: t('settings.sec.hintPending') }
    if (secIdentityActive) return { cls: 'is-ok', text: t('settings.sec.hintActive') }
    return { cls: 'is-warn', text: t('settings.sec.hintUnconfirmed') }
  })()

  // ── Field change handlers ────────────────────────────────────────────────
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
  const handleTestDataProvider = async (provider: string) => {
    setDataTestState((s) => ({ ...s, [provider]: { status: 'testing' } }))
    try {
      await flushPending()
      const { data, error } = await api.POST('/api/settings/test-data-provider', {
        body: { provider },
      })
      if (error || !data) throw new Error('test failed')
      setDataTestState((s) => ({
        ...s,
        [provider]: { status: 'done', ok: data.ok, code: data.code, detail: data.detail },
      }))
      void queryClient.invalidateQueries({ queryKey: ['provider-health'] })
    } catch {
      setDataTestState((s) => ({
        ...s,
        [provider]: { status: 'done', ok: false, code: 'unknown' },
      }))
    }
  }
  const handleSecAgentChange = (v: string) => {
    setSecUserAgent(v)
    scheduleStandardSave({ sec_user_agent: v })
  }

  /** Inline key controls for one unified data-source row: secret input + test
   * button + clear on the row's single line. The test OUTCOME deliberately
   * lives on the row's status line (renderTestResult) — inline it would
   * squeeze the input and wrap the buttons. FMP / Finnhub / Adanos / Alpha
   * Vantage are structurally identical — they only differ in copy, the
   * configured flag, and the settings field names. */
  const renderKeyControl = (cfg: {
    labelKey: string
    placeholderKey: string
    configured: boolean
    value: string
    onChange: (v: string) => void
    clearField: string
    testProvider: string
  }): React.ReactElement => {
    const st = dataTestState[cfg.testProvider] ?? { status: 'idle' as const }
    return (
      <>
        <SecretInput
          value={cfg.value}
          onChange={cfg.onChange}
          placeholder={cfg.configured ? '••••••••' : t(cfg.placeholderKey)}
          ariaLabel={t(cfg.labelKey)}
        />
        <button
          type="button"
          className="settings-btn"
          onClick={() => handleTestDataProvider(cfg.testProvider)}
          disabled={st.status === 'testing'}
        >
          {st.status === 'testing' ? t('settings.test.testing') : t('settings.test.button')}
        </button>
        {cfg.configured && (
          <button
            type="button"
            className="settings-clear-btn"
            onClick={() => onClearSecret(cfg.clearField)}
          >
            {t('settings.clearKey.button')}
          </button>
        )}
      </>
    )
  }
  /** Test outcome for a data-source row — rendered on the row's status line
   * (below the control line), so a long result message can never squeeze the
   * input or wrap the buttons. */
  const renderTestResult = (provider: string): React.ReactNode => {
    const st = dataTestState[provider]
    if (st?.status !== 'done') return null
    return (
      <span className={`settings-test-result${st.ok ? ' is-ok' : ' is-bad'}`}>
        {st.ok ? '✓ ' : '✗ '}
        {t(`settings.dataTest.result.${st.code ?? 'unknown'}`)}
        {!st.ok && st.detail && st.code === 'http' ? ` (${st.detail})` : ''}
      </span>
    )
  }
  /** Key-state badge for a data-source row. "Saved" only means the secret is
   * stored; "Verified" appears only after THIS screen's live probe passes. */
  const renderKeyBadge = (
    configured: boolean,
    tier: 'core' | 'optional',
    provider: string,
  ): React.ReactElement => {
    const st = dataTestState[provider]
    if (st?.status === 'done') {
      return st.ok ? (
        <span className="settings-badge is-ok">{t('settings.badge.verified')}</span>
      ) : (
        <span className="settings-badge is-required">{t('settings.badge.failed')}</span>
      )
    }
    if (configured) {
      return <span className="settings-badge is-pending">{t('settings.badge.saved')}</span>
    }
    return tier === 'core' ? (
      <span className="settings-badge is-recommended">{t('settings.badge.recommended')}</span>
    ) : (
      <span className="settings-badge is-optional">{t('settings.badge.optional')}</span>
    )
  }
  /** Trailing "· Get a key ↗" link appended to a data-source hint. Opens the
   * provider's signup page in the system browser (Tauri shell / window.open). */
  const renderSignupLink = (url: string): React.ReactElement => (
    <>
      {' · '}
      <a
        className="settings-hint-link"
        href={url}
        onClick={(e) => {
          e.preventDefault()
          void openExternal(url)
        }}
      >
        {t('settings.apiKey.getKey')} ↗
      </a>
    </>
  )

  return (
    <section className="settings-section" data-section="dataSources">
      <h2 className="settings-section-title">{t('settings.section.dataSources')}</h2>

      {healthError && <p className="settings-hint">{t('settings.providerStatus.unavailable')}</p>}

      <div className="settings-provider-list">
        {/* Always-on baseline: the app works with zero keys — Yahoo
        Finance covers prices, financials & news for free. */}
        <DataSourceRow
          health={healthByName.get('yfinance')}
          name={PROVIDER_DISPLAY_NAMES.yfinance}
          badge={
            <span className="settings-badge is-always">
              {t('settings.dataSources.baselineBadge')}
            </span>
          }
          hint={t('settings.dataSources.baselineHint')}
        />

        <DataSourceRow
          health={healthByName.get('fmp')}
          name={PROVIDER_DISPLAY_NAMES.fmp}
          badge={renderKeyBadge(fmpConfigured, 'core', 'fmp')}
          control={renderKeyControl({
            labelKey: 'settings.fmp.label',
            placeholderKey: 'settings.fmp.placeholder',
            configured: fmpConfigured,
            value: fmpKey,
            onChange: handleFmpKeyChange,
            clearField: 'fmp_api_key',
            testProvider: 'fmp',
          })}
          result={renderTestResult('fmp')}
          hint={
            <>
              {t('settings.fmp.hint')}
              {renderSignupLink(DATA_SOURCE_SIGNUP_URLS.fmp)}
            </>
          }
        />

        <DataSourceRow
          health={healthByName.get('finnhub')}
          name={PROVIDER_DISPLAY_NAMES.finnhub}
          badge={renderKeyBadge(finnhubConfigured, 'optional', 'finnhub')}
          control={renderKeyControl({
            labelKey: 'settings.finnhub.label',
            placeholderKey: 'settings.finnhub.placeholder',
            configured: finnhubConfigured,
            value: finnhubKey,
            onChange: handleFinnhubKeyChange,
            clearField: 'finnhub_api_key',
            testProvider: 'finnhub',
          })}
          result={renderTestResult('finnhub')}
          hint={
            <>
              {t('settings.finnhub.hint')}
              {renderSignupLink(DATA_SOURCE_SIGNUP_URLS.finnhub)}
            </>
          }
        />

        <DataSourceRow
          health={healthByName.get('adanos')}
          name={PROVIDER_DISPLAY_NAMES.adanos}
          badge={renderKeyBadge(adanosConfigured, 'optional', 'adanos')}
          control={renderKeyControl({
            labelKey: 'settings.adanos.label',
            placeholderKey: 'settings.adanos.placeholder',
            configured: adanosConfigured,
            value: adanosKey,
            onChange: handleAdanosKeyChange,
            clearField: 'adanos_api_key',
            testProvider: 'adanos',
          })}
          result={renderTestResult('adanos')}
          hint={
            <>
              {t('settings.adanos.hint')}
              {renderSignupLink(DATA_SOURCE_SIGNUP_URLS.adanos)}
            </>
          }
        />

        {/* Alpha Vantage is nested under News Aggregator, so it has no standalone
        live breaker row. The badge still reflects saved vs just-tested state. */}
        <DataSourceRow
          health={healthByName.get('alpha_vantage')}
          name={PROVIDER_DISPLAY_NAMES.alpha_vantage}
          badge={renderKeyBadge(alphaVantageConfigured, 'optional', 'alpha_vantage')}
          control={renderKeyControl({
            labelKey: 'settings.alphaVantage.label',
            placeholderKey: 'settings.alphaVantage.placeholder',
            configured: alphaVantageConfigured,
            value: alphaVantageKey,
            onChange: handleAlphaVantageKeyChange,
            clearField: 'alpha_vantage_api_key',
            testProvider: 'alpha_vantage',
          })}
          result={renderTestResult('alpha_vantage')}
          hint={
            <>
              {t('settings.alphaVantage.hint')}
              {renderSignupLink(DATA_SOURCE_SIGNUP_URLS.alphaVantage)}
            </>
          }
        />

        {/* Remaining live-feed providers with no key to configure
        (e.g. news_aggregator) — status row only. */}
        {healthEntries
          .filter((p) => !KEYED_PROVIDER_ROWS.has(p.name))
          .map((p) => (
            <DataSourceRow
              key={p.name}
              health={p}
              name={PROVIDER_DISPLAY_NAMES[p.name] ?? p.name}
            />
          ))}

        {/* SEC EDGAR identity — not a secret key (unlocks 10-K / 10-Q /
        8-K / Form 4 / 13F filings); its two-part hint runs taller
        than the key rows, so it anchors the list. */}
        <DataSourceRow
          health={healthByName.get('edgar_tools')}
          name={PROVIDER_DISPLAY_NAMES.edgar_tools}
          badge={
            secIdentityActive ? (
              <span className="settings-badge is-ok">{t('settings.badge.active')}</span>
            ) : secIdentityLocallyValid ? (
              <span className="settings-badge is-pending">{t('settings.badge.pending')}</span>
            ) : (
              <span className="settings-badge is-recommended">
                {t('settings.badge.recommended')}
              </span>
            )
          }
          control={
            <input
              className={`settings-input${secIdentityInvalidInput ? ' is-invalid' : ''}`}
              type="text"
              value={secUserAgent}
              onChange={(e) => handleSecAgentChange(e.target.value)}
              placeholder={t('settings.sec.placeholder')}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={secIdentityInvalidInput}
              aria-label={t('settings.sec.label')}
            />
          }
          hint={
            <>
              <span className={`settings-hint ${secIdentityHint.cls}`}>{secIdentityHint.text}</span>
              {secIdentityPreview && (
                <span className="settings-hint">
                  {t('settings.sec.preview')}
                  {secIdentityPreview}
                </span>
              )}
            </>
          }
        />
      </div>
    </section>
  )
}
