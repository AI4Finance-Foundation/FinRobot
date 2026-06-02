/**
 * VersionDiffBanner — inline "what changed vs a prior version" banner shown in
 * the report's conclusion area. Replaces the old fixed-modal field-level
 * ArtifactDiff (raw schema-path JSON diff).
 *
 * It fetches GET /api/artifacts/{base}/diff/{current} → SemanticDelta and renders
 * the analyst-grade answer: conclusion moves (rating / target / upside / DCF fair
 * value), a one-line deterministic attribution of the fair-value change, and — on
 * expand — the driver assumptions, the comparability gate, and the data snapshot
 * footnote. All numbers arrive pre-formatted with backend-owned units; this
 * component never guesses a unit or currency (that bug is why the old one died).
 *
 * Default base = the version the current report was re-run from
 * (meta.parent_artifact_id); falls back to the most recent prior same-type
 * version by created_at. The base is changeable via the dropdown. a/b are
 * ordered by created_at so "old → new" stays meaningful whichever is picked.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { fetchWithTimeout, HEAVY_API_TIMEOUT_MS } from '../api/fetch'
import { useI18n } from '../i18n'
import { formatDate } from '../utils/format'
import { FetchHttpError } from '../utils/errorMessage'
import type { ArtifactSummaryV5 } from '../types/v5'

// ── SemanticDelta mirror (finrobot/artifact/semantic_diff.py) ───────────────

type Direction = 'up' | 'down' | 'flat' | 'added' | 'removed'
type Sentiment = 'positive' | 'negative' | 'neutral'

interface DeltaItem {
  key: string
  label_zh: string
  label_en: string
  old_value: number | string | null
  new_value: number | string | null
  formatted_old: string
  formatted_new: string
  pct_change: number | null
  formatted_pct_change: string | null
  direction: Direction
  sentiment: Sentiment
  comparable: boolean
  caliber_note: string | null
  is_user_override: boolean
  contribution: number | null
  formatted_contribution: string | null
}

interface AttributionItem {
  driver_key: string
  label_zh: string
  label_en: string
  contribution: number
  formatted_contribution: string
}

interface Attribution {
  available: boolean
  disabled_reason: string | null
  items: AttributionItem[]
  total_change: number
  formatted_total: string
  residual: number
  formatted_residual: string
  summary_zh: string
  summary_en: string
}

interface ComparabilityFlag {
  kind: 'formula' | 'data_source' | 'period'
  message_zh: string
  message_en: string
  blocks_attribution: boolean
}

interface DataFootnote {
  a_source: string
  b_source: string
  a_fetched_at: string
  b_fetched_at: string
  currency: string | null
  currency_assumed: boolean
}

interface SemanticDelta {
  a_id: string
  b_id: string
  a_label: string
  b_label: string
  report_type: string
  identical: boolean
  conclusion: DeltaItem[]
  attribution: Attribution
  drivers: DeltaItem[]
  comparability: ComparabilityFlag[]
  data_footnote: DataFootnote
}

// ── Chrome strings (backend drives the data strings; only labels are local) ──

const CHROME = {
  zh: {
    base: '对比基准',
    expand: '展开看为什么',
    collapse: '收起',
    colDriver: '驱动',
    colChange: '变化',
    colContribution: '对公允价值',
    snapshot: '数据快照',
    currencyAssumed: '货币假定 USD（数据未带币种标记）',
    identical: '结论与基准一致',
    residual: '交互项 / 数据重估',
    override: '手改',
    loading: '加载对比…',
    loadError: '加载对比失败',
  },
  en: {
    base: 'Compare against',
    expand: 'Why it changed',
    collapse: 'Collapse',
    colDriver: 'Driver',
    colChange: 'Change',
    colContribution: 'To fair value',
    snapshot: 'Data snapshot',
    currencyAssumed: 'Currency assumed USD (data carried no currency tag)',
    identical: 'Conclusion unchanged vs base',
    residual: 'Interaction / data re-basing',
    override: 'override',
    loading: 'Loading comparison…',
    loadError: 'Failed to load comparison',
  },
} as const

function sentimentColor(s: Sentiment): string {
  if (s === 'positive') return 'var(--positive)'
  if (s === 'negative') return 'var(--negative)'
  return 'var(--text-secondary)'
}

function arrow(d: Direction): string {
  if (d === 'up') return '▲'
  if (d === 'down') return '▼'
  return '→'
}

export interface VersionDiffBannerProps {
  currentId: string
  currentCreatedAt: string | null
  reportType: string
  parentArtifactId: string | null
  timeline: ArtifactSummaryV5[]
}

export function VersionDiffBanner({
  currentId,
  currentCreatedAt,
  reportType,
  parentArtifactId,
  timeline,
}: VersionDiffBannerProps): React.ReactElement | null {
  const { locale } = useI18n()
  const c = CHROME[locale]
  const [expanded, setExpanded] = useState(false)

  // Same-type prior/other versions, newest first.
  const candidates = useMemo(
    () =>
      (timeline ?? [])
        .filter((a) => a.type === reportType && a.id !== currentId)
        .slice()
        .sort((x, y) => (x.created_at < y.created_at ? 1 : -1)),
    [timeline, reportType, currentId],
  )

  const defaultBaseId = useMemo(() => {
    if (parentArtifactId && candidates.some((a) => a.id === parentArtifactId)) {
      return parentArtifactId
    }
    return candidates[0]?.id ?? null
  }, [parentArtifactId, candidates])

  // Hold only the analyst's explicit pick. The component instance is reused
  // across artifact navigations (same React position), so a raw useState seeded
  // from defaultBaseId would keep the *previous* report's base — see
  // BUG-20260602-006. We derive the effective base instead: an explicit pick is
  // honored only while it still names a candidate of the current report;
  // otherwise we fall back to the current report's default.
  const [pickedBaseId, setPickedBaseId] = useState<string | null>(null)
  const effectiveBaseId =
    pickedBaseId !== null && candidates.some((a) => a.id === pickedBaseId)
      ? pickedBaseId
      : defaultBaseId
  const setBaseId = setPickedBaseId

  // Order a (older) / b (newer) by created_at so "old → new" stays correct
  // regardless of which version the analyst selected as the base.
  const baseSummary = candidates.find((a) => a.id === effectiveBaseId) ?? null
  const { aId, bId } = useMemo(() => {
    if (!effectiveBaseId) return { aId: null, bId: null }
    const baseTs = baseSummary?.created_at ?? ''
    const curTs = currentCreatedAt ?? ''
    return baseTs <= curTs
      ? { aId: effectiveBaseId, bId: currentId }
      : { aId: currentId, bId: effectiveBaseId }
  }, [effectiveBaseId, baseSummary, currentCreatedAt, currentId])

  const { data, isLoading, error } = useQuery<SemanticDelta>({
    queryKey: ['semantic-diff', aId, bId],
    queryFn: async () => {
      const resp = await fetchWithTimeout(
        `${BASE_URL}/api/artifacts/${aId}/diff/${bId}`,
        {},
        HEAVY_API_TIMEOUT_MS,
      )
      if (!resp.ok) throw new FetchHttpError(resp.status, resp.statusText)
      return resp.json() as Promise<SemanticDelta>
    },
    enabled: aId !== null && bId !== null,
    staleTime: 60 * 1000,
  })

  // No prior version → no banner (single-version reports show nothing).
  if (candidates.length === 0) return null

  const label_ = (it: { label_zh: string; label_en: string }) =>
    locale === 'zh' ? it.label_zh : it.label_en

  return (
    <div
      data-testid="version-diff-banner"
      style={{
        marginBottom: 20,
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-md, 10px)',
        background: 'var(--surface)',
        overflow: 'hidden',
      }}
    >
      {/* Header: heading + base selector */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          flexWrap: 'wrap',
          padding: '10px 14px',
          borderBottom: '1px solid var(--border-subtle, var(--border))',
        }}
      >
        <span
          style={{
            fontSize: '0.7rem',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            color: 'var(--text-muted)',
          }}
        >
          {c.base}
        </span>
        <select
          value={effectiveBaseId ?? ''}
          onChange={(e) => setBaseId(e.target.value)}
          style={{
            background: 'var(--elevated, var(--surface))',
            color: 'var(--text-primary)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--r-sm, 6px)',
            padding: '3px 8px',
            fontSize: '0.8rem',
            maxWidth: 280,
          }}
        >
          {candidates.map((a) => (
            <option key={a.id} value={a.id}>
              {formatDate(a.created_at, locale, 'short')}
              {a.verdict ? ` · ${a.verdict}` : ''}
            </option>
          ))}
        </select>
      </div>

      <div style={{ padding: '12px 14px' }}>
        {isLoading && (
          <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>{c.loading}</div>
        )}
        {error && (
          <div style={{ color: 'var(--negative)', fontSize: '0.85rem' }}>{c.loadError}</div>
        )}

        {data && data.identical && (
          <div style={{ color: 'var(--positive)', fontWeight: 600, fontSize: '0.9rem' }}>
            ✓ {c.identical}
          </div>
        )}

        {data && !data.identical && (
          <>
            {/* A-section: conclusion chips */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 18, alignItems: 'flex-end' }}>
              {data.conclusion.map((it) => (
                <div key={it.key} style={{ minWidth: 96 }}>
                  <div
                    style={{
                      fontSize: '0.68rem',
                      color: 'var(--text-muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.04em',
                      marginBottom: 3,
                    }}
                  >
                    {label_(it)}
                  </div>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      fontFamily: 'var(--font-mono)',
                      fontSize: it.key === 'target_price' ? '1.05rem' : '0.92rem',
                    }}
                  >
                    <span style={{ color: 'var(--text-muted)' }}>{it.formatted_old}</span>
                    <span style={{ color: 'var(--text-muted)' }}>{arrow(it.direction)}</span>
                    <span style={{ color: sentimentColor(it.sentiment), fontWeight: 600 }}>
                      {it.formatted_new}
                    </span>
                    {it.formatted_pct_change !== null && (
                      <span style={{ color: sentimentColor(it.sentiment), fontSize: '0.78rem' }}>
                        ({it.formatted_pct_change})
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Attribution one-liner */}
            {data.attribution.available && data.attribution.summary_zh && (
              <div style={{ marginTop: 12, fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                {locale === 'zh' ? data.attribution.summary_zh : data.attribution.summary_en}
              </div>
            )}
            {!data.attribution.available && data.attribution.disabled_reason && (
              <div style={{ marginTop: 12, fontSize: '0.82rem', color: 'var(--warning)' }}>
                ⚠ {data.attribution.disabled_reason}
              </div>
            )}

            {/* Comparability flags */}
            {data.comparability.map((f, i) => (
              <div
                key={`${f.kind}-${i}`}
                style={{ marginTop: 8, fontSize: '0.8rem', color: 'var(--warning)' }}
              >
                ⚠ {locale === 'zh' ? f.message_zh : f.message_en}
              </div>
            ))}

            {/* Expand toggle */}
            <button
              onClick={() => setExpanded((v) => !v)}
              style={{
                marginTop: 12,
                background: 'none',
                border: 'none',
                color: 'var(--accent)',
                cursor: 'pointer',
                fontSize: '0.82rem',
                padding: 0,
              }}
            >
              {expanded ? `▾ ${c.collapse}` : `▸ ${c.expand}`}
            </button>

            {expanded && (
              <div style={{ marginTop: 12 }}>
                {/* B-section: drivers */}
                {data.drivers.length > 0 && (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                    <thead>
                      <tr>
                        {[c.colDriver, c.colChange, c.colContribution].map((h, i) => (
                          <th
                            key={h}
                            style={{
                              textAlign: i === 0 ? 'left' : 'right',
                              padding: '4px 8px',
                              color: 'var(--text-muted)',
                              fontWeight: 600,
                              fontSize: '0.7rem',
                              textTransform: 'uppercase',
                              borderBottom: '1px solid var(--border)',
                            }}
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.drivers.map((d) => {
                        const attr = data.attribution.items.find((a) => a.driver_key === d.key)
                        return (
                          <tr
                            key={d.key}
                            style={{
                              borderBottom: '1px solid var(--border-subtle, var(--border))',
                            }}
                          >
                            <td style={{ padding: '5px 8px' }}>
                              {label_(d)}
                              {d.is_user_override && (
                                <span
                                  style={{
                                    marginLeft: 6,
                                    fontSize: '0.62rem',
                                    padding: '1px 4px',
                                    borderRadius: 3,
                                    background:
                                      'color-mix(in srgb, var(--accent) 18%, transparent)',
                                    color: 'var(--accent)',
                                  }}
                                >
                                  {c.override}
                                </span>
                              )}
                              {d.caliber_note && (
                                <span
                                  style={{
                                    marginLeft: 6,
                                    fontSize: '0.7rem',
                                    color: 'var(--warning)',
                                  }}
                                >
                                  · {d.caliber_note}
                                </span>
                              )}
                            </td>
                            <td
                              style={{
                                padding: '5px 8px',
                                textAlign: 'right',
                                fontFamily: 'var(--font-mono)',
                                color: 'var(--text-secondary)',
                              }}
                            >
                              {d.formatted_old} {arrow(d.direction)}{' '}
                              <span style={{ color: sentimentColor(d.sentiment) }}>
                                {d.formatted_new}
                              </span>
                            </td>
                            <td
                              style={{
                                padding: '5px 8px',
                                textAlign: 'right',
                                fontFamily: 'var(--font-mono)',
                                color: attr
                                  ? attr.contribution >= 0
                                    ? 'var(--positive)'
                                    : 'var(--negative)'
                                  : 'var(--text-muted)',
                              }}
                            >
                              {attr ? attr.formatted_contribution : '—'}
                            </td>
                          </tr>
                        )
                      })}
                      {data.attribution.available &&
                        Math.abs(data.attribution.residual) > 0.005 && (
                          <tr>
                            <td style={{ padding: '5px 8px', color: 'var(--text-muted)' }}>
                              {c.residual}
                            </td>
                            <td />
                            <td
                              style={{
                                padding: '5px 8px',
                                textAlign: 'right',
                                fontFamily: 'var(--font-mono)',
                                color: 'var(--text-muted)',
                              }}
                            >
                              {data.attribution.formatted_residual}
                            </td>
                          </tr>
                        )}
                    </tbody>
                  </table>
                )}

                {/* Footnote */}
                <div style={{ marginTop: 10, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                  {c.snapshot}: {data.data_footnote.a_source}{' '}
                  {formatDate(data.data_footnote.a_fetched_at, locale, 'short')} →{' '}
                  {data.data_footnote.b_source}{' '}
                  {formatDate(data.data_footnote.b_fetched_at, locale, 'short')}
                  {data.data_footnote.currency_assumed && <> · {c.currencyAssumed}</>}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
