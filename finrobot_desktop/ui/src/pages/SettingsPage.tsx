import { useNavigate } from 'react-router-dom'
import SettingsView from '../views/SettingsView'
import { useI18n, useUiPrefs, LOCALES, type Locale } from '../i18n'

export function SettingsPage() {
  const navigate = useNavigate()
  const { t } = useI18n()
  const locale = useUiPrefs((s) => s.locale)
  const setLocale = useUiPrefs((s) => s.setLocale)

  return (
    <div style={{ height: '100%', overflowY: 'auto' }}>
      <div
        style={{
          maxWidth: '640px',
          margin: '0 auto',
          padding: 'var(--sp-8) var(--sp-6)',
        }}
      >
        <h1
          style={{
            fontSize: '1.4rem',
            fontWeight: 700,
            color: 'var(--text-primary)',
            marginBottom: 'var(--sp-6)',
          }}
        >
          {t('settings.title')}
        </h1>

        {/* Appearance / language */}
        <section
          style={{
            padding: 'var(--sp-5)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            backgroundColor: 'var(--surface)',
            marginBottom: 'var(--sp-5)',
          }}
        >
          <h2
            style={{
              fontSize: '0.95rem',
              fontWeight: 600,
              color: 'var(--text-primary)',
              marginBottom: 'var(--sp-4)',
            }}
          >
            {t('settings.section.appearance')}
          </h2>

          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 'var(--sp-3)',
            }}
          >
            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              {t('settings.language')}
            </span>
            <select
              value={locale}
              onChange={(e) => setLocale(e.target.value as Locale)}
              style={{
                padding: '6px 10px',
                fontSize: '0.85rem',
                border: '1px solid var(--border)',
                borderRadius: 4,
                background: 'var(--elevated)',
                color: 'var(--text-primary)',
                minWidth: 140,
              }}
            >
              {LOCALES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.native}
                </option>
              ))}
            </select>
          </label>
        </section>

        {/* Existing settings — model + API keys + SEC user agent */}
        <SettingsView onComplete={() => navigate('/stocks')} />
      </div>
    </div>
  )
}
