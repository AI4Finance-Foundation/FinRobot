import type {
  DCFResult,
  SensitivityResult,
  CompsResult,
  HistoricalMetrics,
  QuarterlyData,
  EarningsSurprise,
} from '../stores/appStore'

/**
 * Convert backend DcfSensitivityResult grid to the flat array format
 * that SensitivityHeatmap expects.
 */
export function sensitivityGridToHeatmapRows(
  result: SensitivityResult,
): Array<{ wacc: number; tg: number; implied_price: number | null }> {
  const rows: Array<{ wacc: number; tg: number; implied_price: number | null }> = []
  for (let i = 0; i < result.wacc_values.length; i++) {
    for (let j = 0; j < result.tg_values.length; j++) {
      rows.push({
        wacc: result.wacc_values[i],
        tg: result.tg_values[j],
        implied_price: result.implied_prices[i][j],
      })
    }
  }
  return rows
}

/**
 * Build Revenue & EBITDA bar chart data from DCF projections.
 * Year 0 = base year (actual), Years 1..N = forecast.
 */
export function dcfResultToRevenueEbitdaData(
  result: DCFResult,
): Array<Record<string, number | string | boolean | null>> {
  const currentYear = new Date().getFullYear()
  const rows: Array<Record<string, number | string | boolean | null>> = []

  // Base year (actual)
  rows.push({
    year: String(currentYear),
    revenue: result.inputs.revenue_base,
    ebitda: result.inputs.revenue_base * result.inputs.ebitda_margin,
    is_forecast: false,
  })

  // Projected years
  for (let i = 0; i < result.projected_revenue.length; i++) {
    rows.push({
      year: `${currentYear + 1 + i}E`,
      revenue: result.projected_revenue[i],
      ebitda: result.projected_ebitda[i],
      is_forecast: true,
    })
  }

  return rows
}

/**
 * Build margin trend data from DCF projections.
 *
 * EBITDA margin is taken straight from the projection. The `operating_margin`
 * series is the DERIVED EBIT margin (EBITDA margin − D&A%), since EBIT =
 * EBITDA − D&A; the DCF result carries no GAAP operating-income figure for
 * future years, so this is an assumption-driven approximation, not a reported
 * number. When `da_pct_revenue` is unknown we emit `null` rather than 0 —
 * defaulting D&A to zero would render operating_margin == ebitda_margin and
 * falsely imply the company has no depreciation drag.
 */
export function dcfResultToMarginData(
  result: DCFResult,
): Array<Record<string, number | string | boolean | null>> {
  const currentYear = new Date().getFullYear()
  const rows: Array<Record<string, number | string | boolean | null>> = []

  // null (not 0) when D&A% is unknown — see docstring.
  const daPct =
    result.inputs.da_pct_revenue != null && result.inputs.da_pct_revenue > 0
      ? result.inputs.da_pct_revenue
      : null
  const ebitMargin = (ebitdaMargin: number): number | null =>
    daPct != null ? ebitdaMargin - daPct : null

  // Base year
  const baseEbitdaMargin = result.inputs.ebitda_margin
  rows.push({
    year: String(currentYear),
    ebitda_margin: baseEbitdaMargin,
    operating_margin: ebitMargin(baseEbitdaMargin),
    is_forecast: false,
  })

  // Projected years
  for (let i = 0; i < result.projected_revenue.length; i++) {
    const rev = result.projected_revenue[i]
    const ebitda = result.projected_ebitda[i]
    const ebitdaMargin = rev > 0 ? ebitda / rev : 0
    rows.push({
      year: `${currentYear + 1 + i}E`,
      ebitda_margin: ebitdaMargin,
      operating_margin: ebitMargin(ebitdaMargin),
      is_forecast: true,
    })
  }

  return rows
}

/**
 * Convert CompsResult into PeerComparisonChart format.
 * Target row is flagged with is_target: true.
 */
export function compsResultToPeerChartData(
  result: CompsResult,
): Array<Record<string, number | string | boolean | null>> {
  const all = [result.target, ...result.peers]
  return all.map((c) => ({
    ticker: c.ticker,
    ev_ebitda: c.ev_ebitda,
    pe_ratio: c.pe_ratio,
    is_target: c.ticker === result.target.ticker,
  }))
}

/**
 * Convert DCFResult into the waterfall data format for WaterfallChart.
 * Each entry has { label, value, is_total }.
 */
export function dcfResultToWaterfallData(
  result: DCFResult,
): Array<Record<string, number | string | boolean | null>> {
  return [
    { label: 'FCF 现值', value: result.pv_fcf_total, is_total: false },
    { label: '终值现值', value: result.pv_terminal, is_total: false },
    { label: '企业价值', value: result.enterprise_value, is_total: true },
    {
      label: '减：净债务',
      value: -(result.enterprise_value - result.equity_value),
      is_total: false,
    },
    { label: '股权价值', value: result.equity_value, is_total: true },
  ]
}

/**
 * Convert CompsResult into CompanyRadarChart format.
 * Each dimension is normalised so that the larger of (company, peer median) = 100,
 * giving both the company and benchmark shapes that are easy to compare visually.
 */
export function compsResultToRadarData(
  result: CompsResult,
): Array<Record<string, number | string | boolean | null>> {
  const t = result.target

  // Compute peer medians for margin dimensions (not in CompsResult directly)
  const medianOf = (values: number[]): number | null => {
    const valid = values.filter((v) => v != null && isFinite(v))
    if (valid.length === 0) return null
    const sorted = [...valid].sort((a, b) => a - b)
    const mid = Math.floor(sorted.length / 2)
    return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid]
  }

  const peerGrossMedian = medianOf(result.peers.map((p) => p.gross_margin))
  const peerOpMedian = medianOf(result.peers.map((p) => p.operating_margin))

  const dims: { label: string; company: number | null; median: number | null }[] = [
    { label: 'P/E', company: t.pe_ratio, median: result.median_pe },
    { label: 'EV/EBITDA', company: t.ev_ebitda, median: result.median_ev_ebitda },
    { label: 'EV/营收', company: t.ev_revenue, median: result.median_ev_revenue },
    { label: '毛利率', company: t.gross_margin, median: peerGrossMedian },
    { label: '营业利润率', company: t.operating_margin, median: peerOpMedian },
  ]

  return dims
    .filter(
      (d) =>
        d.company != null &&
        d.median != null &&
        isFinite(d.company) &&
        isFinite(d.median) &&
        Math.max(Math.abs(d.company), Math.abs(d.median)) > 0,
    )
    .map((d) => {
      const company = d.company as number
      const median = d.median as number
      const scale = Math.max(Math.abs(company), Math.abs(median))
      return {
        dimension: d.label,
        value: Math.round((company / scale) * 100),
        benchmark: Math.round((median / scale) * 100),
      }
    })
}

/**
 * Build football field (valuation range) data from DCF sensitivity grid.
 * Extracts ranges by varying one assumption at a time:
 * - "Discount Rate" row: base terminal growth, vary WACC across grid
 * - "Terminal Growth" row: base WACC, vary terminal growth across grid
 * - "Combined" row: full grid range (most conservative to most optimistic)
 *
 * Each row has { method, low, mid, high } where mid = base-case implied price.
 */
export function dcfSensitivityToFootballData(
  result: DCFResult,
  sensitivity: SensitivityResult,
): Array<Record<string, number | string | boolean | null>> {
  const midPrice = result.implied_price
  const grid = sensitivity.implied_prices

  // Extract non-null values from a row/column of the grid
  const extractValid = (values: (number | null)[]): number[] =>
    values.filter((v): v is number => v != null && v > 0 && isFinite(v))

  // Middle row index (base WACC row) — vary terminal growth
  const midRow = Math.floor(grid.length / 2)
  const tgRow = extractValid(grid[midRow] ?? [])

  // Middle column (base TG column) — vary WACC
  const midCol = Math.floor((grid[0]?.length ?? 0) / 2)
  const waccCol = extractValid(grid.map((row) => row[midCol]))

  // Full grid — all values
  const allValues = extractValid(grid.flat())

  const rows: Array<Record<string, number | string | boolean | null>> = []

  if (waccCol.length >= 2) {
    rows.push({
      method: 'Discount Rate',
      low: Math.min(...waccCol),
      mid: midPrice,
      high: Math.max(...waccCol),
    })
  }

  if (tgRow.length >= 2) {
    rows.push({
      method: 'Terminal Growth',
      low: Math.min(...tgRow),
      mid: midPrice,
      high: Math.max(...tgRow),
    })
  }

  if (allValues.length >= 2) {
    rows.push({
      method: 'Combined Range',
      low: Math.min(...allValues),
      mid: midPrice,
      high: Math.max(...allValues),
    })
  }

  return rows
}

// ── FinancialsTab adapters (from HistoricalMetrics) ────────────────────

export function historicalToRevenueEbitdaData(h: HistoricalMetrics) {
  return h.years.map((year, i) => ({
    year: String(year),
    revenue: h.revenue[i],
    ebitda: h.ebitda[i],
    is_forecast: false,
  }))
}

export function historicalToMarginData(h: HistoricalMetrics) {
  // MarginTrendChart.formatPercent already does value * 100,
  // so feed raw fractions (0-1 range) to match dcfResultToMarginData behavior.
  return h.years.map((year, i) => ({
    year: String(year),
    gross_margin: h.gross_margin[i],
    ebitda_margin: h.ebitda_margin[i],
    operating_margin: h.operating_margin[i],
    is_forecast: false,
  }))
}

export function historicalToRevenueYoYData(h: HistoricalMetrics) {
  return h.years
    .map((year, i) => ({
      year: String(year),
      yoy_pct: h.revenue_growth_yoy[i] != null ? Number(h.revenue_growth_yoy[i]) * 100 : null,
    }))
    .filter((d) => d.yoy_pct != null)
}

export function historicalToCashFlowData(h: HistoricalMetrics) {
  return h.years.map((year, i) => ({
    year: String(year),
    operating: h.operating_cash_flow[i],
    investing: h.investing_cash_flow[i],
    financing: h.financing_cash_flow[i],
  }))
}

export function quarterlyToComparisonData(q: QuarterlyData) {
  return q.quarters.map((qtr) => ({
    quarter: qtr.quarter,
    revenue: qtr.revenue,
    operating_income: qtr.operating_income,
    net_income: qtr.net_income,
  }))
}

// ── ValuationTab adapters ──────────────────────────────────────────────

export function historicalToEpsPeData(h: HistoricalMetrics) {
  return h.years.map((year, i) => ({
    year: String(year),
    eps: h.eps[i],
    pe_ratio: h.pe_ratio[i],
  }))
}

export interface SurpriseDataPoint {
  quarter: string
  eps_actual: number
  eps_estimated: number
  surprise_pct: number
  direction: 'beat' | 'miss' | 'inline'
}

export function earningsToSurpriseChartData(surprises: EarningsSurprise[]): SurpriseDataPoint[] {
  // CRITICAL: field names differ between store and chart component.
  // Store uses: date, eps_surprise_pct, eps_direction
  // Chart expects: quarter, surprise_pct, direction
  // Must explicitly rename — do NOT spread the EarningsSurprise object.
  return surprises.map((s) => ({
    quarter: s.date,
    eps_actual: s.eps_actual,
    eps_estimated: s.eps_estimated,
    surprise_pct: s.eps_surprise_pct,
    direction: s.eps_direction,
  }))
}
