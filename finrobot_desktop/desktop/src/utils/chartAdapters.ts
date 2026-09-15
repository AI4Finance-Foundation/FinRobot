import type { DCFResult, CompsResult, HistoricalMetrics } from '../types/finance'
import { tSync } from '../i18n'

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
    // P/B rides along so the balance-sheet-financial branch can plot it as the
    // primary bar in place of EV/EBITDA (a category error for deposit-takers).
    pb_ratio: c.pb_ratio ?? null,
    pe_ratio: c.pe_ratio,
    is_target: c.ticker === result.target.ticker,
  }))
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

  // lowerBetter marks the valuation-multiple axes (cheaper = better) vs the
  // margin axes (higher = better) so both can be mapped to a consistent
  // "outward = more favorable" radial direction below.
  const dims: {
    label: string
    company: number | null
    median: number | null
    lowerBetter: boolean
  }[] = [
    {
      label: tSync('chart.radar.dim.pe'),
      company: t.pe_ratio,
      median: result.median_pe,
      lowerBetter: true,
    },
    {
      label: tSync('chart.radar.dim.evEbitda'),
      company: t.ev_ebitda,
      median: result.median_ev_ebitda,
      lowerBetter: true,
    },
    {
      label: tSync('chart.radar.dim.evRevenue'),
      company: t.ev_revenue,
      median: result.median_ev_revenue,
      lowerBetter: true,
    },
    {
      label: tSync('chart.radar.dim.grossMargin'),
      company: t.gross_margin,
      median: peerGrossMedian,
      lowerBetter: false,
    },
    {
      label: tSync('chart.radar.dim.operatingMargin'),
      company: t.operating_margin,
      median: peerOpMedian,
      lowerBetter: false,
    },
  ]

  // Map each axis so "outward = more favorable vs the peer median" CONSISTENTLY:
  // a cheaper multiple (lower) AND a higher margin both push the company point OUT
  // past the benchmark ring. The old normalization divided by max(|company|,
  // |median|), so a cheaper — i.e. better — multiple plotted *smaller/inside* and
  // read backwards. The peer median is pinned to a fixed ring (100); the company
  // sits at favorability×100, capped to [0,200] so an extreme outlier (e.g. a
  // 226× P/E peer) can't blow out the axis. Ill-defined axes are dropped: a
  // multiple needs company>0 & median>0 (a negative P/E is N/A, not "cheap").
  return dims
    .filter((d) => {
      if (d.company == null || d.median == null || !isFinite(d.company) || !isFinite(d.median)) {
        return false
      }
      return d.lowerBetter ? d.company > 0 && d.median > 0 : d.median > 0
    })
    .map((d) => {
      const company = d.company as number
      const median = d.median as number
      const ratio = d.lowerBetter ? median / company : company / median
      return {
        dimension: d.label,
        value: Math.round(Math.max(0, Math.min(200, ratio * 100))),
        benchmark: 100,
      }
    })
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

/**
 * Bank-caliber trajectory (balance-sheet financials): Revenue + Net Income bars
 * plus a Return-on-Equity line. EBITDA / EBITDA-margin are a category error for
 * deposit-takers, so this replaces the Revenue&EBITDA + margin charts.
 *
 * ROE = net_income / shareholders_equity per year — emitted ONLY when that year's
 * equity is a positive finite number (the field is empty on artifacts generated
 * before the 2026-07-06 equity plumbing). A year without valid equity carries
 * roe=null and the chart degrades to Revenue + Net Income (never fabricated).
 */
export function historicalToBankTrajectoryData(h: HistoricalMetrics) {
  const equity = h.shareholders_equity ?? []
  return h.years.map((year, i) => {
    const eq = equity[i]
    const ni = h.net_income[i]
    const roe =
      typeof eq === 'number' && Number.isFinite(eq) && eq > 0 && ni != null ? ni / eq : null
    return { year: String(year), revenue: h.revenue[i], net_income: ni, roe }
  })
}

export function historicalToCashFlowData(h: HistoricalMetrics) {
  return h.years.map((year, i) => ({
    year: String(year),
    operating: h.operating_cash_flow[i],
    investing: h.investing_cash_flow[i],
    financing: h.financing_cash_flow[i],
  }))
}

/**
 * Annual BASIC EPS (not diluted — FMP's `eps` field is basic, and the
 * yfinance path preferentially matches a "Basic EPS" row when present; see
 * fmp_provider.py's per-year extraction comment) with YoY growth. Historical
 * P/E is intentionally NOT paired here: the backend only carries a
 * current-year P/E (prior years are null), so an EPS×P/E dual chart would
 * render a one-point P/E line. EPS itself is fully populated, so this powers
 * a clean EPS-trend bar chart instead. yoy uses abs(prev) as the base so a
 * swing off a tiny/negative EPS keeps its sign without flipping.
 */
export function historicalToEpsData(h: HistoricalMetrics) {
  return h.years.map((year, i) => {
    const eps = h.eps[i]
    const prev = i > 0 ? h.eps[i - 1] : null
    const yoy =
      prev != null && prev !== 0 && eps != null ? ((eps - prev) / Math.abs(prev)) * 100 : null
    return { year: String(year), eps, yoy }
  })
}
