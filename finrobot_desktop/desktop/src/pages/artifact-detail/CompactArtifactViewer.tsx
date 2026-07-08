// CompactArtifactViewer — the detail body for NON equity_research artifacts
// (dcf / ddm / lbo / comps / earnings / ic_memo / peer_research / ad_hoc).
//
// These artifacts are single deterministic computations, not 13-chapter reports.
// The four valuation tools (dcf / ddm / lbo / comps) now render through the SAME
// chapter primitives the full report uses — one visual language, no raw K-V dump:
//   - dcf   → ValuationBody (DCF inputs + bridge) + DcfForecastTable (10y, full) +
//             SensitivityBody (WACC × TG heatmap)
//   - comps → CompetitiveBody (peer table + heat shading + medians + charts)
//   - ddm   → DdmBody (inputs module + full dividend projection)
//   - lbo   → LboBody (entry/exit modules + full debt schedule + IRR sensitivity)
// Every array renders in full (no silent slice); every number is type-formatted
// (currency / percent / ×), never a bare decimal or ISO timestamp; labels are
// human, never snake_case.
//
// This viewer keeps ownership of the artifact-generic surfaces: the type-aware
// headline number, the LLM summary, the numeric-audit banner (reused), a READABLE
// assumption-provenance trail (the sourcing gold that was buried as "16 fields"),
// the reader-facing compute warnings, and the audit/provenance metadata. Uncovered
// types (earnings / ic_memo / ad_hoc) still degrade to a clean flattened grid —
// but arrays are no longer truncated.

import type { ReactNode } from 'react'
import type { ArtifactDetail } from '../../hooks/useV5Artifacts'
import { useI18n, type Locale } from '../../i18n'
import { formatCurrency, formatPercent, formatDate, formatCompactNumber } from '../../utils/format'
import { MarkdownLite } from '../../components/MarkdownLite'
import { layerComputeWarnings, parseSurfacedContractFindings } from './reportData'
import { ComputeWarningsPanel } from './ComputeWarningsPanel'
import {
  ChapterAuditBanner,
  ValuationBody,
  SensitivityBody,
  CompetitiveBody,
  DcfForecastTable,
  DdmBody,
  LboBody,
} from './chapters'
import type {
  DcfShape,
  DdmShape,
  LboShape,
  LboInputsShape,
  PeerCompsShape,
  NumericAuditShape,
} from './chapters/types'

interface CompactInputs {
  data_source?: string
  data_fetched_at?: string
  raw_data?: Record<string, unknown>
}
interface CompactOutputs {
  structured?: Record<string, unknown>
  summary_text?: string
  warnings?: string[]
}
interface CompactMeta {
  created_at?: string
  source?: string
}
interface CompactComputeVersion {
  version?: string
  git_commit?: string
  formula_id?: string
  formula_warnings?: string[]
}

interface HeadlineStat {
  label: string
  value: string
  // Optional inline marker rendered next to the value (e.g. the LBO
  // not-self-financing caveat, so a headline IRR can't be read as achievable).
  badge?: ReactNode
}

const T = (locale: Locale, zh: string, en: string): string => (locale === 'zh' ? zh : en)

// Inline caveat pill next to a headline number (LBO not-self-financing). Warning
// tone, muted — a caliber caveat, not an error; the full explanation is on hover.
const NOT_SELF_FINANCING_BADGE: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  fontWeight: 500,
  color: 'var(--warning)',
  border: '1px solid var(--warning)',
  borderRadius: 'var(--radius-sm)',
  padding: '2px 7px',
  cursor: 'help',
  whiteSpace: 'nowrap',
}

function isPlainNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

/** Pretty-print a snake_case key as a Title-ish label, locale-agnostic. */
function humanizeKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bPe\b/g, 'P/E')
    .replace(/\bPb\b/g, 'P/B')
    .replace(/\bEv\b/g, 'EV')
    .replace(/\bEbitda\b/g, 'EBITDA')
    .replace(/\bIrr\b/g, 'IRR')
    .replace(/\bMoic\b/g, 'MOIC')
    .replace(/\bWacc\b/g, 'WACC')
    .replace(/\bDcf\b/g, 'DCF')
    .replace(/\bLbo\b/g, 'LBO')
    .replace(/\bDdm\b/g, 'DDM')
    .replace(/\bDps\b/g, 'DPS')
    .replace(/\bNwc\b/g, 'NWC')
    .replace(/\bDa\b/g, 'D&A')
    .replace(/\bRoe\b/g, 'ROE')
    .replace(/\bTtm\b/g, 'TTM')
    .replace(/\bPct\b/g, '%')
}

/** Render a scalar value for the generic grid (uncovered types only). Arrays
 * render IN FULL (never a silent slice) — the "10 年投影只显示前 8 项" bug. */
function renderScalar(v: unknown, locale: Locale): string | null {
  if (v === null || v === undefined) return null
  if (typeof v === 'boolean') return v ? T(locale, '是', 'Yes') : T(locale, '否', 'No')
  if (typeof v === 'string') return v.trim() === '' ? null : v
  if (isPlainNumber(v)) {
    if (Math.abs(v) >= 1e6) return formatCompactNumber(v, locale)
    return new Intl.NumberFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
      maximumFractionDigits: 4,
    }).format(v)
  }
  if (Array.isArray(v)) {
    if (v.length === 0) return null
    if (v.every((x) => isPlainNumber(x) || typeof x === 'string')) {
      return v.map((x) => (isPlainNumber(x) ? renderScalar(x, locale) : String(x))).join(', ')
    }
    return T(locale, `${v.length} 项`, `${v.length} items`)
  }
  if (typeof v === 'object') {
    const n = Object.keys(v as object).length
    return T(locale, `${n} 字段`, `${n} fields`)
  }
  return String(v)
}

interface KV {
  key: string
  label: string
  value: string
}

/** Flatten a structured dict into displayable key/value rows (one level deep).
 * Only used by the generic fallback for uncovered artifact types. */
function flatten(obj: Record<string, unknown> | undefined, locale: Locale): KV[] {
  if (!obj) return []
  const rows: KV[] = []
  for (const [key, raw] of Object.entries(obj)) {
    const value = renderScalar(raw, locale)
    if (value === null) continue
    rows.push({ key, label: humanizeKey(key), value })
  }
  return rows
}

/** Type-aware headline stats. Falls back to [] so the body still renders. */
function deriveHeadline(
  type: string,
  structured: Record<string, unknown>,
  locale: Locale,
): HeadlineStat[] {
  const num = (k: string): number | undefined =>
    isPlainNumber(structured[k]) ? (structured[k] as number) : undefined

  switch (type) {
    case 'dcf': {
      const p = num('implied_price')
      const stats: HeadlineStat[] = []
      if (p !== undefined)
        stats.push({
          label: T(locale, 'DCF 隐含股价', 'DCF Implied Price'),
          value: formatCurrency(p, 'USD', locale),
        })
      const wacc = num('wacc')
      if (wacc !== undefined) stats.push({ label: 'WACC', value: formatPercent(wacc, locale) })
      return stats
    }
    case 'ddm': {
      const p = num('equity_value_per_share')
      const stats: HeadlineStat[] = []
      if (p !== undefined)
        stats.push({
          label: T(locale, 'DDM 每股价值', 'DDM Value / Share'),
          value: formatCurrency(p, 'USD', locale),
        })
      const coe = num('cost_of_equity')
      if (coe !== undefined)
        stats.push({
          label: T(locale, '股权成本', 'Cost of Equity'),
          value: formatPercent(coe, locale),
        })
      return stats
    }
    case 'lbo': {
      const stats: HeadlineStat[] = []
      // self_financing === false: the levered FCF does NOT deleverage the
      // acquisition debt (revolver funds the shortfall, net debt rises) → the
      // IRR/MOIC are exit-multiple artifacts, not achievable returns and "must
      // not headline" (backend LBOResult contract). Badge the IRR so it can't be
      // read at face value. null (impossible structure / legacy artifact) → none.
      const badge =
        structured['self_financing'] === false ? (
          <span
            title={T(
              locale,
              '负债不自偿:经营现金流不足以去杠杆(靠循环贷补缺口、净债上升)—— IRR/MOIC 是退出倍数假象,非可实现回报。',
              'Debt does not self-finance: operating cash flow cannot deleverage the acquisition debt (the revolver funds the shortfall, net debt rises) — IRR/MOIC are exit-multiple artifacts, not achievable returns.',
            )}
            style={NOT_SELF_FINANCING_BADGE}
          >
            {T(locale, '非自偿', 'not self-financing')}
          </span>
        ) : undefined
      const irr = num('irr')
      if (irr !== undefined) stats.push({ label: 'IRR', value: formatPercent(irr, locale), badge })
      const moic = num('moic')
      if (moic !== undefined) stats.push({ label: 'MOIC', value: `${moic.toFixed(2)}×` })
      return stats
    }
    case 'comps': {
      const stats: HeadlineStat[] = []
      const pe = num('median_pe')
      if (pe !== undefined)
        stats.push({
          label: T(locale, '同业中位 P/E', 'Peer Median P/E'),
          value: `${pe.toFixed(1)}×`,
        })
      // P/B is the lead relative multiple for cyclicals & financials (book equity is
      // cycle-stable / the bank-and-insurer anchor), so surface it whenever present.
      // EV/EBITDA is nulled for financial issuers upstream (build_comps_artifact).
      const pb = num('median_pb')
      if (pb !== undefined)
        stats.push({
          label: T(locale, '同业中位 P/B', 'Peer Median P/B'),
          value: `${pb.toFixed(1)}×`,
        })
      const evEbitda = num('median_ev_ebitda')
      if (evEbitda !== undefined)
        stats.push({
          label: T(locale, '同业中位 EV/EBITDA', 'Peer Median EV/EBITDA'),
          value: `${evEbitda.toFixed(1)}×`,
        })
      return stats
    }
    case 'earnings': {
      const stats: HeadlineStat[] = []
      const beat = num('beat_rate')
      if (beat !== undefined)
        stats.push({
          label: T(locale, 'EPS 超预期率', 'EPS Beat Rate'),
          value: formatPercent(beat, locale),
        })
      const streak = num('consecutive_beats')
      if (streak !== undefined)
        stats.push({ label: T(locale, '连续超预期', 'Consecutive Beats'), value: String(streak) })
      return stats
    }
    case 'ic_memo': {
      const stats: HeadlineStat[] = []
      const dcf = structured.dcf_result as Record<string, unknown> | undefined
      const lbo = structured.lbo_result as Record<string, unknown> | undefined
      if (dcf && isPlainNumber(dcf.implied_price))
        stats.push({
          label: T(locale, 'DCF 隐含股价', 'DCF Implied Price'),
          value: formatCurrency(dcf.implied_price as number, 'USD', locale),
        })
      if (lbo && isPlainNumber(lbo.irr))
        stats.push({ label: 'LBO IRR', value: formatPercent(lbo.irr as number, locale) })
      return stats
    }
    default:
      return []
  }
}

const TYPE_LABEL: Record<string, { zh: string; en: string }> = {
  dcf: { zh: 'DCF 估值模型', en: 'DCF Valuation' },
  lbo: { zh: 'LBO 模型', en: 'LBO Model' },
  ddm: { zh: 'DDM 股利贴现', en: 'DDM Valuation' },
  comps: { zh: '可比公司分析', en: 'Comparable Companies' },
  earnings: { zh: '财报质量分析', en: 'Earnings Quality' },
  ic_memo: { zh: '投委会备忘录', en: 'IC Memo' },
  peer_research: { zh: '同业研究', en: 'Peer Research' },
  ad_hoc: { zh: '即席分析', en: 'Ad-hoc Analysis' },
}

function typeLabel(type: string, locale: Locale): string {
  const m = TYPE_LABEL[type]
  if (m) return T(locale, m.zh, m.en)
  return type
}

/** Currency for a standalone valuation tool. All four standalone pipelines
 * FX-normalize to USD before seeding (BUG-073 family), so USD is the correct
 * default; the DCF artifact additionally stamps `currency` at the structured /
 * inputs level, which we honour for the rare foreign case. */
function toolCurrency(structured: Record<string, unknown>): string {
  const top = structured.currency
  if (typeof top === 'string' && top) return top
  const inputs = structured.inputs as Record<string, unknown> | undefined
  const inner = inputs?.currency
  if (typeof inner === 'string' && inner) return inner
  return 'USD'
}

export function CompactArtifactViewer({
  artifact,
}: {
  artifact: ArtifactDetail
}): React.ReactElement {
  const { locale } = useI18n()
  const inputs = artifact.inputs as CompactInputs
  const outputs = artifact.outputs as CompactOutputs
  const meta = artifact.meta as CompactMeta
  const cv = (artifact as unknown as { compute_version?: CompactComputeVersion }).compute_version
  const assumptions = (artifact.assumptions as { parameters?: Record<string, unknown> }) ?? {}

  const structured = outputs.structured ?? {}
  const type = artifact.type
  const headline = deriveHeadline(type, structured, locale)
  const currency = toolCurrency(structured)
  const numericAudit = (structured.numeric_audit as NumericAuditShape | undefined) ?? null

  // Same reader-facing filter + layering as the full report — machine-tagged audit /
  // QA lines dropped, template boilerplate sunk into a collapsed section. The compact
  // artifacts (dcf/ddm/lbo/comps) never emit a street-range disclosure, but if a
  // legacy one somehow carried it, fold it into the caveats so it is never lost
  // (this viewer has no cover/target box to relocate it to).
  const contractFindings = parseSurfacedContractFindings(outputs.warnings ?? [])
  const layered = layerComputeWarnings(outputs.warnings ?? [])
  const compactCaveats = layered.streetContext
    ? [...layered.caveats, layered.streetContext]
    : layered.caveats
  const summaryText = (outputs.summary_text ?? '').trim()

  // Assumption-provenance trail (key → analyst prose). DCF / DDM stash it under
  // structured.inputs; LBO under assumptions.parameters (its result has no inputs).
  // Comps has no per-input provenance dict — its sourcing story is the peer-selection
  // trace, which the SUMMARY already carries (statistical_bench step), so we don't
  // repeat it here.
  const structuredInputs = structured.inputs as Record<string, unknown> | undefined
  const provenance =
    type === 'lbo'
      ? (assumptions.parameters?.assumption_provenance as Record<string, string> | undefined)
      : (structuredInputs?.assumption_provenance as Record<string, string> | undefined)

  return (
    <main data-testid="compact-artifact-viewer" style={{ minWidth: 0, padding: '12px 0 60px' }}>
      <ChapterAuditBanner audit={numericAudit} contractFindings={contractFindings} />

      {/* Header: type + ticker + headline number */}
      <header style={{ marginBottom: 28 }}>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            letterSpacing: '0.12em',
            color: 'var(--text-muted)',
            textTransform: 'uppercase',
            marginBottom: 6,
          }}
        >
          {typeLabel(type, locale)}
          {artifact.ticker ? ` · ${artifact.ticker}` : ''}
        </div>
        <h1
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 26,
            fontWeight: 600,
            color: 'var(--text-primary)',
            margin: 0,
            letterSpacing: '0.5px',
          }}
        >
          {typeLabel(type, locale)}
        </h1>

        {headline.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32, marginTop: 18 }}>
            {headline.map((h) => (
              <div key={h.label}>
                <div
                  style={{
                    fontSize: 11,
                    color: 'var(--text-muted)',
                    letterSpacing: '0.04em',
                    marginBottom: 4,
                  }}
                >
                  {h.label}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <div
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 28,
                      fontWeight: 600,
                      color: 'var(--accent)',
                      lineHeight: 1,
                    }}
                  >
                    {h.value}
                  </div>
                  {h.badge}
                </div>
              </div>
            ))}
          </div>
        )}
      </header>

      {summaryText && (
        <Section title={T(locale, '摘要', 'Summary')}>
          <MarkdownLite
            text={summaryText}
            style={{ fontSize: 13.5, lineHeight: 1.7, color: 'var(--text-secondary)' }}
          />
        </Section>
      )}

      <ToolBody
        artifact={artifact}
        structured={structured}
        assumptionParams={assumptions.parameters}
        currency={currency}
        numericAudit={numericAudit}
        locale={locale}
      />

      {provenance && Object.keys(provenance).length > 0 && (
        <Section title={T(locale, '假设与溯源', 'Assumptions & Provenance')}>
          <ProvenanceList provenance={provenance} />
        </Section>
      )}

      <ComputeWarningsPanel
        caveats={compactCaveats}
        methodologyNotes={layered.methodologyNotes}
        formulaWarnings={cv?.formula_warnings ?? []}
      />

      {/* Audit / provenance trail */}
      <Section title={T(locale, '审计溯源', 'Audit & Provenance')}>
        <KVGrid
          rows={[
            {
              key: 'created_at',
              label: T(locale, '生成时间', 'Created'),
              value: meta.created_at ? formatDate(meta.created_at, locale, 'datetime') : '—',
            },
            { key: 'source', label: T(locale, '来源', 'Source'), value: meta.source ?? '—' },
            {
              key: 'data_source',
              label: T(locale, '数据源', 'Data Source'),
              value: inputs.data_source ?? '—',
            },
            {
              key: 'data_fetched_at',
              label: T(locale, '取数时间', 'Data Fetched'),
              value: inputs.data_fetched_at
                ? formatDate(inputs.data_fetched_at, locale, 'datetime')
                : '—',
            },
            {
              key: 'formula_id',
              label: T(locale, '公式版本', 'Formula'),
              value: cv?.formula_id ?? '—',
            },
            {
              key: 'compute_version',
              label: T(locale, '计算版本', 'Compute Version'),
              value: cv?.version ? `finrobot ${cv.version}` : '—',
            },
            { key: 'artifact_id', label: 'Artifact ID', value: artifact.id },
          ]}
        />
      </Section>
    </main>
  )
}

/** Route each covered valuation tool to the report's chapter primitives; degrade
 * uncovered types to the flattened grid (arrays no longer truncated). */
function ToolBody({
  artifact,
  structured,
  assumptionParams,
  currency,
  numericAudit,
  locale,
}: {
  artifact: ArtifactDetail
  structured: Record<string, unknown>
  assumptionParams: Record<string, unknown> | undefined
  currency: string
  numericAudit: NumericAuditShape | null
  locale: Locale
}): React.ReactElement {
  switch (artifact.type) {
    case 'dcf': {
      const dcf = structured as unknown as DcfShape
      return (
        <>
          <Section title={T(locale, '估值', 'Valuation')}>
            <ValuationBody
              dcf={dcf}
              thesis={null}
              valuationSynthesis={null}
              forwardEstimates={null}
              sotpBreakdown={null}
              quoteCurrency={currency}
              reportingCurrency={currency}
              numericAudit={numericAudit}
            />
          </Section>
          <Section title={T(locale, '财务预测', 'Financial Forecast')}>
            <DcfForecastTable dcf={dcf} reportingCurrency={currency} />
          </Section>
          <Section title={T(locale, '敏感性', 'Sensitivity')}>
            {/* showReconciliation={false}: this page already renders a full
                ProvenanceList below, so the reconciliation's "Model uses" column
                would double-list the same strings (同源双列). The margin swing note
                still renders — it duplicates nothing. */}
            <SensitivityBody
              dcf={dcf}
              financialSector={false}
              quoteCurrency={currency}
              showReconciliation={false}
            />
          </Section>
        </>
      )
    }
    case 'ddm':
      return (
        <Section title={T(locale, 'DDM 模型', 'DDM Model')}>
          <DdmBody ddm={structured as unknown as DdmShape} currency={currency} />
        </Section>
      )
    case 'lbo':
      return (
        <Section title={T(locale, 'LBO 模型', 'LBO Model')}>
          <LboBody
            lbo={structured as unknown as LboShape}
            inputs={(assumptionParams as unknown as LboInputsShape | undefined) ?? null}
            currency={currency}
          />
        </Section>
      )
    case 'comps':
      return (
        <Section title={T(locale, '同业对比', 'Peer Comparison')}>
          <CompetitiveBody peers={structured as unknown as PeerCompsShape} thesis={null} />
        </Section>
      )
    default:
      return (
        <GenericBody structured={structured} assumptionParams={assumptionParams} locale={locale} />
      )
  }
}

/** Fallback for uncovered types (earnings / ic_memo / peer_research / ad_hoc):
 * the inputs + results flattened grid. Arrays render in full (no slice). */
function GenericBody({
  structured,
  assumptionParams,
  locale,
}: {
  structured: Record<string, unknown>
  assumptionParams: Record<string, unknown> | undefined
  locale: Locale
}): React.ReactElement {
  const inputRows = flatten(assumptionParams, locale)
  // ic_memo nests { dcf_result, lbo_result } — surface their scalars one level
  // deeper so the grid isn't just "N fields, N fields".
  const resultSource: Record<string, unknown> =
    'dcf_result' in structured || 'lbo_result' in structured
      ? {
          ...((structured.dcf_result as Record<string, unknown>) ?? {}),
          ...((structured.lbo_result as Record<string, unknown>) ?? {}),
        }
      : structured
  const resultRows = flatten(resultSource, locale)
  return (
    <>
      {inputRows.length > 0 && (
        <Section title={T(locale, '输入假设', 'Inputs & Assumptions')}>
          <KVGrid rows={inputRows} />
        </Section>
      )}
      {resultRows.length > 0 && (
        <Section title={T(locale, '计算结果', 'Computed Results')}>
          <KVGrid rows={resultRows} />
        </Section>
      )}
    </>
  )
}

/** Readable assumption-provenance trail: a humanized label + the analyst-prose
 * explanation (the backend value is already prose carrying the value in correct
 * units — e.g. "34.4% (trailing 3yr EBITDA margin median)"). Replaces the flat
 * "16 fields" dead text that buried this sourcing layer. */
function ProvenanceList({
  provenance,
}: {
  provenance: Record<string, string>
}): React.ReactElement {
  const rows = Object.entries(provenance).filter(
    ([, v]) => typeof v === 'string' && v.trim() !== '',
  )
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-sm)',
        overflow: 'hidden',
      }}
    >
      {rows.map(([key, value], i) => (
        <div
          key={key}
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(140px, 200px) 1fr',
            gap: 16,
            padding: '10px 14px',
            background: i % 2 === 0 ? 'var(--surface-2)' : 'transparent',
            borderTop: i === 0 ? undefined : '1px solid var(--border-faint)',
          }}
        >
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              color: 'var(--text-muted)',
            }}
          >
            {humanizeKey(key)}
          </span>
          <span style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--text-secondary)' }}>
            {value}
          </span>
        </div>
      ))}
    </div>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}): React.ReactElement {
  return (
    <section style={{ margin: '0 0 24px' }}>
      <h2
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: 'var(--text-muted)',
          margin: '0 0 12px',
          paddingBottom: 8,
          borderBottom: '1px solid var(--border)',
        }}
      >
        {title}
      </h2>
      {children}
    </section>
  )
}

function KVGrid({ rows }: { rows: KV[] }): React.ReactElement {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
        gap: '10px 24px',
      }}
    >
      {rows.map((r) => (
        <div
          key={r.key}
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 3,
            minWidth: 0,
            padding: '8px 12px',
            background: 'var(--surface-2)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{r.label}</span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 13,
              color: 'var(--text-primary)',
              wordBreak: 'break-word',
            }}
          >
            {r.value}
          </span>
        </div>
      ))}
    </div>
  )
}
