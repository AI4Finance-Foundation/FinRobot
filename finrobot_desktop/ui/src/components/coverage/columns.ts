// Single source of truth for the Coverage Table's hideable data columns —
// shared by the table (which gates each th/td on visibility) and the column
// menu (which lists them as toggles). Ticker / select / action are structural
// and never hideable, so they're not here.

export interface CoverageColumn {
  /** Stable visibility id (also the row field for data columns). */
  key: string
  /** i18n message id for the header label, or a literal for symbol columns. */
  i18nKey?: string
  label?: string
}

export const COVERAGE_COLUMNS: CoverageColumn[] = [
  { key: 'price', i18nKey: 'coverage.col.price' },
  { key: 'change_pct_1d', label: '1D' },
  { key: 'market_cap', i18nKey: 'coverage.col.mcap' },
  { key: 'revenue_ttm', i18nKey: 'coverage.col.revttm' },
  { key: 'ev_ebitda', label: 'EV/EBITDA' },
  { key: 'pe', label: 'P/E' },
  { key: 'verdict', i18nKey: 'coverage.col.verdict' },
  { key: 'upside', i18nKey: 'coverage.col.upside' },
  { key: 'signal', i18nKey: 'coverage.col.signal' },
  { key: 'runs', i18nKey: 'coverage.col.runs' },
  { key: 'status', i18nKey: 'coverage.col.status' },
]

export function columnLabel(col: CoverageColumn, t: (id: string) => string): string {
  return col.i18nKey ? t(col.i18nKey) : (col.label ?? col.key)
}
