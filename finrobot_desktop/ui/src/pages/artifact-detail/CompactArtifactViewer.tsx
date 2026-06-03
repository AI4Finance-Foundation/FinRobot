// CompactArtifactViewer — the detail body for NON equity_research artifacts
// (dcf / lbo / ddm / comps / earnings / ic_memo / peer_research / ad_hoc).
//
// These artifacts are single deterministic computations, not 13-chapter
// reports. Forcing them through ReportChapters renders a mostly-empty equity
// shell (empty thesis/valuation/ownership chapters) — see BUG-20260602-039.
// Instead we show what the artifact ACTUALLY carries:
//   - a type-aware headline number (DCF→implied price, DDM→equity value/sh,
//     LBO→IRR·MOIC, comps→median multiples, earnings→beat rate)
//   - its inputs / assumptions (assumptions.parameters)
//   - its result key numbers (outputs.structured, generic flatten)
//   - its summary text + warnings
//   - an audit / provenance trail (created_at · source · data_source ·
//     compute version · formula id)
//
// It is a generic structured-data renderer with just enough type-awareness to
// label the headline; the long tail (ad_hoc, future types) degrades to a clean
// flattened key/value grid rather than an empty page.

import type { ArtifactDetail } from '../../hooks/useV5Artifacts'
import { useI18n, type Locale } from '../../i18n'
import { formatCurrency, formatPercent, formatDate, formatCompactNumber } from '../../utils/format'

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
  /** Optional secondary stat shown next to the headline (e.g. MOIC next to IRR). */
}

const T = (locale: Locale, zh: string, en: string): string => (locale === 'zh' ? zh : en)

function isPlainNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

/** Pretty-print a snake_case key as a Title-ish label, locale-agnostic. */
function humanizeKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bPe\b/g, 'P/E')
    .replace(/\bEv\b/g, 'EV')
    .replace(/\bEbitda\b/g, 'EBITDA')
    .replace(/\bIrr\b/g, 'IRR')
    .replace(/\bMoic\b/g, 'MOIC')
    .replace(/\bWacc\b/g, 'WACC')
    .replace(/\bDcf\b/g, 'DCF')
    .replace(/\bLbo\b/g, 'LBO')
    .replace(/\bDps\b/g, 'DPS')
    .replace(/\bPct\b/g, '%')
}

/** Render a scalar value for the generic grid. Arrays/objects are summarized. */
function renderScalar(v: unknown, locale: Locale): string | null {
  if (v === null || v === undefined) return null
  if (typeof v === 'boolean') return v ? T(locale, '是', 'Yes') : T(locale, '否', 'No')
  if (typeof v === 'string') return v.trim() === '' ? null : v
  if (isPlainNumber(v)) {
    // Large magnitudes → compact; otherwise plain with 2 decimals.
    if (Math.abs(v) >= 1e6) return formatCompactNumber(v, locale)
    return new Intl.NumberFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
      maximumFractionDigits: 4,
    }).format(v)
  }
  if (Array.isArray(v)) {
    if (v.length === 0) return null
    if (v.every((x) => isPlainNumber(x) || typeof x === 'string')) {
      return v
        .slice(0, 8)
        .map((x) => (isPlainNumber(x) ? renderScalar(x, locale) : String(x)))
        .join(', ')
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

/** Flatten a structured dict into displayable key/value rows (one level deep). */
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
      const irr = num('irr')
      if (irr !== undefined) stats.push({ label: 'IRR', value: formatPercent(irr, locale) })
      const moic = num('moic')
      if (moic !== undefined)
        stats.push({
          label: 'MOIC',
          value: `${moic.toFixed(2)}×`,
        })
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
        stats.push({
          label: T(locale, '连续超预期', 'Consecutive Beats'),
          value: String(streak),
        })
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
  const headline = deriveHeadline(artifact.type, structured, locale)

  const inputRows = flatten(assumptions.parameters, locale)
  // For ic_memo the top level is { dcf_result, lbo_result } — surface their
  // scalars one level deeper so the result grid isn't just "N fields, N fields".
  const resultSource: Record<string, unknown> =
    artifact.type === 'ic_memo'
      ? {
          ...((structured.dcf_result as Record<string, unknown>) ?? {}),
          ...((structured.lbo_result as Record<string, unknown>) ?? {}),
        }
      : structured
  const resultRows = flatten(resultSource, locale)

  const warnings = [...(outputs.warnings ?? []), ...(cv?.formula_warnings ?? [])]
  const summaryText = (outputs.summary_text ?? '').trim()

  return (
    <main data-testid="compact-artifact-viewer" style={{ minWidth: 0, padding: '12px 0 60px' }}>
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
          {typeLabel(artifact.type, locale)}
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
          {typeLabel(artifact.type, locale)}
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
              </div>
            ))}
          </div>
        )}
      </header>

      {summaryText && (
        <Section title={T(locale, '摘要', 'Summary')}>
          <p
            style={{
              fontSize: 13.5,
              lineHeight: 1.7,
              color: 'var(--text-secondary)',
              margin: 0,
              whiteSpace: 'pre-wrap',
            }}
          >
            {summaryText}
          </p>
        </Section>
      )}

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

      {warnings.length > 0 && (
        <section
          data-testid="compact-warnings"
          style={{
            margin: '24px 0',
            padding: '14px 18px',
            background: 'color-mix(in srgb, var(--warning) 6%, transparent)',
            border: '1px solid color-mix(in srgb, var(--warning) 32%, transparent)',
            borderRadius: 'var(--radius-sm)',
            fontSize: 12,
            color: 'var(--warning)',
          }}
        >
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              letterSpacing: '0.08em',
              marginBottom: 6,
            }}
          >
            ⚠ {T(locale, '计算警告', 'Compute Warnings')}
          </div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {warnings.map((w, i) => (
              <li key={i} style={{ marginBottom: 4 }}>
                {w}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Audit / provenance trail */}
      <Section title={T(locale, '审计溯源', 'Audit & Provenance')}>
        <KVGrid
          rows={[
            {
              key: 'created_at',
              label: T(locale, '生成时间', 'Created'),
              value: meta.created_at ? formatDate(meta.created_at, locale, 'datetime') : '—',
            },
            {
              key: 'source',
              label: T(locale, '来源', 'Source'),
              value: meta.source ?? '—',
            },
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
            {
              key: 'artifact_id',
              label: 'Artifact ID',
              value: artifact.id,
            },
          ]}
        />
      </Section>
    </main>
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
