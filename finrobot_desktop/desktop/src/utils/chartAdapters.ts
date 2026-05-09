import type { DCFResult, DCFInputs, SensitivityResult } from '../stores/appStore'

/**
 * Convert backend DcfSensitivityResult grid to the flat array format
 * that SensitivityHeatmap expects.
 */
export function sensitivityGridToHeatmapRows(
  result: SensitivityResult
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
  result: DCFResult
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
 * Computes EBITDA margin per projected year.
 * Operating margin approximated as EBITDA margin minus D&A (if available).
 */
export function dcfResultToMarginData(
  result: DCFResult
): Array<Record<string, number | string | boolean | null>> {
  const currentYear = new Date().getFullYear()
  const rows: Array<Record<string, number | string | boolean | null>> = []

  // Base year
  const baseEbitdaMargin = result.inputs.ebitda_margin
  const daPct = result.inputs.da_pct_revenue ?? 0
  rows.push({
    year: String(currentYear),
    ebitda_margin: baseEbitdaMargin,
    operating_margin: baseEbitdaMargin - daPct,
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
      operating_margin: ebitdaMargin - daPct,
      is_forecast: true,
    })
  }

  return rows
}

/**
 * Convert DCFResult into the waterfall data format for WaterfallChart.
 * Each entry has { label, value, is_total }.
 */
export function dcfResultToWaterfallData(
  result: DCFResult
): Array<Record<string, number | string | boolean | null>> {
  return [
    { label: 'PV of FCF', value: result.pv_fcf_total, is_total: false },
    { label: 'PV Terminal Value', value: result.pv_terminal, is_total: false },
    { label: 'Enterprise Value', value: result.enterprise_value, is_total: true },
    { label: 'Less: Net Debt', value: -(result.enterprise_value - result.equity_value), is_total: false },
    { label: 'Equity Value', value: result.equity_value, is_total: true },
  ]
}
