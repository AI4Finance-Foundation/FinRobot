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
import { Chapter, KvGrid, Narrative, type KvCell } from './ChapterBase'
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
}

interface ProvenanceShape {
  provider?: string | null
}

function tr(zh: string, en: string, locale: Locale): string {
  return locale === 'en' ? en : zh
}

/** Build the identity+scale snapshot cells. Identity strings render plain;
 *  numeric cells carry the provider/fetched_at provenance (SourcedNumber).
 *  A cell is pushed ONLY when its value is present — never a blank/NaN cell. */
function buildSnapshotCells(
  market: MarketShape,
  income: IncomeShape | undefined,
  historicalMetrics: HistoricalMetrics | null,
  quoteCurrency: string,
  locale: Locale,
  source?: NumberSource,
): KvCell[] {
  const cells: KvCell[] = []

  // ── Identity (plain strings, no provenance popover) ───────────────────────
  if (typeof market.sector === 'string' && market.sector) {
    cells.push({ label: tr('板块', 'Sector', locale), value: market.sector })
  }
  if (typeof market.industry === 'string' && market.industry) {
    cells.push({ label: tr('行业', 'Industry', locale), value: market.industry })
  }
  if (typeof market.country === 'string' && market.country) {
    cells.push({ label: tr('国家/地区', 'Country', locale), value: market.country })
  }

  // ── Scale (numeric, sourced) ──────────────────────────────────────────────
  if (typeof market.market_cap === 'number' && Number.isFinite(market.market_cap)) {
    cells.push({
      label: tr('市值', 'Market Cap', locale),
      // Market cap is a quote-currency figure (mirrors ChapterFinancialData).
      value: formatCurrencyCompact(market.market_cap, quoteCurrency, locale),
      source,
    })
  }
  const cagr = historicalMetrics?.cagr_revenue
  if (typeof cagr === 'number' && Number.isFinite(cagr)) {
    cells.push({
      // cagr_revenue is a RATIO (0.0328 = 3.3%).
      label: tr('营收复合增速', 'Revenue CAGR', locale),
      value: formatPercent(cagr, locale),
      source,
    })
  }
  const grossMargin = income?.gross_margin
  if (typeof grossMargin === 'number' && Number.isFinite(grossMargin)) {
    cells.push({
      // gross_margin is a RATIO (0.479 = 47.9%).
      label: tr('毛利率', 'Gross Margin', locale),
      value: formatPercent(grossMargin, locale),
      source,
    })
  }
  if (typeof market.beta === 'number' && Number.isFinite(market.beta)) {
    cells.push({ label: 'Beta', value: formatNumber(market.beta, locale, 2), source })
  }

  return cells
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

  const snapshotCells = buildSnapshotCells(
    market,
    income,
    historicalMetrics,
    quoteCurrency,
    locale,
    numberSource,
  )

  return (
    <Chapter id="overview">
      {snapshotCells.length > 0 && <KvGrid cells={snapshotCells} columns={4} />}

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
