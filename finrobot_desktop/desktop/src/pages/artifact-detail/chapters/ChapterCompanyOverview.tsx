// Chapter 02 — Company Overview. The header promises BUSINESS · SEGMENTS ·
// GEOGRAPHY · MOAT, but the only structured datum the pipeline carries here is
// the company_overview narrative (the 8th synthesis slot, populated by
// synthesis_agent as of 2026-05-23). Segments/geography data does NOT exist in
// the artifact — we do NOT fabricate it. What the artifact DOES carry, and no
// other chapter surfaces at this point in the scroll, is the company's identity
// (sector / industry / country) + headline scale (market cap, revenue CAGR,
// gross margin, beta). We render that as a compact, sourced snapshot strip above
// the narrative so the chapter delivers structure, not just a text wall.
//
// Provenance MIRRORS ChapterFinancialData: numeric cells wrap in SourcedNumber
// (provider from raw_data.provenance ?? dataSource, fetched_at), identity
// strings render plain. Market cap is a QUOTE-currency figure (same arg
// ChapterFinancialData passes). cagr_revenue + gross_margin are RATIOS
// (0.479 = 47.9%) → formatPercent. Every cell is omitted when its value is
// null/absent, so the strip degrades to "narrative only" (and the narrative to
// the empty-state) without ever blanking, crashing, or printing NaN/undefined.

import type { NumberSource } from '../../../components/SourcedNumber'
import type { HistoricalMetrics } from '../../../types/finance'
import { Chapter, Narrative } from './ChapterBase'
import { CompanySnapshot, type SnapshotIdentity, type SnapshotMetric } from './CompanySnapshot'
import type { ThesisShape } from './types'
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

export function ChapterCompanyOverview({
  thesis,
  rawData,
  historicalMetrics,
  quoteCurrency,
  dataSource,
  fetchedAt,
}: {
  thesis: ThesisShape | null
  rawData: Record<string, unknown> | null
  historicalMetrics: HistoricalMetrics | null
  // Market cap is a quote-currency figure — same arg ChapterFinancialData passes.
  quoteCurrency: string
  dataSource: string | null
  fetchedAt: string | null
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
          <p>{overview}</p>
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
    </Chapter>
  )
}
