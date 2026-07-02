import SensitivityHeatmap from '../../../components/charts/SensitivityHeatmap'
import { Chapter, SubChapter } from './ChapterBase'
import type { DcfShape } from './types'
import { useI18n } from '../../../i18n'
import { formatCurrency } from '../../../utils/format'

interface SensitivityTableShape {
  wacc_values?: number[]
  tg_values?: number[]
  implied_prices?: number[][]
}

function flattenSensitivity(
  table: Record<string, unknown> | null | undefined,
): { wacc: number; tg: number; implied_price: number }[] {
  if (!table) return []
  const t = table as SensitivityTableShape
  const waccs = Array.isArray(t.wacc_values) ? t.wacc_values : []
  const tgs = Array.isArray(t.tg_values) ? t.tg_values : []
  const prices = Array.isArray(t.implied_prices) ? t.implied_prices : []
  const rows: { wacc: number; tg: number; implied_price: number }[] = []
  for (let i = 0; i < waccs.length; i++) {
    const row = prices[i]
    if (!Array.isArray(row)) continue
    for (let j = 0; j < tgs.length; j++) {
      const price = row[j]
      if (typeof price !== 'number' || !Number.isFinite(price)) continue
      rows.push({ wacc: waccs[i], tg: tgs[j], implied_price: price })
    }
  }
  return rows
}

interface AxisSwing {
  waccLow: number
  waccHigh: number
  waccSwing: number
  tgLow: number
  tgHigh: number
  tgSwing: number
  driver: 'wacc' | 'tg'
}

// Derive how far implied price moves along each axis of the ACTUAL grid, so the
// "notes" describe this DCF rather than a hardcoded boilerplate paragraph. The
// base case sits at the grid centre, so we hold one axis at its middle index
// and read the spread along the other.
function computeAxisSwing(table: Record<string, unknown> | null | undefined): AxisSwing | null {
  if (!table) return null
  const t = table as SensitivityTableShape
  const waccs = Array.isArray(t.wacc_values) ? t.wacc_values : []
  const tgs = Array.isArray(t.tg_values) ? t.tg_values : []
  const prices = Array.isArray(t.implied_prices) ? t.implied_prices : []
  if (waccs.length < 2 || tgs.length < 2 || prices.length === 0) return null

  const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0
  const baseWaccRow = Math.floor(waccs.length / 2)
  const baseTgCol = Math.floor(tgs.length / 2)

  // Vary WACC at base terminal growth = the base-TG column down all rows.
  const waccCol = prices
    .map((row) => (Array.isArray(row) ? row[baseTgCol] : undefined))
    .filter(finite)
  // Vary terminal growth at base WACC = the base-WACC row.
  const tgRow = (Array.isArray(prices[baseWaccRow]) ? prices[baseWaccRow] : []).filter(finite)
  if (waccCol.length < 2 || tgRow.length < 2) return null

  const waccLow = Math.min(...waccCol)
  const waccHigh = Math.max(...waccCol)
  const tgLow = Math.min(...tgRow)
  const tgHigh = Math.max(...tgRow)
  const waccSwing = waccHigh - waccLow
  const tgSwing = tgHigh - tgLow
  return {
    waccLow,
    waccHigh,
    waccSwing,
    tgLow,
    tgHigh,
    tgSwing,
    driver: waccSwing >= tgSwing ? 'wacc' : 'tg',
  }
}

interface ChapterSensitivityProps {
  dcf: DcfShape | null
  financialSector: boolean
  quoteCurrency: string
}

export function ChapterSensitivity(props: ChapterSensitivityProps): React.ReactElement {
  return (
    <Chapter id="sensitivity">
      <SensitivityBody {...props} />
    </Chapter>
  )
}

/** The WACC × terminal-growth sensitivity content WITHOUT the numbered <Chapter>
 * chrome, so the standalone DCF tool page reuses the exact same assumptions lead +
 * heatmap + swing notes under its own section header. */
export function SensitivityBody({
  dcf,
  // True for a balance-sheet financial (bank / insurer): there is no FCFF-DCF, so a
  // WACC × terminal-growth sensitivity grid is a category error — show why, not "re-run".
  financialSector,
  // Sensitivity-grid implied prices are per-share → quote currency (BUG-030).
  quoteCurrency,
}: ChapterSensitivityProps): React.ReactElement {
  const { t, locale } = useI18n()
  const fmtPrice = (v: number): string => formatCurrency(v, quoteCurrency, locale, v >= 100 ? 0 : 2)
  const table = dcf?.sensitivity_table ?? null
  const inputs = dcf?.inputs
  const heatmapRows = flattenSensitivity(table)
  const swing = computeAxisSwing(table)

  // A balance-sheet financial has no DCF at all — the whole sensitivity chapter (which
  // sweeps WACC × terminal growth of the FCFF-DCF) does not apply. Lead with the reason
  // instead of an empty grid + a content-free assumptions heading.
  if (financialSector) {
    return <p style={mutedNote}>{t('chapter.cashflowMethods.notApplicableForFinancials')}</p>
  }

  return (
    <>
      <SubChapter heading={t('chapter.sensitivity.subheading.assumptions')}>
        <p style={{ fontSize: 13, lineHeight: 1.7, color: 'var(--text-secondary)' }}>
          {t('chapter.sensitivity.assumptions.lead')}
          {inputs?.revenue_growth_rates && inputs.revenue_growth_rates.length > 0 && (
            <>
              {' '}
              {t('chapter.sensitivity.assumptions.revenueCagr')}{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {(meanArray(inputs.revenue_growth_rates) * 100).toFixed(1)}%
              </strong>
              ,
            </>
          )}
          {inputs?.ebitda_margin !== undefined && (
            <>
              {' '}
              {t('chapter.sensitivity.assumptions.ebitdaMargin')}{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {(inputs.ebitda_margin * 100).toFixed(1)}%
              </strong>
              ,
            </>
          )}
          {dcf?.wacc !== undefined && (
            <>
              {' '}
              WACC{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {(dcf.wacc * 100).toFixed(2)}%
              </strong>
              ,
            </>
          )}
          {inputs?.terminal_growth_rate !== undefined && (
            <>
              {' '}
              {t('chapter.sensitivity.assumptions.terminalGrowth')}{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {(inputs.terminal_growth_rate * 100).toFixed(2)}%
              </strong>
              .
            </>
          )}
        </p>
      </SubChapter>

      <SubChapter heading={t('chapter.sensitivity.subheading.matrix')}>
        {heatmapRows.length > 0 ? (
          <SensitivityHeatmap data={heatmapRows} title={t('chapter.sensitivity.matrix.title')} />
        ) : (
          <p style={mutedNote}>{t('chapter.sensitivity.empty')}</p>
        )}
      </SubChapter>

      {swing && (
        <SubChapter heading={t('chapter.sensitivity.subheading.notes')}>
          <p style={{ fontSize: 13, lineHeight: 1.7, color: 'var(--text-secondary)' }}>
            {t('chapter.sensitivity.notes.wacc')}{' '}
            <strong style={{ color: 'var(--text-primary)' }}>
              {fmtPrice(swing.waccLow)}–{fmtPrice(swing.waccHigh)}
            </strong>{' '}
            (Δ{fmtPrice(swing.waccSwing)}). {t('chapter.sensitivity.notes.tg')}{' '}
            <strong style={{ color: 'var(--text-primary)' }}>
              {fmtPrice(swing.tgLow)}–{fmtPrice(swing.tgHigh)}
            </strong>{' '}
            (Δ{fmtPrice(swing.tgSwing)}).{' '}
            {t('chapter.sensitivity.notes.mostSensitive', {
              driver:
                swing.driver === 'wacc'
                  ? t('chapter.sensitivity.driver.wacc')
                  : t('chapter.sensitivity.driver.tg'),
            })}
          </p>
        </SubChapter>
      )}
    </>
  )
}

function meanArray(arr: number[]): number {
  if (arr.length === 0) return 0
  return arr.reduce((a, b) => a + b, 0) / arr.length
}

const mutedNote: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '14px 18px',
  background: 'var(--bg-card-50)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
  lineHeight: 1.6,
}
