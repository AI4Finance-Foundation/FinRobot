// Chapter 12 — Ownership & Governance. Four sub-blocks:
//   1. Insider Transactions (Form 4)        — flat row table
//   2. Institutional Holdings (13F top N)   — flat row table
//   3. Proxy Compensation (DEF 14A)         — KvGrid of CEO comp + pay ratio
//   4. Schedule 13D/G Alerts                — list of 5%+ shareholder events
//
// Every number here came from SEC EDGAR via EdgarTools (Form 4 / 13F-HR /
// DEF 14A / 13D / 13G). `degraded_sections` marks any sub-block whose data
// source was unavailable at run-time (e.g. 13F cache empty) so we render a
// dedicated cold-state placeholder instead of a misleading empty table.
//
// When the artifact has no ownership_governance at all (older runs, or
// runs where SEC identity wasn't configured), we render a single chapter-
// level callout pointing the user at /settings to set their SEC identity.

import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'

import { Chapter, SubChapter, TableScroll, tableStyle } from './ChapterBase'
import { MetricModule, type MetricCell } from './MetricModule'
import type {
  FilingProvenanceShape,
  InsiderTransactionShape,
  InsiderTransactionType,
  InstitutionalHoldingShape,
  OwnershipDegradedReason,
  OwnershipGovernanceShape,
  ProxyCompensationShape,
  ScheduleThirteenAlertShape,
} from './types'
import { useI18n } from '../../../i18n'
import { TermTip } from '../../../components/TermTip'
import {
  formatCompactNumber,
  formatCurrencyCompact,
  formatDate,
  formatPercent,
} from '../../../utils/format'

interface Props {
  ownership: OwnershipGovernanceShape | null
  // CEO compensation → reporting currency (BUG-030). Insider Form-4 / 13F
  // values stay USD (SEC EDGAR is USD-denominated; the holding field is even
  // named value_usd), so those use a literal 'USD' at their call sites.
  reportingCurrency: string
}

export function ChapterOwnershipGovernance({
  ownership,
  reportingCurrency,
}: Props): React.ReactElement {
  const { t, locale } = useI18n()

  // No ownership_governance block at all → SEC identity unconfigured or this
  // is a pre-EdgarTools-integration artifact. Show a single chapter-level CTA.
  if (!ownership) {
    return (
      <Chapter id="ownership">
        <div style={emptyChapterCallout}>
          <div style={emptyChapterCalloutTitle}>{t('chapter.ownership.empty.title')}</div>
          <p style={emptyChapterCalloutBody}>{t('chapter.ownership.empty.body')}</p>
          <Link to="/settings" style={emptyChapterCalloutCta}>
            {t('chapter.ownership.empty.cta')}
          </Link>
        </div>
      </Chapter>
    )
  }

  const degraded = new Set(ownership.degraded_sections ?? [])
  const reasons = ownership.degraded_reasons ?? {}
  const insiders = ownership.insider_transactions ?? []
  const holdings = ownership.institutional_holdings ?? []
  const compensationRaw = ownership.proxy_compensation ?? null
  const compensation = sanitizeProxyCompensation(compensationRaw)
  const compensationInvalid = compensationRaw !== null && compensation === null
  const alerts = ownership.schedule13_alerts ?? []

  const insidersReason = degradedReasonKey(
    'insiders',
    reasons['insider_transactions'],
    'chapter.ownership.degraded.insiders',
  )
  const institutionsReason = degradedReasonKey(
    'institutions',
    reasons['institutional_holdings'],
    'chapter.ownership.degraded.institutions',
  )
  const compensationReason = degradedReasonKey(
    'proxy',
    reasons['proxy_compensation'],
    'chapter.ownership.degraded.compensation',
  )

  // Lead the chapter with a glanceable aggregate strip over the cold tables
  // below — only for sections with non-degraded data to summarize.
  const showInsiderFlow = !degraded.has('insider_transactions') && insiders.length > 0
  const showConcentration = !degraded.has('institutional_holdings') && holdings.length > 0

  return (
    <Chapter id="ownership">
      {(showInsiderFlow || showConcentration) && (
        <OwnershipSignalStrip
          insiders={showInsiderFlow ? insiders : []}
          holdings={showConcentration ? holdings : []}
          locale={locale}
          t={t}
        />
      )}
      <SubChapter heading={t('chapter.ownership.heading.insiders')}>
        {degraded.has('insider_transactions') ? (
          <DegradedPlaceholder reason={t(insidersReason)} />
        ) : insiders.length > 0 ? (
          <InsiderTable rows={insiders} locale={locale} t={t} />
        ) : (
          <EmptyNote>{t('chapter.ownership.empty.insiders')}</EmptyNote>
        )}
      </SubChapter>

      <SubChapter
        heading={
          <>
            {t('chapter.ownership.heading.institutions')}{' '}
            <span style={{ fontSize: 10, verticalAlign: 'middle' }}>
              <TermTip term="13F" />
            </span>
          </>
        }
      >
        {degraded.has('institutional_holdings') ? (
          <DegradedPlaceholder
            reason={t(institutionsReason)}
            cta={{ to: '/settings', label: t('chapter.ownership.degraded.institutions.cta') }}
          />
        ) : holdings.length > 0 ? (
          <InstitutionTable rows={holdings} locale={locale} t={t} />
        ) : (
          <EmptyNote>{t('chapter.ownership.empty.institutions')}</EmptyNote>
        )}
      </SubChapter>

      <SubChapter heading={t('chapter.ownership.heading.compensation')}>
        {degraded.has('proxy_compensation') || compensationInvalid ? (
          <DegradedPlaceholder reason={t(compensationReason)} />
        ) : compensation ? (
          <CompensationGrid
            comp={compensation}
            locale={locale}
            t={t}
            reportingCurrency={reportingCurrency}
          />
        ) : (
          <EmptyNote>{t('chapter.ownership.empty.compensation')}</EmptyNote>
        )}
      </SubChapter>

      <SubChapter heading={t('chapter.ownership.heading.alerts')}>
        {degraded.has('schedule13_alerts') ? (
          <DegradedPlaceholder reason={t('chapter.ownership.degraded.alerts')} />
        ) : alerts.length > 0 ? (
          <AlertList rows={alerts} locale={locale} t={t} />
        ) : (
          <EmptyNote>{t('chapter.ownership.empty.alerts')}</EmptyNote>
        )}
      </SubChapter>
    </Chapter>
  )
}

// Maps backend reason code → reason-specific i18n key.
// Falls back to the section-generic key when reason is missing/unknown so
// the message remains accurate when backend can't pinpoint why data is gone.
function degradedReasonKey(
  section: 'insiders' | 'institutions' | 'proxy',
  reason: OwnershipDegradedReason | undefined,
  fallback: string,
): string {
  if (!reason) return fallback
  if (section === 'proxy') {
    return reason === 'parse_failed' ? 'chapter.ownership.degraded.proxy.parse_failed' : fallback
  }
  const reasonKeys: Record<OwnershipDegradedReason, string | null> = {
    identity_missing: `chapter.ownership.degraded.${section}.identity_missing`,
    no_recent_filings: `chapter.ownership.degraded.${section}.no_recent_filings`,
    fetch_error: `chapter.ownership.degraded.${section}.fetch_error`,
    parse_failed: null,
  }
  return reasonKeys[reason] ?? fallback
}

const CEO_COMP_MIN = 1_000_000
const CEO_COMP_MAX = 500_000_000
const CEO_TITLE_ONLY = new Set([
  'chief executive officer',
  'ceo',
  'ceo chief executive officer',
  'chief executive officer ceo',
])

function sanitizeProxyCompensation(
  comp: ProxyCompensationShape | null,
): ProxyCompensationShape | null {
  if (!comp) return null
  const ceoName = sanitizeCeoName(comp.ceo_name)
  const ceoTotalCompensation = sanitizeCeoTotalCompensation(comp.ceo_total_compensation)
  const hasUsefulPayRatio = comp.ceo_pay_ratio !== null && comp.ceo_pay_ratio !== undefined
  if (ceoName === null && ceoTotalCompensation === null && !hasUsefulPayRatio) {
    return null
  }
  return {
    ...comp,
    ceo_name: ceoName,
    ceo_total_compensation: ceoTotalCompensation,
  }
}

function sanitizeCeoName(value: string | null | undefined): string | null {
  if (!value) return null
  const normalized = value.replace(/\s+/g, ' ').trim()
  if (!normalized) return null
  if (CEO_TITLE_ONLY.has(normalized.toLowerCase())) return null
  return normalized
}

function sanitizeCeoTotalCompensation(value: number | null | undefined): number | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null
  if (value < CEO_COMP_MIN || value > CEO_COMP_MAX) return null
  return value
}

// ---------------------------------------------------------------------------
// Sub-block: Insider Transactions
// ---------------------------------------------------------------------------

type Translator = (key: string, params?: Record<string, string | number>) => string

// ---------------------------------------------------------------------------
// Signal strip — a glanceable aggregate headline above the cold tables
// (Bloomberg leads its ownership tab with the aggregate, tables below). Pure
// client aggregation over data already shown; never a verdict.
// ---------------------------------------------------------------------------
function OwnershipSignalStrip({
  insiders,
  holdings,
  locale,
  t,
}: {
  insiders: InsiderTransactionShape[]
  holdings: InstitutionalHoldingShape[]
  locale: 'zh' | 'en'
  t: Translator
}): React.ReactElement | null {
  const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
  // Only open-market purchase/sale are directional. Grants (code A) / tax-
  // withholding (F) / option exercise (M) / gift (G) are compensation mechanics
  // and carry NO buy/sell signal — excluded from the net so a routine RSU grant
  // never reads as bullish insider buying (would be a fabricated signal).
  const sumOf = (type: string) =>
    insiders
      .filter((r) => r.transaction_type === type && finite(r.value))
      .reduce((s, r) => s + (r.value as number), 0)
  const buy = sumOf('purchase')
  const sell = sumOf('sale')
  const net = buy - sell
  const nonMarket = insiders.filter(
    (r) => r.transaction_type !== 'purchase' && r.transaction_type !== 'sale',
  ).length
  const hasFlow = insiders.length > 0 && (buy > 0 || sell > 0)
  const flowDenom = buy + sell || 1

  const vals = holdings
    .map((h) => h.value_usd)
    .filter(finite)
    .sort((a, b) => b - a)
  const total = vals.reduce((s, v) => s + v, 0)
  const topN = Math.min(5, vals.length)
  const topShare =
    total > 0 && topN > 0 ? vals.slice(0, topN).reduce((s, v) => s + v, 0) / total : null

  if (!hasFlow && topShare === null) return null

  const netColor = net > 0 ? 'var(--success)' : net < 0 ? 'var(--danger)' : 'var(--text-secondary)'

  return (
    <div style={signalStripWrap} data-testid="ownership-signal-strip">
      {hasFlow && (
        <div style={signalCell}>
          <div style={signalLabel}>{t('chapter.ownership.signal.insiderFlow')}</div>
          <div style={signalBarTrack}>
            <div style={{ width: `${(buy / flowDenom) * 100}%`, background: 'var(--success)' }} />
            <div style={{ width: `${(sell / flowDenom) * 100}%`, background: 'var(--danger)' }} />
          </div>
          <div style={signalFootRow}>
            <span style={{ color: netColor, fontWeight: 600 }}>
              {t('chapter.ownership.signal.net')} {net >= 0 ? '+' : '-'}
              {formatCurrencyCompact(Math.abs(net), 'USD', locale)}
            </span>
            <span style={{ color: 'var(--text-dim)' }}>
              {t('chapter.ownership.signal.nonMarketExcl', { n: nonMarket })}
            </span>
          </div>
        </div>
      )}
      {topShare !== null && (
        <div style={signalCell}>
          <div style={signalLabel}>{t('chapter.ownership.signal.concentration')}</div>
          <div style={signalBarTrack}>
            <div style={{ width: `${topShare * 100}%`, background: 'var(--primary)' }} />
          </div>
          <div style={signalFootRow}>
            <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
              {t('chapter.ownership.signal.topHolders', { n: topN })} {(topShare * 100).toFixed(0)}%
            </span>
            <span style={{ color: 'var(--text-dim)' }}>
              {t('chapter.ownership.signal.ofTotal')}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

const signalStripWrap: React.CSSProperties = {
  display: 'flex',
  gap: 16,
  flexWrap: 'wrap',
  marginBottom: 20,
}
const signalCell: React.CSSProperties = {
  flex: '1 1 240px',
  padding: '12px 16px',
  background: 'var(--bg-card-50)',
  border: '1px solid var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
}
const signalLabel: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  color: 'var(--text-muted)',
}
const signalBarTrack: React.CSSProperties = {
  display: 'flex',
  height: 8,
  borderRadius: 4,
  overflow: 'hidden',
  background: 'var(--bg-elevated)',
  margin: '8px 0',
}
const signalFootRow: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: 8,
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
}

function InsiderTable({
  rows,
  locale,
  t,
}: {
  rows: InsiderTransactionShape[]
  locale: 'zh' | 'en'
  t: Translator
}): React.ReactElement {
  // Sort descending by filing_date — most recent first
  const sorted = [...rows].sort((a, b) => (a.filing_date < b.filing_date ? 1 : -1)).slice(0, 12)
  return (
    <TableScroll>
      <table style={tableStyle}>
        <thead>
          <tr>
            <th style={thStyle}>{t('chapter.ownership.col.date')}</th>
            <th style={thStyle}>{t('chapter.ownership.col.name')}</th>
            <th style={thStyle}>{t('chapter.ownership.col.role')}</th>
            <th style={thStyle}>{t('chapter.ownership.col.transaction')}</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>{t('chapter.ownership.col.shares')}</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>{t('chapter.ownership.col.value')}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const isBuy = r.transaction_type === 'purchase'
            const isSell = r.transaction_type === 'sale'
            return (
              // index guards against identical (accession, insider, shares, value)
              // rows — a filer can report two matching lines in one Form 4.
              <tr key={`${r.accession_no}-${r.insider_name}-${r.shares}-${r.value}-${i}`}>
                <td style={tdStyle}>
                  <ProvenanceLink prov={r.provenance} locale={locale} t={t}>
                    {formatDate(r.filing_date, locale)}
                  </ProvenanceLink>
                </td>
                <td style={tdStyle}>{r.insider_name}</td>
                <td style={{ ...tdStyle, color: 'var(--text-muted)' }}>
                  {r.insider_position ?? '—'}
                </td>
                <td
                  style={{
                    ...tdStyle,
                    color: isBuy
                      ? 'var(--success)'
                      : isSell
                        ? 'var(--danger)'
                        : 'var(--text-muted)',
                    fontWeight: 500,
                  }}
                >
                  {transactionLabel(r.transaction_type, t)}
                </td>
                <td style={{ ...tdStyle, textAlign: 'right' }}>
                  {formatCompactNumber(r.shares, locale)}
                </td>
                <td style={{ ...tdStyle, textAlign: 'right' }}>
                  {/* Form 4 transaction value — SEC EDGAR, USD-denominated. */}
                  {r.value > 0 ? formatCurrencyCompact(r.value, 'USD', locale) : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </TableScroll>
  )
}

/** Maps Form 4 transaction_type → i18n key. The exhaustive `Record<...>` type
 * means TypeScript fails the build if backend adds a new enum variant without
 * a matching catalog entry — no silent fallthrough. Unknown variants (string
 * outside the union) hit the runtime fallback returning the raw value. */
const TX_LABEL_KEY: Record<InsiderTransactionType, string> = {
  sale: 'chapter.ownership.tx.sale',
  purchase: 'chapter.ownership.tx.purchase',
  exercise: 'chapter.ownership.tx.exercise',
  other_disposition: 'chapter.ownership.tx.other_disposition',
  grant: 'chapter.ownership.tx.grant',
  award: 'chapter.ownership.tx.award',
  tax_withholding: 'chapter.ownership.tx.tax_withholding',
  conversion: 'chapter.ownership.tx.conversion',
  exercise_otm: 'chapter.ownership.tx.exercise_otm',
  exercise_itm_atm: 'chapter.ownership.tx.exercise_itm_atm',
  disposition_to_issuer: 'chapter.ownership.tx.disposition_to_issuer',
  discretionary: 'chapter.ownership.tx.discretionary',
  equity_swap: 'chapter.ownership.tx.equity_swap',
  tender: 'chapter.ownership.tx.tender',
  voluntary_report: 'chapter.ownership.tx.voluntary_report',
  estate: 'chapter.ownership.tx.estate',
  voting_trust: 'chapter.ownership.tx.voting_trust',
  small_acquisition: 'chapter.ownership.tx.small_acquisition',
  gift: 'chapter.ownership.tx.gift',
  expiration_short: 'chapter.ownership.tx.expiration_short',
  expiration_long: 'chapter.ownership.tx.expiration_long',
  other: 'chapter.ownership.tx.other',
}

function transactionLabel(typ: string, t: Translator): string {
  const key = (TX_LABEL_KEY as Record<string, string | undefined>)[typ]
  if (!key) return typ // backend emitted an unknown variant — show raw
  return t(key)
}

// ---------------------------------------------------------------------------
// Sub-block: Institutional Holdings
// ---------------------------------------------------------------------------

// A holder can legitimately file separate 13F lines for the SAME issuer when
// the issuer has multiple registered share classes (BUG report: GOOGL/GOOG —
// BlackRock/Vanguard each carry a Class A (02079K305) AND a Class C
// (02079K107) line). That is correct SEC data, not a duplicate — but two
// identically-labelled "BlackRock, Inc." rows read as a bug to an analyst.
// We label rather than merge: each row already carries its own `cusip` +
// `ProvenanceLink` to a specific 13F filing, and merging would (a) fabricate
// a combined-class total no single filing reports and (b) silently drop the
// real signal that share-class composition carries (a fund overweighting the
// voting Class A vs the non-voting Class C is itself informative). Class
// labels come straight from the filer's own `title_of_class` (SEC-sourced,
// e.g. "CAP STK CL A") — never an invented ticker guess. Gated on the
// rendered set actually containing >1 distinct class so a single-class
// ticker's table (title_of_class uniformly "COM") never sprouts redundant
// badges.
function shareClassLabel(titleOfClass: string | undefined, t: Translator): string | null {
  if (!titleOfClass) return null
  const trimmed = titleOfClass.trim()
  if (!trimmed) return null
  const m = /\bCL\.?\s*([A-Z0-9]+)\b/i.exec(trimmed)
  if (m) return t('chapter.ownership.shareClass', { letter: m[1].toUpperCase() })
  // Some filers report a generic label ("COMMON" / "CMN") even when the CUSIP
  // is class-specific — that ambiguity is in the SEC filing itself, not
  // something FinRobot can resolve without guessing; show it verbatim (still
  // sourced, never fabricated) rather than inventing a class letter.
  return trimmed
}

function InstitutionTable({
  rows,
  locale,
  t,
}: {
  rows: InstitutionalHoldingShape[]
  locale: 'zh' | 'en'
  t: Translator
}): React.ReactElement {
  const sorted = [...rows].sort((a, b) => b.value_usd - a.value_usd).slice(0, 12)
  const distinctClasses = new Set(
    sorted.map((r) => (r.title_of_class ?? '').trim()).filter((c) => c.length > 0),
  )
  const showClassBadge = distinctClasses.size > 1
  return (
    <TableScroll>
      <table style={tableStyle}>
        <thead>
          <tr>
            <th style={thStyle}>{t('chapter.ownership.col.holder')}</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>{t('chapter.ownership.col.shares')}</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>{t('chapter.ownership.col.value')}</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>
              {t('chapter.ownership.col.changePct')}
            </th>
            <th style={thStyle}>{t('chapter.ownership.col.periodEnd')}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const classLabel = showClassBadge ? shareClassLabel(r.title_of_class, t) : null
            return (
              <tr key={`${r.holder_name}-${r.period_end}-${r.shares}-${i}`}>
                <td style={tdStyle}>
                  <ProvenanceLink prov={r.provenance} locale={locale} t={t}>
                    {r.holder_name}
                  </ProvenanceLink>
                  {classLabel && <span style={shareClassBadgeStyle}>{classLabel}</span>}
                </td>
                <td style={{ ...tdStyle, textAlign: 'right' }}>
                  {formatCompactNumber(r.shares, locale)}
                </td>
                <td style={{ ...tdStyle, textAlign: 'right' }}>
                  {/* 13F value_usd — the field is USD by definition. */}
                  {formatCurrencyCompact(r.value_usd, 'USD', locale)}
                </td>
                <td
                  style={{
                    ...tdStyle,
                    textAlign: 'right',
                    color:
                      r.shares_change_pct === null || r.shares_change_pct === undefined
                        ? 'var(--text-muted)'
                        : r.shares_change_pct > 0
                          ? 'var(--success)'
                          : r.shares_change_pct < 0
                            ? 'var(--danger)'
                            : 'var(--text-muted)',
                  }}
                >
                  {r.shares_change_pct === null || r.shares_change_pct === undefined
                    ? '—'
                    : `${r.shares_change_pct > 0 ? '+' : ''}${formatPercent(r.shares_change_pct, locale, 1, true)}`}
                </td>
                <td style={{ ...tdStyle, color: 'var(--text-muted)' }}>
                  {formatDate(r.period_end, locale)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </TableScroll>
  )
}

// ---------------------------------------------------------------------------
// Sub-block: Proxy Compensation (KvGrid)
// ---------------------------------------------------------------------------

function CompensationGrid({
  comp,
  locale,
  t,
  reportingCurrency,
}: {
  comp: ProxyCompensationShape
  locale: 'zh' | 'en'
  t: Translator
  reportingCurrency: string
}): React.ReactElement {
  const cells: MetricCell[] = [
    {
      label: t('chapter.ownership.kv.ceoName'),
      value: comp.ceo_name ?? '—',
      // When the NAME was overridden by a fresher authority than this proxy (a
      // succession the annual DEF 14A hasn't caught), show where it came from so
      // the reader can trace it — e.g. "per 10-Q cert · Apr 30, 2026".
      sub: ceoNameSourceLabel(comp, locale),
    },
    {
      label: t('chapter.ownership.kv.ceoComp'),
      value:
        comp.ceo_total_compensation !== null && comp.ceo_total_compensation !== undefined
          ? formatCurrencyCompact(comp.ceo_total_compensation, reportingCurrency, locale)
          : '—',
      sub:
        comp.ceo_yoy_change_pct !== null && comp.ceo_yoy_change_pct !== undefined
          ? `${comp.ceo_yoy_change_pct > 0 ? '+' : ''}${formatPercent(comp.ceo_yoy_change_pct, locale, 1, true)} YoY`
          : undefined,
      tone:
        comp.ceo_yoy_change_pct !== null && comp.ceo_yoy_change_pct !== undefined
          ? comp.ceo_yoy_change_pct > 0
            ? 'up'
            : 'down'
          : undefined,
    },
    {
      label: <TermTip term="Pay Ratio">{t('chapter.ownership.kv.payRatio')}</TermTip>,
      value:
        comp.ceo_pay_ratio !== null && comp.ceo_pay_ratio !== undefined
          ? `${comp.ceo_pay_ratio}:1`
          : '—',
    },
  ]
  return (
    <>
      <MetricModule
        title={locale === 'en' ? 'CEO Pay (DEF 14A)' : 'CEO 薪酬（DEF 14A）'}
        accent="violet"
        cells={cells}
        columns={3}
      />
      <p style={kvFooter}>
        <ProvenanceLink prov={makeProvenance(comp)} locale={locale} t={t}>
          {t('chapter.ownership.source.def14a', { date: formatDate(comp.filing_date, locale) })}
        </ProvenanceLink>{' '}
        <TermTip term="DEF 14A" />
      </p>
    </>
  )
}

function makeProvenance(comp: ProxyCompensationShape): FilingProvenanceShape {
  return {
    form: 'DEF 14A',
    filing_date: comp.filing_date,
    accession_no: comp.accession_no,
  }
}

// Sub-label for the CEO name cell when the name came from a fresher authority
// than this DEF 14A. The comp figures are always DEF 14A (panel footer); only
// the NAME can be overridden — by the SOX-302 cert (Ex-31.1 signer of the latest
// 10-Q/10-K, the current CEO by law) or a Form-4 officer title.
function ceoNameSourceLabel(comp: ProxyCompensationShape, locale: 'zh' | 'en'): string | undefined {
  const source = comp.ceo_name_source
  const prov = comp.ceo_name_provenance
  if (!source || source === 'def14a' || !prov) return undefined
  const date = formatDate(prov.filing_date, locale)
  if (source === 'sox302_cert') {
    const form = prov.form || (locale === 'en' ? '10-Q' : '10-Q')
    return locale === 'en' ? `per ${form} cert · ${date}` : `据 ${form} 认证 · ${date}`
  }
  // form4
  return locale === 'en' ? `per Form 4 · ${date}` : `据 Form 4 · ${date}`
}

// ---------------------------------------------------------------------------
// Sub-block: Schedule 13D/G Alerts
// ---------------------------------------------------------------------------

function AlertList({
  rows,
  locale,
  t,
}: {
  rows: ScheduleThirteenAlertShape[]
  locale: 'zh' | 'en'
  t: Translator
}): React.ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {rows.map((r, i) => {
        const isActivist = r.schedule_type === '13D'
        return (
          <div
            // accession+filer alone collides when one filer has multiple 13D/13G
            // rows in the same accession — index disambiguates this display list.
            key={`${r.accession_no}-${r.filer_name}-${i}`}
            style={{
              padding: '10px 14px',
              background: 'var(--bg-card-50)',
              borderLeft: `2px solid ${isActivist ? 'var(--warning)' : 'var(--accent-cyan)'}`,
              borderRadius: '0 var(--radius-sm) var(--radius-sm) 0',
              fontSize: 12.5,
              color: 'var(--text-secondary)',
              lineHeight: 1.55,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
              <strong style={{ color: 'var(--text-primary)' }}>{r.filer_name}</strong>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  padding: '2px 6px',
                  borderRadius: 999,
                  background: isActivist
                    ? 'var(--warning-soft)'
                    : 'color-mix(in srgb, var(--accent-cyan) 18%, transparent)',
                  color: isActivist ? 'var(--warning)' : 'var(--accent-cyan)',
                  letterSpacing: '0.08em',
                }}
              >
                {r.schedule_type}
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  color: 'var(--text-muted)',
                  marginLeft: 'auto',
                }}
              >
                {formatDate(r.filing_date, locale)}
              </span>
            </div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--text-muted)',
                marginTop: 4,
              }}
            >
              {formatCompactNumber(r.shares, locale)} {t('chapter.ownership.alert.shares')}
              {r.pct_of_class !== null && r.pct_of_class !== undefined
                ? ` · ${formatPercent(r.pct_of_class, locale, 2, true)} ${t('chapter.ownership.alert.ofClass')}`
                : ''}
            </div>
            {r.transaction_summary && (
              <div style={{ marginTop: 6, fontSize: 12.5 }}>{r.transaction_summary}</div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

function ProvenanceLink({
  prov,
  locale,
  t,
  children,
}: {
  prov: FilingProvenanceShape
  locale: 'zh' | 'en'
  t: Translator
  children: React.ReactNode
}): React.ReactElement {
  const tooltip = t('chapter.ownership.provenance.tooltip', {
    form: prov.form,
    accession: prov.accession_no,
    date: formatDate(prov.filing_date, locale),
  })
  const inner = (
    <span title={tooltip} style={{ borderBottom: '1px dotted var(--border-soft)' }}>
      {children}
    </span>
  )
  if (prov.source_url) {
    return (
      <a
        href={prov.source_url}
        target="_blank"
        rel="noopener noreferrer"
        style={{ color: 'inherit', textDecoration: 'none' }}
      >
        {inner}
      </a>
    )
  }
  return inner
}

function DegradedPlaceholder({
  reason,
  cta,
}: {
  reason: string
  cta?: { to: string; label: string }
}): React.ReactElement {
  return (
    <div
      style={{
        padding: '14px 18px',
        background: 'color-mix(in srgb, var(--warning) 6%, transparent)',
        border: '1px dashed color-mix(in srgb, var(--warning) 32%, transparent)',
        borderRadius: 'var(--radius-sm)',
        fontFamily: 'var(--font-mono)',
        fontSize: 11.5,
        color: 'var(--warning)',
        lineHeight: 1.5,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <span>⚠ {reason}</span>
      {cta && (
        <Link to={cta.to} style={degradedCtaStyle}>
          {cta.label} →
        </Link>
      )}
    </div>
  )
}

function EmptyNote({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <div
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 11.5,
        color: 'var(--text-muted)',
        padding: '14px 18px',
        background: 'var(--bg-card-50)',
        border: '1px dashed var(--border-soft)',
        borderRadius: 'var(--radius-sm)',
      }}
    >
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const thStyle: CSSProperties = {
  textAlign: 'left',
  padding: '10px 14px',
  fontSize: 10.5,
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
  color: 'var(--text-muted)',
  fontWeight: 500,
  borderBottom: '1px solid var(--border-soft)',
}

const tdStyle: CSSProperties = {
  padding: '10px 14px',
  fontSize: 12,
  color: 'var(--text-secondary)',
  borderBottom: '1px solid var(--border-hairline)',
}

const shareClassBadgeStyle: CSSProperties = {
  marginLeft: 7,
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  letterSpacing: '0.02em',
  color: 'var(--text-muted)',
  border: '1px solid var(--border-soft)',
  borderRadius: 3,
  padding: '1px 5px',
  whiteSpace: 'nowrap',
}

const emptyChapterCallout: CSSProperties = {
  padding: '24px 28px',
  background: 'color-mix(in srgb, var(--accent-cyan) 6%, transparent)',
  borderLeft: '2px solid var(--accent-cyan)',
  borderRadius: '0 var(--radius-sm) var(--radius-sm) 0',
}

const emptyChapterCalloutTitle: CSSProperties = {
  fontFamily: 'var(--font-display)',
  fontSize: 14,
  letterSpacing: '2px',
  color: 'var(--accent-cyan)',
  marginBottom: 10,
}

const emptyChapterCalloutBody: CSSProperties = {
  fontSize: 13,
  lineHeight: 1.7,
  color: 'var(--text-secondary)',
  marginBottom: 14,
}

const emptyChapterCalloutCta: CSSProperties = {
  display: 'inline-block',
  padding: '8px 18px',
  background: 'linear-gradient(135deg, var(--primary), var(--secondary))',
  borderRadius: 'var(--radius-md)',
  fontFamily: 'var(--font-display)',
  fontSize: 12,
  letterSpacing: '2px',
  color: 'var(--text-primary)',
  textDecoration: 'none',
}

const degradedCtaStyle: CSSProperties = {
  alignSelf: 'flex-start',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  color: 'var(--warning)',
  textDecoration: 'none',
  borderBottom: '1px dotted color-mix(in srgb, var(--warning) 50%, transparent)',
  paddingBottom: 1,
}

const kvFooter: CSSProperties = {
  marginTop: 8,
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  color: 'var(--text-muted)',
}
