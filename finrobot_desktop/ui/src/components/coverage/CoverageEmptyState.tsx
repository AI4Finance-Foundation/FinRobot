// CoverageEmptyState — the Coverage Starter shown when the user has no groups
// yet (Coverage plan State A). Honest empty: no fake quotes/research/hit-rate,
// just a 3-step path + hot-ticker quick-add chips (chips are an ADD entry, not
// a claim those tickers are covered).

import { useState } from 'react'
import { useI18n } from '../../i18n'

const HOT_TICKERS = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMD']

interface Props {
  onCreate: (name: string, tickers: string[]) => void
  busy: boolean
}

export function CoverageEmptyState({ onCreate, busy }: Props): React.ReactElement {
  const { t } = useI18n()
  const [picked, setPicked] = useState<string[]>([])
  const [typed, setTyped] = useState('')

  function toggle(ticker: string) {
    setPicked((p) => (p.includes(ticker) ? p.filter((x) => x !== ticker) : [...p, ticker]))
  }

  function start() {
    const fromInput = typed
      .split(/[\s,]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean)
    const tickers = [...new Set([...picked, ...fromInput])]
    onCreate(t('coverage.starter.defaultName'), tickers)
  }

  return (
    <div
      data-testid="coverage-empty"
      style={{
        maxWidth: 560,
        margin: '64px auto',
        textAlign: 'center',
        display: 'flex',
        flexDirection: 'column',
        gap: 20,
      }}
    >
      <div>
        <h1
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 28,
            letterSpacing: '0.04em',
            color: 'var(--text-primary)',
            margin: 0,
          }}
        >
          Coverage Desk
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: 14, marginTop: 8 }}>
          {t('coverage.starter.subtitle')}
        </p>
      </div>

      <input
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
        placeholder={t('coverage.starter.addPlaceholder')}
        style={{
          width: '100%',
          padding: '10px 14px',
          background: 'var(--bg-card)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          color: 'var(--text-primary)',
          fontFamily: 'var(--font-mono)',
          fontSize: 14,
        }}
      />

      <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap' }}>
        {HOT_TICKERS.map((tk) => {
          const on = picked.includes(tk)
          return (
            <button
              key={tk}
              type="button"
              onClick={() => toggle(tk)}
              style={{
                padding: '5px 14px',
                borderRadius: 999,
                fontFamily: 'var(--font-mono)',
                fontSize: 13,
                cursor: 'pointer',
                background: on ? 'var(--primary)' : 'transparent',
                color: on ? '#fff' : 'var(--text-secondary)',
                border: `1px solid ${on ? 'var(--primary)' : 'var(--border-soft)'}`,
              }}
            >
              {tk}
            </button>
          )
        })}
      </div>

      <button
        type="button"
        onClick={start}
        disabled={busy || (picked.length === 0 && !typed.trim())}
        style={{
          alignSelf: 'center',
          padding: '10px 28px',
          borderRadius: 'var(--radius-md)',
          background: 'linear-gradient(135deg, var(--primary), var(--secondary))',
          color: '#fff',
          border: 'none',
          fontFamily: 'var(--font-display)',
          fontSize: 13,
          letterSpacing: '0.08em',
          cursor: busy ? 'wait' : 'pointer',
          opacity: picked.length === 0 && !typed.trim() ? 0.5 : 1,
        }}
      >
        {t('coverage.starter.cta')}
      </button>

      <ol
        style={{
          textAlign: 'left',
          color: 'var(--text-muted)',
          fontSize: 12,
          lineHeight: 1.8,
          maxWidth: 360,
          margin: '0 auto',
        }}
      >
        <li>{t('coverage.starter.step1')}</li>
        <li>{t('coverage.starter.step2')}</li>
        <li>{t('coverage.starter.step3')}</li>
      </ol>
    </div>
  )
}
