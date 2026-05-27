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

import { Chapter, KvGrid, SubChapter, tableStyle } from './ChapterBase'
import type {
  FilingProvenanceShape,
  InsiderTransactionShape,
  InstitutionalHoldingShape,
  OwnershipGovernanceShape,
  ProxyCompensationShape,
  ScheduleThirteenAlertShape,
} from './types'
import { useI18n } from '../../../i18n'
import { formatCompactNumber, formatDate, formatPercent } from '../../../utils/format'

interface Props {
  ownership: OwnershipGovernanceShape | null
}

export function ChapterOwnershipGovernance({ ownership }: Props): React.ReactElement {
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
  const insiders = ownership.insider_transactions ?? []
  const holdings = ownership.institutional_holdings ?? []
  const compensation = ownership.proxy_compensation ?? null
  const alerts = ownership.schedule13_alerts ?? []

  return (
    <Chapter id="ownership">
      <SubChapter heading={t('chapter.ownership.heading.insiders')}>
        {degraded.has('insider_transactions') ? (
          <DegradedPlaceholder reason={t('chapter.ownership.degraded.insiders')} />
        ) : insiders.length > 0 ? (
          <InsiderTable rows={insiders} locale={locale} t={t} />
        ) : (
          <EmptyNote>{t('chapter.ownership.empty.insiders')}</EmptyNote>
        )}
      </SubChapter>

      <SubChapter heading={t('chapter.ownership.heading.institutions')}>
        {degraded.has('institutional_holdings') ? (
          <DegradedPlaceholder reason={t('chapter.ownership.degraded.institutions')} />
        ) : holdings.length > 0 ? (
          <InstitutionTable rows={holdings} locale={locale} t={t} />
        ) : (
          <EmptyNote>{t('chapter.ownership.empty.institutions')}</EmptyNote>
        )}
      </SubChapter>

      <SubChapter heading={t('chapter.ownership.heading.compensation')}>
        {degraded.has('proxy_compensation') ? (
          <DegradedPlaceholder reason={t('chapter.ownership.degraded.compensation')} />
        ) : compensation ? (
          <CompensationGrid comp={compensation} locale={locale} t={t} />
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

// ---------------------------------------------------------------------------
// Sub-block: Insider Transactions
// ---------------------------------------------------------------------------

type Translator = (key: string, params?: Record<string, string | number>) => string

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
        {sorted.map((r) => {
          const isBuy = r.transaction_type === 'purchase'
          const isSell = r.transaction_type === 'sale'
          return (
            <tr key={`${r.accession_no}-${r.insider_name}-${r.shares}-${r.value}`}>
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
                  color: isBuy ? 'var(--success)' : isSell ? 'var(--danger)' : 'var(--text-muted)',
                  fontWeight: 500,
                }}
              >
                {transactionLabel(r.transaction_type, t)}
              </td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>
                {formatCompactNumber(r.shares, locale)}
              </td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>
                {r.value > 0 ? `$${formatCompactNumber(r.value, locale)}` : '—'}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function transactionLabel(typ: string, t: Translator): string {
  const key = `chapter.ownership.tx.${typ}`
  const translated = t(key)
  // Fallback to raw value if i18n key not found (Lingui returns key unchanged on miss)
  return translated === key ? typ : translated
}

// ---------------------------------------------------------------------------
// Sub-block: Institutional Holdings
// ---------------------------------------------------------------------------

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
  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <th style={thStyle}>{t('chapter.ownership.col.holder')}</th>
          <th style={{ ...thStyle, textAlign: 'right' }}>{t('chapter.ownership.col.shares')}</th>
          <th style={{ ...thStyle, textAlign: 'right' }}>{t('chapter.ownership.col.value')}</th>
          <th style={{ ...thStyle, textAlign: 'right' }}>{t('chapter.ownership.col.changePct')}</th>
          <th style={thStyle}>{t('chapter.ownership.col.periodEnd')}</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r) => (
          <tr key={`${r.holder_name}-${r.period_end}-${r.shares}`}>
            <td style={tdStyle}>
              <ProvenanceLink prov={r.provenance} locale={locale} t={t}>
                {r.holder_name}
              </ProvenanceLink>
            </td>
            <td style={{ ...tdStyle, textAlign: 'right' }}>
              {formatCompactNumber(r.shares, locale)}
            </td>
            <td style={{ ...tdStyle, textAlign: 'right' }}>
              ${formatCompactNumber(r.value_usd, locale)}
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
                : `${r.shares_change_pct > 0 ? '+' : ''}${formatPercent(r.shares_change_pct / 100, locale, 1)}`}
            </td>
            <td style={{ ...tdStyle, color: 'var(--text-muted)' }}>
              {formatDate(r.period_end, locale)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------------------
// Sub-block: Proxy Compensation (KvGrid)
// ---------------------------------------------------------------------------

function CompensationGrid({
  comp,
  locale,
  t,
}: {
  comp: ProxyCompensationShape
  locale: 'zh' | 'en'
  t: Translator
}): React.ReactElement {
  const cells: { label: string; value: string; delta?: string; tone?: 'up' | 'down' }[] = [
    {
      label: t('chapter.ownership.kv.ceoName'),
      value: comp.ceo_name ?? '—',
    },
    {
      label: t('chapter.ownership.kv.ceoComp'),
      value:
        comp.ceo_total_compensation !== null && comp.ceo_total_compensation !== undefined
          ? `$${formatCompactNumber(comp.ceo_total_compensation, locale)}`
          : '—',
      delta:
        comp.ceo_yoy_change_pct !== null && comp.ceo_yoy_change_pct !== undefined
          ? `${comp.ceo_yoy_change_pct > 0 ? '+' : ''}${formatPercent(comp.ceo_yoy_change_pct / 100, locale, 1)} YoY`
          : undefined,
      tone:
        comp.ceo_yoy_change_pct !== null && comp.ceo_yoy_change_pct !== undefined
          ? comp.ceo_yoy_change_pct > 0
            ? 'up'
            : 'down'
          : undefined,
    },
    {
      label: t('chapter.ownership.kv.payRatio'),
      value:
        comp.ceo_pay_ratio !== null && comp.ceo_pay_ratio !== undefined
          ? `${comp.ceo_pay_ratio}:1`
          : '—',
    },
    {
      label: t('chapter.ownership.kv.peerPercentile'),
      value:
        comp.peer_percentile !== null && comp.peer_percentile !== undefined
          ? `${comp.peer_percentile}th`
          : '—',
    },
  ]
  return (
    <>
      <KvGrid cells={cells} columns={4} />
      <p style={kvFooter}>
        <ProvenanceLink prov={makeProvenance(comp)} locale={locale} t={t}>
          {t('chapter.ownership.source.def14a', { date: formatDate(comp.filing_date, locale) })}
        </ProvenanceLink>
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
      {rows.map((r) => {
        const isActivist = r.schedule_type === '13D'
        return (
          <div
            key={`${r.accession_no}-${r.filer_name}`}
            style={{
              padding: '10px 14px',
              background: 'rgba(15, 15, 34, 0.5)',
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
                  background: isActivist ? 'rgba(217, 119, 6, 0.18)' : 'rgba(34, 211, 238, 0.18)',
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
                ? ` · ${formatPercent(r.pct_of_class / 100, locale, 2)} ${t('chapter.ownership.alert.ofClass')}`
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

function DegradedPlaceholder({ reason }: { reason: string }): React.ReactElement {
  return (
    <div
      style={{
        padding: '14px 18px',
        background: 'rgba(217, 119, 6, 0.06)',
        border: '1px dashed rgba(217, 119, 6, 0.32)',
        borderRadius: 'var(--radius-sm)',
        fontFamily: 'var(--font-mono)',
        fontSize: 11.5,
        color: 'var(--warning)',
        lineHeight: 1.5,
      }}
    >
      ⚠ {reason}
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
        background: 'rgba(15, 15, 34, 0.5)',
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
  borderBottom: '1px solid rgba(255,255,255,0.04)',
}

const emptyChapterCallout: CSSProperties = {
  padding: '24px 28px',
  background: 'rgba(34, 211, 238, 0.06)',
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

const kvFooter: CSSProperties = {
  marginTop: 8,
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  color: 'var(--text-muted)',
}
