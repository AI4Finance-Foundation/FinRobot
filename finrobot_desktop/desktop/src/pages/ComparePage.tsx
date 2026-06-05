// ComparePage — side-by-side DCF comparison (route `/compare?tickers=A,B`).
// Pure read: assembles from each ticker's latest stored DCF artifact + live
// market (backend GET /api/compare). Tickers without a DCF show a "run DCF
// first" note instead of a fabricated number.

import { useSearchParams, useNavigate } from 'react-router-dom'
import { useI18n } from '../i18n'
import { formatCurrency, formatDate, formatNumber, formatPercent } from '../utils/format'
import { useCompare } from '../hooks/useCoverage'
import type { CompanyValuation } from '../api/coverage'

// A row's DCF is flagged "stale" once it is this many days old; a comparison is
// warned when its rows' DCF vintages span more than this. Mirrors the backend
// _VINTAGE_SPREAD_WARN_DAYS so the table and the CLI agree on the threshold.
export const VINTAGE_WARN_DAYS = 7
const MS_PER_DAY = 86_400_000

export function dayAge(iso: string | null, now: number): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  return Math.floor((now - t) / MS_PER_DAY)
}

/** Whole-day gap between the oldest and newest *dated* DCF in the table, or
 *  null when fewer than two rows carry a vintage (nothing to compare). */
export function vintageSpreadDays(companies: CompanyValuation[]): number | null {
  const stamps = companies
    .filter((c) => !c.error && c.dcf_as_of)
    .map((c) => Date.parse(c.dcf_as_of as string))
    .filter((t) => !Number.isNaN(t))
  if (stamps.length < 2) return null
  return Math.floor((Math.max(...stamps) - Math.min(...stamps)) / MS_PER_DAY)
}

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
  const tickers = Array.from(
    new Set(
      (params.get('tickers') ?? '')
        .split(',')
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean),
    ),
  )

  const { data, isLoading, isError } = useCompare(tickers, tickers.length >= 2)

  const companies = data?.companies ?? []
  const now = Date.now()
  const spread = vintageSpreadDays(companies)

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
        <>
          {spread !== null && spread > VINTAGE_WARN_DAYS ? (
            <div
              style={{
                maxWidth: 1000,
                marginBottom: 14,
                padding: '10px 14px',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--warning)',
                background: 'color-mix(in srgb, var(--warning) 10%, transparent)',
                color: 'var(--warning)',
                fontSize: 13,
                lineHeight: 1.5,
              }}
              role="alert"
            >
              {t('compare.vintageWarn', { days: spread })}
            </div>
          ) : null}
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
                <th style={TH}>{t('compare.dcfDate')}</th>
              </tr>
            </thead>
            <tbody>
              {companies.map((c, i) => {
                const age = dayAge(c.dcf_as_of, now)
                const stale = age !== null && age > VINTAGE_WARN_DAYS
                return (
                  <tr key={`${c.ticker}:${i}`}>
                    <td style={{ ...TD, textAlign: 'left' }}>
                      <span style={{ fontWeight: 600 }}>{c.ticker}</span>
                      {c.company_name ? (
                        <span style={{ color: 'var(--text-muted)', marginLeft: 8, fontSize: 11 }}>
                          {c.company_name}
                        </span>
                      ) : null}
                    </td>
                    {c.error ? (
                      <td colSpan={7} style={{ ...TD, textAlign: 'left', color: 'var(--warning)' }}>
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
                          {c.upside_pct === null
                            ? '—'
                            : formatPercent(c.upside_pct, locale, 1, true)}
                        </td>
                        <td style={TD}>
                          {c.wacc === null ? '—' : formatPercent(c.wacc, locale, 1)}
                        </td>
                        <td style={TD}>
                          {c.ev_ebitda === null ? '—' : `${formatNumber(c.ev_ebitda, locale, 1)}×`}
                        </td>
                        <td style={TD}>
                          {c.pe_ratio === null ? '—' : `${formatNumber(c.pe_ratio, locale, 1)}×`}
                        </td>
                        <td
                          style={{
                            ...TD,
                            color: stale ? 'var(--warning)' : 'var(--text-secondary)',
                            whiteSpace: 'nowrap',
                          }}
                          title={stale ? t('compare.staleTitle', { days: age }) : undefined}
                        >
                          {c.dcf_as_of === null ? (
                            t('compare.live')
                          ) : (
                            <>
                              {formatDate(c.dcf_as_of, locale, 'short')}
                              {stale ? (
                                <span style={{ marginLeft: 6, fontSize: 10, fontWeight: 600 }}>
                                  ⚠ {t('compare.stale')}
                                </span>
                              ) : null}
                            </>
                          )}
                        </td>
                      </>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </>
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
