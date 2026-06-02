// ComparePage — side-by-side DCF comparison (route `/compare?tickers=A,B`).
// Pure read: assembles from each ticker's latest stored DCF artifact + live
// market (backend GET /api/compare). Tickers without a DCF show a "run DCF
// first" note instead of a fabricated number.

import { useSearchParams, useNavigate } from 'react-router-dom'
import { useI18n } from '../i18n'
import { formatCurrency, formatNumber, formatPercent } from '../utils/format'
import { useCompare } from '../hooks/useCoverage'

const TH: React.CSSProperties = {
  textAlign: 'right',
  padding: '10px 14px',
  fontSize: 10,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  color: 'var(--text-muted)',
  borderBottom: '1px solid var(--border-soft)',
}
const TD: React.CSSProperties = {
  textAlign: 'right',
  padding: '11px 14px',
  fontFamily: 'var(--font-mono)',
  fontSize: 14,
  color: 'var(--text-primary)',
  borderTop: '1px solid var(--border-faint)',
}

export function ComparePage(): React.ReactElement {
  const { t, locale } = useI18n()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const tickers = (params.get('tickers') ?? '')
    .split(',')
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean)

  const { data, isLoading, isError } = useCompare(tickers, tickers.length >= 2)

  return (
    <div style={{ padding: '24px 28px', height: '100%', overflow: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <button
          type="button"
          onClick={() => navigate('/coverage')}
          style={{
            background: 'transparent',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--text-secondary)',
            padding: '5px 12px',
            cursor: 'pointer',
            fontSize: 13,
          }}
        >
          ← {t('compare.back')}
        </button>
        <h1
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 20,
            letterSpacing: '0.06em',
            color: 'var(--text-primary)',
            margin: 0,
          }}
        >
          {t('compare.title')}
        </h1>
      </div>

      {tickers.length < 2 ? (
        <Note text={t('compare.needTwo')} />
      ) : isLoading ? (
        <Note text={t('compare.loading')} />
      ) : isError ? (
        <Note text={t('compare.error')} />
      ) : (
        <table style={{ borderCollapse: 'collapse', width: '100%', maxWidth: 1000 }}>
          <thead>
            <tr>
              <th style={{ ...TH, textAlign: 'left' }}>{t('coverage.col.ticker')}</th>
              <th style={TH}>{t('coverage.col.price')}</th>
              <th style={TH}>{t('compare.implied')}</th>
              <th style={TH}>{t('coverage.col.upside')}</th>
              <th style={TH}>WACC</th>
              <th style={TH}>EV/EBITDA</th>
              <th style={TH}>P/E</th>
            </tr>
          </thead>
          <tbody>
            {(data?.companies ?? []).map((c) => (
              <tr key={c.ticker}>
                <td style={{ ...TD, textAlign: 'left' }}>
                  <span style={{ fontWeight: 600 }}>{c.ticker}</span>
                  {c.company_name ? (
                    <span style={{ color: 'var(--text-muted)', marginLeft: 8, fontSize: 11 }}>
                      {c.company_name}
                    </span>
                  ) : null}
                </td>
                {c.error ? (
                  <td colSpan={6} style={{ ...TD, textAlign: 'left', color: 'var(--warning)' }}>
                    {c.error}
                  </td>
                ) : (
                  <>
                    <td style={TD}>{formatCurrency(c.current_price, 'USD', locale)}</td>
                    <td style={TD}>{formatCurrency(c.implied_price, 'USD', locale)}</td>
                    <td
                      style={{
                        ...TD,
                        color:
                          c.upside_pct === null
                            ? 'var(--text-secondary)'
                            : c.upside_pct >= 0
                              ? 'var(--success)'
                              : 'var(--danger)',
                      }}
                    >
                      {c.upside_pct === null ? '—' : formatPercent(c.upside_pct, locale, 1, true)}
                    </td>
                    <td style={TD}>{c.wacc === null ? '—' : formatPercent(c.wacc, locale, 1)}</td>
                    <td style={TD}>
                      {c.ev_ebitda === null ? '—' : `${formatNumber(c.ev_ebitda, locale, 1)}×`}
                    </td>
                    <td style={TD}>
                      {c.pe_ratio === null ? '—' : `${formatNumber(c.pe_ratio, locale, 1)}×`}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function Note({ text }: { text: string }): React.ReactElement {
  return (
    <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
      {text}
    </div>
  )
}
