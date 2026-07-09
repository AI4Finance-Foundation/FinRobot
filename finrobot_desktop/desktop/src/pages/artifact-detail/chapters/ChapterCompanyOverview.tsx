// Chapter 02 — Company Overview: BUSINESS · SEGMENTS · GEOGRAPHY · MOAT. The
// pipeline carries the company_overview narrative (the 8th synthesis slot,
// populated by synthesis_agent as of 2026-05-23) plus, since BACKLOG A4
// (2026-07-09), a real segment revenue mix (segmentOverview — SEC XBRL ASC-280
// reportable segments ONLY; null for a single-segment issuer, an unwired SEC,
// or an issuer whose XBRL has no cleanly-anchorable segment breakdown (e.g.
// KO), in which case the narrative degrades to its own honest "unavailable"
// line — we still never fabricate a figure or substitute a different-caliber
// FMP product mix). Geography remains narrative-only (no geographic fetch is
// wired). What the artifact ALSO carries, and no other chapter surfaces at this
// point in the scroll, is the company's identity (sector / industry / country)
// + headline scale (market cap, revenue CAGR, gross margin, beta). We render
// that as a compact, sourced snapshot strip above the narrative + segment table
// so the chapter delivers structure, not just a text wall.
//
// Provenance MIRRORS ChapterFinancialData: numeric cells wrap in SourcedNumber
// (provider from raw_data.provenance ?? dataSource, fetched_at), identity
// strings render plain. Market cap is a QUOTE-currency figure (same arg
// ChapterFinancialData passes). cagr_revenue + gross_margin are RATIOS
// (0.479 = 47.9%) → formatPercent. Every cell is omitted when its value is
// null/absent, so the strip degrades to "narrative only" (and the narrative to
// the empty-state) without ever blanking, crashing, or printing NaN/undefined.
// Segment metrics (revenue / operating income / gross profit) are REPORTING
// currency (mirrors ChapterValuation's SOTPBreakdownPanel).

import type { NumberSource } from '../../../components/SourcedNumber'
import type { HistoricalMetrics } from '../../../types/finance'
import { Chapter, Narrative } from './ChapterBase'
import { MarkdownLite } from '../../../components/MarkdownLite'
import { CompanySnapshot, type SnapshotIdentity, type SnapshotMetric } from './CompanySnapshot'
import type { SegmentOverviewShape, SegmentShareShape, ThesisShape } from './types'
import { formatCurrencyCompact, formatNumber, formatPercent } from '../../../utils/format'
import { useI18n, type Locale } from '../../../i18n'

// Identity + scale slice of raw_data.market. Superset of ChapterFinancialData's
// MarketShape — adds `country` (present in the FinancialData dump, unused there).
interface MarketShape {
  sector?: string | null
  industry?: string | null
  country?: string | null
  market_cap?: number | null
  beta?: number | null
}

interface IncomeShape {
  gross_margin?: number | null
  operating_margin?: number | null
}

interface ProvenanceShape {
  provider?: string | null
}

function tr(zh: string, en: string, locale: Locale): string {
  return locale === 'en' ? en : zh
}

/** Build the identity + scale snapshot. Identity strings render plain (no
 *  provenance); numeric metrics carry the provider/fetched_at provenance via
 *  SourcedNumber and a raw value for the gauge encoding. A field is included
 *  ONLY when present — an absent field produces no chip/tile (never blank/NaN).
 *  Metric order = market cap → gross margin → operating margin → CAGR → beta
 *  (telemetry layout; the two margins sit adjacent as the profitability pair). */
function buildSnapshot(
  market: MarketShape,
  income: IncomeShape | undefined,
  historicalMetrics: HistoricalMetrics | null,
  quoteCurrency: string,
  locale: Locale,
  source?: NumberSource,
): { identity: SnapshotIdentity; metrics: SnapshotMetric[] } {
  // ── Identity (plain strings, no provenance popover) ───────────────────────
  const identity: SnapshotIdentity = {}
  if (typeof market.sector === 'string' && market.sector) identity.sector = market.sector
  if (typeof market.industry === 'string' && market.industry) identity.industry = market.industry
  if (typeof market.country === 'string' && market.country) identity.country = market.country

  // ── Scale (numeric, sourced; raw drives the gauge) ────────────────────────
  const metrics: SnapshotMetric[] = []
  if (typeof market.market_cap === 'number' && Number.isFinite(market.market_cap)) {
    metrics.push({
      kind: 'market_cap',
      label: tr('市值', 'Market Cap', locale),
      // Market cap is a quote-currency figure (mirrors ChapterFinancialData).
      value: formatCurrencyCompact(market.market_cap, quoteCurrency, locale),
      raw: market.market_cap,
      source,
    })
  }
  const grossMargin = income?.gross_margin
  if (typeof grossMargin === 'number' && Number.isFinite(grossMargin)) {
    metrics.push({
      kind: 'gross_margin',
      // gross_margin is a RATIO (0.479 = 47.9%) → the arc fills 47.9% of sweep.
      label: tr('毛利率', 'Gross Margin', locale),
      value: formatPercent(grossMargin, locale),
      raw: grossMargin,
      source,
    })
  }
  // Operating margin (EBIT/revenue) — the profitability companion to gross margin.
  // Can be negative for loss-makers (backend IncomeStatement.operating_margin
  // allows ge=-5); RadialArc clamps a negative raw to an empty sweep. Sits
  // adjacent to gross margin so the two read as the profitability pair.
  const operatingMargin = income?.operating_margin
  if (typeof operatingMargin === 'number' && Number.isFinite(operatingMargin)) {
    metrics.push({
      kind: 'operating_margin',
      label: tr('营业利润率', 'Operating Margin', locale),
      value: formatPercent(operatingMargin, locale),
      raw: operatingMargin,
      source,
    })
  }
  const cagr = historicalMetrics?.cagr_revenue
  if (typeof cagr === 'number' && Number.isFinite(cagr)) {
    metrics.push({
      kind: 'cagr',
      // cagr_revenue is a RATIO (0.0328 = 3.3%); sign drives the trend glyph.
      label: tr('营收复合增速', 'Revenue CAGR', locale),
      value: formatPercent(cagr, locale),
      raw: cagr,
      source,
    })
  }
  if (typeof market.beta === 'number' && Number.isFinite(market.beta)) {
    metrics.push({
      kind: 'beta',
      label: 'Beta',
      value: formatNumber(market.beta, locale, 2),
      raw: market.beta,
      source,
    })
  }

  return { identity, metrics }
}

// Which profitability metric the breakdown actually carries — MSFT-style
// issuers (extract_segment_facts' OperatingIncomeLoss anchor) populate
// operating_income; TSLA-style issuers (the GrossProfit anchor) populate
// gross_profit; some issuers disclose neither at segment level (revenue-only) →
// no profit column. Never both for the same breakdown (see the backend's
// extract_segment_facts docstring).
function deriveProfitMetricKind(
  segments: SegmentShareShape[],
): 'operating_income' | 'gross_profit' | null {
  if (segments.some((s) => typeof s.operating_income === 'number')) return 'operating_income'
  if (segments.some((s) => typeof s.gross_profit === 'number')) return 'gross_profit'
  return null
}

/** Segment revenue mix table (BACKLOG A4, 2026-07-09) — the deterministic,
 *  sourced complement to the company_overview prose (which cites the SAME
 *  segmentOverview data via the thesis prompt's numeric whitelist, never
 *  narrating a figure not in this table). Renders nothing when segments is
 *  empty (the caller already gates on that). */
function SegmentOverviewTable({
  segmentOverview,
  reportingCurrency,
}: {
  segmentOverview: SegmentOverviewShape
  reportingCurrency: string
}): React.ReactElement {
  const { locale } = useI18n()
  const profitKind = deriveProfitMetricKind(segmentOverview.segments)
  // XBRL-only (BACKLOG A4): source is always the audited ASC-280 reportable
  // segment breakdown — an issuer without one ships no SegmentOverview at all.
  const sourceLabel = tr(
    'SEC XBRL 可报告分部(ASC 280)',
    'SEC XBRL reportable segments (ASC 280)',
    locale,
  )
  const profitHeader =
    profitKind === 'operating_income'
      ? tr('分部营业利润', 'Segment Operating Income', locale)
      : profitKind === 'gross_profit'
        ? tr('分部毛利', 'Segment Gross Profit', locale)
        : null

  return (
    <div style={{ marginTop: 20 }}>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-muted)',
          marginBottom: 8,
        }}
      >
        {sourceLabel} · {segmentOverview.period_label}
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
          }}
        >
          <thead>
            <tr style={{ color: 'var(--text-muted)', textAlign: 'left' }}>
              <th style={{ padding: '4px 8px' }}>{tr('分部', 'Segment', locale)}</th>
              <th style={{ padding: '4px 8px', textAlign: 'right' }}>
                {tr('营收', 'Revenue', locale)}
              </th>
              <th style={{ padding: '4px 8px', textAlign: 'right' }}>
                {tr('营收占比', 'Revenue Share', locale)}
              </th>
              {profitHeader && (
                <th style={{ padding: '4px 8px', textAlign: 'right' }}>{profitHeader}</th>
              )}
            </tr>
          </thead>
          <tbody>
            {segmentOverview.segments.map((s) => {
              const profitValue =
                profitKind === 'operating_income'
                  ? s.operating_income
                  : profitKind === 'gross_profit'
                    ? s.gross_profit
                    : null
              return (
                <tr key={s.name} style={{ borderTop: '1px solid var(--border-grid)' }}>
                  <td style={{ padding: '4px 8px', color: 'var(--text-primary)' }}>{s.name}</td>
                  <td
                    style={{
                      padding: '4px 8px',
                      textAlign: 'right',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    {typeof s.revenue === 'number'
                      ? formatCurrencyCompact(s.revenue, reportingCurrency, locale)
                      : '—'}
                  </td>
                  <td
                    style={{
                      padding: '4px 8px',
                      textAlign: 'right',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    {typeof s.revenue_share === 'number'
                      ? formatPercent(s.revenue_share, locale)
                      : '—'}
                  </td>
                  {profitHeader && (
                    <td
                      style={{
                        padding: '4px 8px',
                        textAlign: 'right',
                        color: 'var(--accent-cyan)',
                      }}
                    >
                      {typeof profitValue === 'number'
                        ? formatCurrencyCompact(profitValue, reportingCurrency, locale)
                        : '—'}
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--text-dim)',
          marginTop: 6,
          lineHeight: 1.5,
        }}
      >
        {tr(
          '营收占比按本表分部合计计算,可能因公司/抵销项(部分发行人不单独披露)而与合并总收入存在差异。',
          'Revenue share is computed against the sum of segments shown here — corporate / eliminations items, where an issuer has them, are not broken out and may keep this from summing exactly to consolidated total revenue.',
          locale,
        )}
      </p>
    </div>
  )
}

export function ChapterCompanyOverview({
  thesis,
  rawData,
  historicalMetrics,
  quoteCurrency,
  dataSource,
  fetchedAt,
  segmentOverview,
  reportingCurrency,
}: {
  thesis: ThesisShape | null
  rawData: Record<string, unknown> | null
  historicalMetrics: HistoricalMetrics | null
  // Market cap is a quote-currency figure — same arg ChapterFinancialData passes.
  quoteCurrency: string
  dataSource: string | null
  fetchedAt: string | null
  // BACKLOG A4 (2026-07-09): display-only segment revenue mix. null when the
  // SOTP option-value gate fired instead (that ticker's segments render in
  // ChapterValuation's SOTPBreakdownPanel) or SEC XBRL had no cleanly-anchorable
  // reportable-segment breakdown (honest "not available", no substitute).
  segmentOverview: SegmentOverviewShape | null
  reportingCurrency: string
}): React.ReactElement {
  const { t, locale } = useI18n()
  const overview = thesis?.company_overview ?? null

  const data = rawData ?? {}
  const market = (data['market'] as MarketShape | undefined) ?? {}
  const income = data['income'] as IncomeShape | undefined

  // Provenance for the snapshot's numbers (mirrors ChapterFinancialData):
  // raw_data.provenance.provider is canonical; dataSource is the legacy mirror.
  const provenance = data['provenance'] as ProvenanceShape | undefined
  const sourceProvider = provenance?.provider ?? dataSource ?? undefined
  const numberSource: NumberSource | undefined =
    sourceProvider || fetchedAt
      ? { provider: sourceProvider, fetched_at: fetchedAt ?? undefined }
      : undefined

  const { identity, metrics } = buildSnapshot(
    market,
    income,
    historicalMetrics,
    quoteCurrency,
    locale,
    numberSource,
  )

  return (
    <Chapter id="overview">
      <CompanySnapshot
        identity={identity}
        metrics={metrics}
        quoteCurrency={quoteCurrency}
        fetchedAt={fetchedAt}
        labels={{
          sector: tr('板块', 'Sector', locale),
          industry: tr('行业', 'Industry', locale),
          country: tr('国家/地区', 'Country', locale),
        }}
      />

      {overview ? (
        <Narrative>
          <MarkdownLite text={overview} />
        </Narrative>
      ) : (
        // Empty-state is unchanged — the snapshot strip is purely additive above
        // it. The message ("no company-overview field; re-run for prose coverage")
        // stays accurate when the snapshot is present but the narrative is not.
        <div
          style={{
            background: 'var(--bg-card-50)',
            border: '1px dashed var(--border-soft)',
            borderRadius: 'var(--radius-sm)',
            padding: '18px 22px',
            fontSize: 12.5,
            color: 'var(--text-muted)',
            lineHeight: 1.7,
          }}
        >
          {t('chapter.companyOverview.empty')}
        </div>
      )}

      {segmentOverview && segmentOverview.segments.length > 0 && (
        <SegmentOverviewTable
          segmentOverview={segmentOverview}
          reportingCurrency={reportingCurrency}
        />
      )}
    </Chapter>
  )
}
