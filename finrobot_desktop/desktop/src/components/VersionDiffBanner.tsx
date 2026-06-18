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
import { formatCurrency, formatDate } from '../utils/format'
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
  kind: 'formula' | 'data_source' | 'period' | 'peer_set' | 'method_set'
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
  // False when the only moves are sub-materiality drift (live price tick, fresh
  // data) — the thesis stands. Drives the "结论实质未变" note so a re-run of the
  // same name doesn't read as a change.
  material_change: boolean
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
    immaterial: '结论实质未变 · 仅数据微调',
    archived: '已归档',
    targetRange: '目标区间',
    pointTargetWithheld: '点目标价已隐藏',
    fairUnavailable: '不可归因',
    // Withheld-target state: DCF fair value is withheld (—→—) so it can't be
    // attributed; the attributable signal is the market-implied growth shift
    // above. Demote the fair-value row to this footnote instead of a blank chip.
    fairNotAttributable: '目标价已隐藏，无 DCF 公允价值可归因 — 改看上方市场隐含增长的变化',
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
    immaterial: 'No material change · live data re-based',
    archived: 'archived',
    targetRange: 'Target range',
    pointTargetWithheld: 'Point target withheld',
    fairUnavailable: 'not attributable',
    fairNotAttributable:
      'Fair value not attributable when the target is withheld — track the market-implied growth shift above instead',
  },
} as const

function arrow(d: Direction): string {
  if (d === 'up') return '▲'
  if (d === 'down') return '▼'
  return '→'
}

function sentimentToneClass(s: Sentiment): string {
  if (s === 'positive') return 'version-diff-tone--positive'
  if (s === 'negative') return 'version-diff-tone--negative'
  return 'version-diff-tone--neutral'
}

function directionToneClass(d: Direction): string {
  if (d === 'up' || d === 'added') return 'version-diff-tone--positive'
  if (d === 'down' || d === 'removed') return 'version-diff-tone--negative'
  return 'version-diff-tone--muted'
}

function verdictToneClass(value: string): string {
  const v = value.toUpperCase()
  if (v.includes('BUY')) return 'version-diff-tone--positive'
  if (v.includes('SELL')) return 'version-diff-tone--negative'
  if (v.includes('HOLD')) return 'version-diff-tone--target'
  return 'version-diff-tone--neutral'
}

function verdictRailClass(value: string): string {
  const v = value.toUpperCase()
  if (v.includes('BUY')) return 'version-diff-rail--positive'
  if (v.includes('SELL')) return 'version-diff-rail--negative'
  if (v.includes('HOLD')) return 'version-diff-rail--target'
  return 'version-diff-rail--muted'
}

function directionRailClass(d: Direction): string {
  if (d === 'up' || d === 'added') return 'version-diff-rail--positive'
  if (d === 'down' || d === 'removed') return 'version-diff-rail--negative'
  return 'version-diff-rail--muted'
}

function metricToneClass(it: DeltaItem): string {
  if (it.key === 'rating' || it.key === 'recommendation') return verdictToneClass(it.formatted_new)
  if (it.key === 'target_price') return 'version-diff-tone--target'
  if (it.key === 'current_price') return 'version-diff-tone--market'
  if (it.key === 'dcf_fair_value' || it.key === 'implied_price') return 'version-diff-tone--fair'
  // Reverse-DCF market-implied growth — the promoted, attributable row in the
  // withheld-target state. Amber (neutral-warning) — a rising market-implied
  // growth is neither good nor bad, it just raises the bar, never 涨绿跌红.
  if (it.key === 'implied_growth') return 'version-diff-tone--review'
  return sentimentToneClass(it.sentiment)
}

function metricRailClass(it: DeltaItem): string {
  if (it.key === 'rating' || it.key === 'recommendation') return verdictRailClass(it.formatted_new)
  if (it.key === 'target_price') return 'version-diff-rail--target'
  if (it.key === 'current_price' || it.key === 'dcf_fair_value' || it.key === 'implied_price') {
    return 'version-diff-rail--market'
  }
  if (it.key === 'implied_growth') return 'version-diff-rail--review'
  return directionRailClass(it.direction)
}

export interface VersionDiffBannerProps {
  currentId: string
  currentCreatedAt: string | null
  reportType: string
  parentArtifactId: string | null
  timeline: ArtifactSummaryV5[]
  currentTargetRange?: { low: number | null; high: number | null; currency: string } | null
  currentTargetWithheld?: boolean
}

export function VersionDiffBanner({
  currentId,
  currentCreatedAt,
  reportType,
  parentArtifactId,
  timeline,
  currentTargetRange,
  currentTargetWithheld = false,
}: VersionDiffBannerProps): React.ReactElement | null {
  const { locale } = useI18n()
  const c = CHROME[locale]
  // `open` = the whole card (default collapsed to a slim bar so it doesn't push
  // the report cover down); `expanded` = the inner driver-detail table.
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)

  // Same-type prior/other versions, newest first.
  const candidates = useMemo(
    () =>
      (timeline ?? [])
        .filter((a) => a.type === reportType && a.id !== currentId)
        .slice()
        // Sort by (created_at, id) so same-second ties are deterministic —
        // a bare created_at sort leaves the 'compare vs previous' base unstable
        // when two runs land in the same second. See BUG-023.
        .sort((x, y) => {
          if (x.created_at !== y.created_at) {
            return x.created_at < y.created_at ? 1 : -1
          }
          return x.id < y.id ? 1 : -1
        }),
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
  const currentTargetRangeLabel =
    currentTargetRange &&
    isFiniteNumber(currentTargetRange.low) &&
    isFiniteNumber(currentTargetRange.high)
      ? `${formatCurrency(currentTargetRange.low, currentTargetRange.currency, locale, 2)}–${formatCurrency(
          currentTargetRange.high,
          currentTargetRange.currency,
          locale,
          2,
        )}`
      : null

  // Collapsed by default — a slim bar so the version-diff card doesn't push the
  // report cover down. Opening it reveals the full conclusion / attribution card.
  const baseLabel = baseSummary
    ? `${formatDate(baseSummary.created_at, locale, 'short')}${
        baseSummary.verdict ? ` · ${baseSummary.verdict}` : ''
      }`
    : ''
  if (!open) {
    return (
      <div data-testid="version-diff-banner" className="version-diff-card">
        <button
          type="button"
          data-testid="version-diff-toggle"
          className="version-diff-card__summary"
          aria-expanded={false}
          onClick={() => setOpen(true)}
        >
          <span className="version-diff-card__eyebrow">{c.base}</span>
          {baseLabel && <span className="version-diff-card__summary-base">{baseLabel}</span>}
          <span className="version-diff-card__collapse" aria-hidden>
            ▸ {c.expand}
          </span>
        </button>
      </div>
    )
  }

  return (
    <div data-testid="version-diff-banner" className="version-diff-card">
      {/* Header: heading + base selector */}
      <div className="version-diff-card__header">
        <span className="version-diff-card__eyebrow">{c.base}</span>
        <select
          className="version-diff-card__select"
          value={effectiveBaseId ?? ''}
          onChange={(e) => setBaseId(e.target.value)}
        >
          {candidates.map((a) => (
            <option key={a.id} value={a.id}>
              {formatDate(a.created_at, locale, 'short')}
              {a.verdict ? ` · ${a.verdict}` : ''}
              {/* Mark retired (stale-archived) base candidates (BUG-055). */}
              {a.archived ? ` · ${c.archived}` : ''}
            </option>
          ))}
        </select>
        <button
          type="button"
          data-testid="version-diff-toggle"
          className="version-diff-card__collapse"
          aria-expanded
          onClick={() => setOpen(false)}
        >
          ▾ {c.collapse}
        </button>
      </div>

      <div className="version-diff-card__body">
        {isLoading && <div className="version-diff-card__state">{c.loading}</div>}
        {error && (
          <div className="version-diff-card__state version-diff-tone--negative">{c.loadError}</div>
        )}

        {data && data.identical && (
          <div className="version-diff-card__state version-diff-tone--positive">
            ✓ {c.identical}
          </div>
        )}

        {/* Not bit-identical, but every move is sub-materiality drift — say so up
            front so a same-name re-run doesn't read as a thesis change. The chips
            below still show the small moves for the analyst who wants them. */}
        {data && !data.identical && !data.material_change && (
          <div
            className="version-diff-card__state version-diff-tone--muted"
            data-testid="version-diff-immaterial"
          >
            ≈ {c.immaterial}
          </div>
        )}

        {data && !data.identical && (
          <>
            {(() => {
              // Withheld-target demotion: when the reverse-DCF growth row is the
              // attributable headline and the DCF fair value is withheld (—→—), the fair-value row
              // stops being a blank prominent chip — it drops to a quiet footnote that
              // redirects the analyst to the growth shift. The "缺少 DCF 公允价值" attribution
              // warning becomes redundant with that footnote, so it's suppressed too.
              const hasGrowthRow = data.conclusion.some((it) => it.key === 'implied_growth')
              const isFairWithheld = (it: DeltaItem): boolean =>
                (it.key === 'implied_price' || it.key === 'dcf_fair_value') &&
                it.old_value === null &&
                it.new_value === null
              const isTargetPointWithheld = (it: DeltaItem): boolean =>
                it.key === 'target_price' && it.old_value === null && it.new_value === null
              const demoteFair = hasGrowthRow
              const showTargetRangeChip =
                currentTargetWithheld &&
                currentTargetRangeLabel !== null &&
                data.conclusion.some(isTargetPointWithheld)
              const primaryChipsBeforeTargetRange = demoteFair
                ? data.conclusion.filter((it) => !isFairWithheld(it))
                : data.conclusion
              const primaryChips = showTargetRangeChip
                ? primaryChipsBeforeTargetRange.filter((it) => !isTargetPointWithheld(it))
                : primaryChipsBeforeTargetRange
              const demotedFair = demoteFair ? data.conclusion.find(isFairWithheld) : undefined
              return (
                <>
                  {/* A-section: conclusion chips */}
                  <div className="version-diff-metrics">
                    {showTargetRangeChip && (
                      <div
                        className="version-diff-metric version-diff-metric--target_price version-diff-rail--target"
                        data-testid="diff-target-range"
                        data-key="target_range"
                      >
                        <div className="version-diff-metric__label">{c.targetRange}</div>
                        <div className="version-diff-metric__row">
                          <span className="version-diff-metric__new version-diff-tone--target">
                            {currentTargetRangeLabel}
                          </span>
                          <span className="version-diff-metric__note">
                            · {c.pointTargetWithheld}
                          </span>
                        </div>
                      </div>
                    )}
                    {primaryChips.map((it) => (
                      <div
                        key={it.key}
                        className={`version-diff-metric version-diff-metric--${it.key} ${metricRailClass(it)}`}
                        data-key={it.key}
                      >
                        <div className="version-diff-metric__label">{label_(it)}</div>
                        <div className="version-diff-metric__row">
                          <span className="version-diff-metric__old">{it.formatted_old}</span>
                          <span className="version-diff-metric__arrow">{arrow(it.direction)}</span>
                          <span className={`version-diff-metric__new ${metricToneClass(it)}`}>
                            {it.formatted_new}
                          </span>
                          {it.formatted_pct_change !== null && (
                            <span
                              className={`version-diff-metric__pct ${directionToneClass(it.direction)}`}
                            >
                              ({it.formatted_pct_change})
                            </span>
                          )}
                          {it.caliber_note && (
                            <span className="version-diff-metric__note">· {it.caliber_note}</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Demoted fair-value footnote (was a blank —→— chip) */}
                  {demotedFair && (
                    <div
                      className="version-diff-card__footnote-demoted"
                      data-testid="diff-fair-demoted"
                    >
                      <span className="version-diff-card__demoted-key">{label_(demotedFair)}</span>
                      <span className="version-diff-card__demoted-dash">{c.fairUnavailable}</span>
                      <span>{c.fairNotAttributable}</span>
                    </div>
                  )}

                  {/* Attribution one-liner */}
                  {data.attribution.available && data.attribution.summary_zh && (
                    <div className="version-diff-card__summary">
                      {locale === 'zh' ? data.attribution.summary_zh : data.attribution.summary_en}
                    </div>
                  )}
                  {!data.attribution.available &&
                    data.attribution.disabled_reason &&
                    !demoteFair && (
                      <div className="version-diff-card__warning">
                        ⚠ {data.attribution.disabled_reason}
                      </div>
                    )}
                </>
              )
            })()}

            {/* Comparability flags */}
            {data.comparability.map((f, i) => (
              <div key={`${f.kind}-${i}`} className="version-diff-card__warning">
                ⚠ {locale === 'zh' ? f.message_zh : f.message_en}
              </div>
            ))}

            {/* Expand toggle */}
            <button
              type="button"
              className="version-diff-card__expand"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? `▾ ${c.collapse}` : `▸ ${c.expand}`}
            </button>

            {expanded && (
              <div className="version-diff-detail">
                {/* B-section: drivers */}
                {data.drivers.length > 0 && (
                  <table className="version-diff-table">
                    <thead>
                      <tr>
                        {[c.colDriver, c.colChange, c.colContribution].map((h, i) => (
                          <th key={h} className={i === 0 ? undefined : 'version-diff-table__num'}>
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.drivers.map((d) => {
                        const attr = data.attribution.items.find((a) => a.driver_key === d.key)
                        return (
                          <tr key={d.key}>
                            <td>
                              {label_(d)}
                              {d.is_user_override && (
                                <span className="version-diff-table__tag">{c.override}</span>
                              )}
                              {d.caliber_note && (
                                <span className="version-diff-table__note">· {d.caliber_note}</span>
                              )}
                            </td>
                            <td className="version-diff-table__num">
                              {d.formatted_old} {arrow(d.direction)}{' '}
                              <span className={sentimentToneClass(d.sentiment)}>
                                {d.formatted_new}
                              </span>
                            </td>
                            <td
                              className={`version-diff-table__num ${
                                attr
                                  ? attr.contribution >= 0
                                    ? 'version-diff-tone--positive'
                                    : 'version-diff-tone--negative'
                                  : 'version-diff-tone--muted'
                              }`}
                            >
                              {attr ? attr.formatted_contribution : '—'}
                            </td>
                          </tr>
                        )
                      })}
                      {data.attribution.available &&
                        Math.abs(data.attribution.residual) > 0.005 && (
                          <tr>
                            <td className="version-diff-tone--muted">{c.residual}</td>
                            <td />
                            <td className="version-diff-table__num version-diff-tone--muted">
                              {data.attribution.formatted_residual}
                            </td>
                          </tr>
                        )}
                    </tbody>
                  </table>
                )}

                {/* Footnote */}
                <div className="version-diff-footnote">
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

function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}
