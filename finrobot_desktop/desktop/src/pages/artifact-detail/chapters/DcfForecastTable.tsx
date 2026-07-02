// The 10-year DCF forecast table (projected revenue / EBITDA / FCF). Extracted
// from ChapterFinancialAnalysis so the full report's Financial Analysis chapter
// AND the standalone DCF tool page (CompactArtifactViewer) render the SAME table —
// one source of truth, no drift. Renders EVERY projected year (no silent slice):
// the flat K-V dump it replaces truncated arrays at 8 items, violating the
// "页面永不隐藏数字" contract on the 10-year projection.

import { useI18n } from '../../../i18n'
import { TermTip } from '../../../components/TermTip'
import { formatCurrencyCompact } from '../../../utils/format'
import { SubChapter, TableScroll, tableStyle } from './ChapterBase'
import type { DcfShape } from './types'

export function DcfForecastTable({
  dcf,
  // Income-statement absolutes (revenue / EBITDA / FCF) → reporting currency.
  reportingCurrency,
}: {
  dcf: DcfShape | null
  reportingCurrency: string
}): React.ReactElement | null {
  const { t, locale } = useI18n()
  const fmtMoney = (v: number): string => formatCurrencyCompact(v, reportingCurrency, locale)
  const revenue = dcf?.projected_revenue
  if (!revenue || revenue.length === 0) return null

  return (
    <SubChapter heading={t('chapter.financial.subheading.dcfForecast')}>
      <TableScroll>
        <table style={tableStyle}>
          <thead style={{ background: 'var(--bg-elevated)' }}>
            <tr>
              <th style={thStyle}>{t('chapter.financial.table.unit')}</th>
              {revenue.map((_, i) => (
                <th key={`year-${i}`} style={thStyle}>
                  {t('chapter.financial.table.yearPlus', { n: i + 1 })}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                {t('chapter.financial.table.revenue')}
              </td>
              {revenue.map((v, i) => (
                <td key={`rev-${i}`} style={{ ...tdStyle, textAlign: 'right' }}>
                  {fmtMoney(v)}
                </td>
              ))}
            </tr>
            {dcf?.projected_ebitda && dcf.projected_ebitda.length > 0 && (
              <tr>
                <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                  EBITDA
                </td>
                {dcf.projected_ebitda.map((v, i) => (
                  <td key={`ebitda-${i}`} style={{ ...tdStyle, textAlign: 'right' }}>
                    {fmtMoney(v)}
                  </td>
                ))}
              </tr>
            )}
            {dcf?.projected_fcf && dcf.projected_fcf.length > 0 && (
              <tr>
                <td style={{ ...tdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                  <TermTip term="FCF">{t('chapter.financial.table.fcf')}</TermTip>
                </td>
                {dcf.projected_fcf.map((v, i) => (
                  <td
                    key={`fcf-${i}`}
                    style={{ ...tdStyle, textAlign: 'right', color: 'var(--accent-cyan)' }}
                  >
                    {fmtMoney(v)}
                  </td>
                ))}
              </tr>
            )}
          </tbody>
        </table>
      </TableScroll>
      <p
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--text-dim)',
          marginTop: 6,
          letterSpacing: '0.04em',
        }}
      >
        {t('chapter.financial.table.source')}
      </p>
    </SubChapter>
  )
}

const thStyle: React.CSSProperties = {
  padding: '10px 14px',
  textAlign: 'left',
  fontWeight: 500,
  fontSize: 10.5,
  color: 'var(--secondary)',
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  borderBottom: '1px solid var(--border-soft)',
}
const tdStyle: React.CSSProperties = {
  padding: '9px 14px',
  borderBottom: '1px solid var(--border-faint)',
  color: 'var(--text-secondary)',
  fontVariantNumeric: 'tabular-nums',
}
