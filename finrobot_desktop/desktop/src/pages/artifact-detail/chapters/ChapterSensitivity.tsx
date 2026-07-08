import SensitivityHeatmap from '../../../components/charts/SensitivityHeatmap'
import { Chapter, SubChapter, tableStyle, TableScroll } from './ChapterBase'
import type { DcfShape } from './types'
import { useI18n } from '../../../i18n'
import { formatCurrency, formatCurrencyCompact } from '../../../utils/format'

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

/** Index of the axis value closest to the DCF's own base value. The backend
 * grid is built AROUND the base case but Gordon-floor pruning can DROP the
 * upper terminal-growth cells (KO: tg axis [2.0, 2.5, 3.0] with base 3.0 in
 * the LAST slot), so "the grid centre" is not where the base lives — the
 * notes claimed "at base terminal growth" while reading the 2.5% column
 * (external audit 2026-07-07). Fall back to the centre only when the base
 * value is unavailable. */
function nearestIndex(values: number[], base: number | undefined): number {
  if (base === undefined || !Number.isFinite(base)) return Math.floor(values.length / 2)
  let best = 0
  for (let i = 1; i < values.length; i++) {
    if (Math.abs(values[i] - base) < Math.abs(values[best] - base)) best = i
  }
  return best
}

// Derive how far implied price moves along each axis of the ACTUAL grid, so the
// "notes" describe this DCF rather than a hardcoded boilerplate paragraph. Each
// axis is held at the index nearest the BASE assumption (not the grid centre —
// see nearestIndex) while the spread is read along the other.
function computeAxisSwing(
  table: Record<string, unknown> | null | undefined,
  baseWacc: number | undefined,
  baseTg: number | undefined,
): AxisSwing | null {
  if (!table) return null
  const t = table as SensitivityTableShape
  const waccs = Array.isArray(t.wacc_values) ? t.wacc_values : []
  const tgs = Array.isArray(t.tg_values) ? t.tg_values : []
  const prices = Array.isArray(t.implied_prices) ? t.implied_prices : []
  if (waccs.length < 2 || tgs.length < 2 || prices.length === 0) return null

  const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0
  const baseWaccRow = nearestIndex(waccs, baseWacc)
  const baseTgCol = nearestIndex(tgs, baseTg)

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
  // The model-vs-current reconciliation renders the assumption_provenance strings
  // in its "Model uses" column. The standalone DCF tool page (CompactArtifactViewer)
  // ALSO renders a full ProvenanceList of the same strings, so it passes false to
  // avoid double-listing (the 同源双列 the frontend contract forbids); the research
  // report has no competing trail, so it keeps the default true. The margin swing
  // note is unaffected — it duplicates nothing.
  showReconciliation = true,
}: ChapterSensitivityProps & { showReconciliation?: boolean }): React.ReactElement {
  const { t, locale } = useI18n()
  const fmtPrice = (v: number): string => formatCurrency(v, quoteCurrency, locale, v >= 100 ? 0 : 2)
  const table = dcf?.sensitivity_table ?? null
  const inputs = dcf?.inputs
  const heatmapRows = flattenSensitivity(table)
  const swing = computeAxisSwing(table, dcf?.wacc, inputs?.terminal_growth_rate)
  // ±2pp EBITDA-margin swing note: render only when BOTH ends resolved to a
  // finite price (a half-range would read as a broken figure). The backend
  // computed it; the client never re-derives a DCF.
  const marginSwing = readMarginSwing(dcf?.margin_swing)

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
          {/* Gordon reconstruction disclosure: the perpetuity BASE is the
              normalized steady-state FCF, not projected_fcf[-1] — without
              this line a reader rebuilding TV from the printed FCF path
              lands ~2x off and reads it as an error (KO audit 2026-07-07). */}
          {typeof dcf?.terminal_fcf === 'number' && dcf.terminal_fcf > 0 && (
            <>
              {' '}
              {t('chapter.sensitivity.assumptions.terminalBase')}{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {formatCurrencyCompact(dcf.terminal_fcf, quoteCurrency, locale)}
              </strong>
              {t('chapter.sensitivity.assumptions.terminalBaseNote')}
            </>
          )}
        </p>
      </SubChapter>

      {showReconciliation && (
        <AssumptionReconciliation
          provenance={inputs?.assumption_provenance}
          actuals={dcf?.assumption_current_actuals}
          nwcClamped={inputs?.nwc_clamped ?? false}
        />
      )}

      <SubChapter heading={t('chapter.sensitivity.subheading.matrix')}>
        {heatmapRows.length > 0 ? (
          <SensitivityHeatmap data={heatmapRows} title={t('chapter.sensitivity.matrix.title')} />
        ) : (
          <p style={mutedNote}>{t('chapter.sensitivity.empty')}</p>
        )}
      </SubChapter>

      {(swing || marginSwing) && (
        <SubChapter heading={t('chapter.sensitivity.subheading.notes')}>
          {swing && (
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
          )}
          {marginSwing && (
            <p
              style={{
                fontSize: 13,
                lineHeight: 1.7,
                color: 'var(--text-secondary)',
                marginTop: swing ? 8 : 0,
              }}
            >
              {t('chapter.sensitivity.notes.margin')}{' '}
              <strong style={{ color: 'var(--text-primary)' }}>
                {fmtPrice(marginSwing[0])}–{fmtPrice(marginSwing[1])}
              </strong>
              .
            </p>
          )}
        </SubChapter>
      )}
    </>
  )
}

function meanArray(arr: number[]): number {
  if (arr.length === 0) return 0
  return arr.reduce((a, b) => a + b, 0) / arr.length
}

/** Narrow the backend margin_swing ([low, high], either end nullable) to a
 * finite [low, high] pair — the note only renders a clean range when BOTH ends
 * resolved. Null otherwise (one/both ends degraded, or field absent). */
function readMarginSwing(
  raw: [number | null, number | null] | null | undefined,
): [number, number] | null {
  if (!Array.isArray(raw)) return null
  const [lo, hi] = raw
  if (typeof lo !== 'number' || !Number.isFinite(lo)) return null
  if (typeof hi !== 'number' || !Number.isFinite(hi)) return null
  return [lo, hi]
}

// The four DCF explicit-period drivers, in report order. `provKey` reads the
// verbatim "Model uses" prose from DCFInputs.assumption_provenance; `actualKey`
// reads the latest-year "Current" figure from DcfShape.assumption_current_actuals
// (the growth keys differ — provenance is keyed on the input field name, the
// actuals on the driver). `signed` prints a leading + on positive growth / ΔNWC
// (their sign is load-bearing); `nwc` carries the clamp ⚠.
const RECON_ROWS: {
  labelKey: string
  provKey: string
  actualKey: string
  signed: boolean
  nwc?: boolean
}[] = [
  {
    labelKey: 'chapter.sensitivity.reconciliation.driver.growth',
    provKey: 'revenue_growth_rates',
    actualKey: 'revenue_growth',
    signed: true,
  },
  {
    labelKey: 'chapter.sensitivity.reconciliation.driver.margin',
    provKey: 'ebitda_margin',
    actualKey: 'ebitda_margin',
    signed: false,
  },
  {
    labelKey: 'chapter.sensitivity.reconciliation.driver.capex',
    provKey: 'capex_pct_revenue',
    actualKey: 'capex_pct_revenue',
    signed: false,
  },
  {
    labelKey: 'chapter.sensitivity.reconciliation.driver.nwc',
    provKey: 'nwc_pct_revenue',
    actualKey: 'nwc_pct_revenue',
    signed: true,
    nwc: true,
  },
]

/** The "model vs current" reconciliation the external audit asked for: the DCF's
 * trailing-median explicit-period drivers beside their latest actual, so a reader
 * sees where the smoothed assumptions diverge from recent reality. The "Model
 * uses" column renders the backend provenance prose VERBATIM (never reformatted —
 * frontend contract); the "Current" column is the backend-computed latest actual
 * (never re-derived here). Renders nothing when no provenance exists (legacy /
 * degraded artifacts). */
function AssumptionReconciliation({
  provenance,
  actuals,
  nwcClamped,
}: {
  provenance: Record<string, string> | undefined
  actuals: Record<string, number | null> | null | undefined
  nwcClamped: boolean
}): React.ReactElement | null {
  const { t } = useI18n()
  if (!provenance) return null
  const rows = RECON_ROWS.filter((r) => provenance[r.provKey])
  if (rows.length === 0) return null

  const fmtActual = (v: number | null | undefined, signed: boolean): string => {
    if (v === null || v === undefined || !Number.isFinite(v)) {
      return t('chapter.sensitivity.reconciliation.na')
    }
    const pct = v * 100
    const body = `${pct.toFixed(1)}%`
    return signed && pct > 0 ? `+${body}` : body
  }

  return (
    <SubChapter heading={t('chapter.sensitivity.reconciliation.title')}>
      <TableScroll>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={reconThStyle}>{t('chapter.sensitivity.reconciliation.driver')}</th>
              <th style={reconThStyle}>{t('chapter.sensitivity.reconciliation.modelUses')}</th>
              <th style={{ ...reconThStyle, textAlign: 'right' }}>
                {t('chapter.sensitivity.reconciliation.currentActual')}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.provKey}>
                <td style={{ ...reconTdStyle, color: 'var(--text-primary)', fontWeight: 500 }}>
                  {t(r.labelKey)}
                </td>
                <td style={reconTdStyle}>
                  {provenance[r.provKey]}
                  {r.nwc && nwcClamped && (
                    <span
                      title={t('chapter.sensitivity.reconciliation.clampedTooltip')}
                      style={{ color: 'var(--warning)', marginLeft: 6 }}
                    >
                      ⚠
                    </span>
                  )}
                </td>
                <td
                  style={{
                    ...reconTdStyle,
                    textAlign: 'right',
                    color: 'var(--text-primary)',
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {fmtActual(actuals?.[r.actualKey], r.signed)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
      <p
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-dim)',
          marginTop: 8,
          lineHeight: 1.6,
        }}
      >
        {t('chapter.sensitivity.reconciliation.footnote')}
      </p>
    </SubChapter>
  )
}

const reconThStyle: React.CSSProperties = {
  padding: '10px 14px',
  textAlign: 'left',
  fontWeight: 500,
  fontSize: 10.5,
  color: 'var(--secondary)',
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  borderBottom: '1px solid var(--border-soft)',
}

const reconTdStyle: React.CSSProperties = {
  padding: '9px 14px',
  borderBottom: '1px solid var(--border-faint)',
  color: 'var(--text-secondary)',
  verticalAlign: 'top',
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
