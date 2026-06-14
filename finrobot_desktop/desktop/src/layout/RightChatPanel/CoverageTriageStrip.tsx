// CoverageTriageStrip — the AI panel's bounded "needs your eyes" triage band.
//
// Deliberately NOT a watchlist. The full self-selected universe is the Coverage
// page's job (and blows up at large N); this strip lists only TODAY'S anomalies —
// names that MOVED hard or whose live price has PASSED my target — capped at
// TRIAGE_MAX. Its height tracks the day's anomaly count, never N: a 120-name desk
// with 2 movers shows 2 cards, the same as a 6-name desk with 2 movers.
//
// The anomaly caliber is deterministic and defined once in coverageTriage.ts,
// which mirrors finrobot/coverage/prompt.py — so the band an analyst sees and the
// snapshot the chat LLM reads flag the exact same names. Clicking a card hands a
// pre-written, caliber-correct question to the chat input (does not auto-send, so
// the analyst can edit); the chevron deep-links to the ticker workspace.
//
// Cosmic spec: inline style + var(--*) only (no App.css coupling — a sibling
// agent owns that file). 涨=success / 跌=danger / 警示=warning. Persistent
// emphasis is a STATIC neon box-shadow halo; no animation, no spinner. Numbers
// render in var(--font-mono).

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCoverageGroups, useCoverageOverview } from '../../hooks/useCoverage'
import { useUiStore } from '../../stores/uiStore'
import { useI18n } from '../../i18n'
import type { Locale } from '../../i18n'
import { formatPercent, formatDate } from '../../utils/format'
import { verdictLabel } from '../../utils/verdict'
import type { CoverageRow } from '../../api/coverage'
import { deriveTriage, TRIAGE_MAX, type TriageItem } from '../../components/coverage/coverageTriage'

// Verdict badge colours — mirror CoverageCard's VERDICT map (one design source of
// truth for BUY/HOLD/SELL). Keyed on the upper-cased verdict so casing variance
// never drops a badge; the legacy WITHHELD display token (or any unknown verdict)
// falls through to neutral rather than crashing, exactly as the card degrades.
const VERDICT_BADGE: Record<string, { color: string; bg: string }> = {
  BUY: { color: 'var(--success)', bg: 'var(--success-soft)' },
  HOLD: { color: 'var(--warning)', bg: 'var(--warning-soft)' },
  SELL: { color: 'var(--danger)', bg: 'var(--danger-soft)' },
}
const VERDICT_NEUTRAL = { color: 'var(--text-muted)', bg: 'var(--neutral-soft)' }

function verdictBadge(verdict: string | null): { color: string; bg: string } {
  if (!verdict) return VERDICT_NEUTRAL
  return VERDICT_BADGE[verdict.toUpperCase()] ?? VERDICT_NEUTRAL
}

// Direction colour for a 1-day move (涨绿跌红); flat/zero stays neutral text.
function changeColor(change: number | null): string {
  if (change === null || change === 0) return 'var(--text)'
  return change > 0 ? 'var(--success)' : 'var(--danger)'
}

// The left-edge halo rail colour: past_target is a warning, a mover follows its
// own direction (up green / down red).
function railColor(item: TriageItem): string {
  if (item.kind === 'past_target') return 'var(--warning)'
  return changeColor(item.row.change_pct_1d)
}

// The pre-written question handed to the chat input. Caliber-correct phrasing so
// the LLM answers against the right denominator (past_target = re-run the DCF;
// mover = explain today's % move).
function promptFor(item: TriageItem, locale: Locale): string {
  const { ticker, target_price, change_pct_1d } = item.row
  if (item.kind === 'past_target') {
    const target = target_price !== null ? formatNum(target_price) : '?'
    return locale === 'zh'
      ? `${ticker} 已越过我的 ${target} 目标价，重算 DCF 看论点是否还成立`
      : `${ticker} has crossed my ${target} target — re-run the DCF and check whether the thesis still holds`
  }
  const move = formatPercent(change_pct_1d, locale, 1, true)
  return locale === 'zh'
    ? `${ticker} 今天 ${move} 的驱动是什么？总结催化剂`
    : `What's driving ${ticker}'s ${move} move today? Summarize the catalyst`
}

// Plain grouped number for inline prose (target price in the prompt / sub-line).
function formatNum(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

interface CoverageTriageStripProps {
  /** Parent passes `messages.length > 0` — start collapsed when a conversation
   *  is already underway so the strip never shoves the thread down on every turn. */
  defaultCollapsed?: boolean
}

export function CoverageTriageStrip({
  defaultCollapsed = false,
}: CoverageTriageStripProps): React.ReactElement | null {
  const { locale } = useI18n()
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(defaultCollapsed)
  // The parent flips defaultCollapsed to true the moment a conversation starts
  // (messages.length > 0). useState only reads a prop at mount, so without this
  // the strip stays expanded through the whole chat and keeps shoving the thread
  // down (the bug). Sync on the 0↔1 boundary: auto-collapse when a conversation
  // begins, re-expand on a fresh/empty session. defaultCollapsed is constant
  // while messages stay non-empty, so this fires ONLY at the transition — a
  // manual expand mid-conversation is preserved, never re-collapsed every turn.
  useEffect(() => {
    setCollapsed(defaultCollapsed)
  }, [defaultCollapsed])

  // Same queryKey as the Coverage page (TanStack dedupes — zero extra request).
  // The system "Studied Tickers" group is the analyst's working universe.
  const groups = useCoverageGroups().data ?? []
  const systemGroup = groups.find((g) => g.is_system) ?? groups[0]
  const { data } = useCoverageOverview(systemGroup?.id ?? null)
  const rows: CoverageRow[] = data?.rows ?? []

  // Cold first paint must stay instant — no skeleton, no shimmer. If there's no
  // group yet or no cached rows, render nothing rather than reserve space.
  if (!systemGroup || rows.length === 0) return null

  const triage = deriveTriage(rows)
  const asOf = data?.generated_at ? formatDate(data.generated_at, locale, 'datetime') : null

  // ── All quiet: one calm line, ~36px, no cards. ───────────────────────────────
  if (triage.length === 0) {
    return (
      <div style={STRIP_SHELL}>
        <div style={{ ...QUIET_ROW }}>
          <span aria-hidden style={dot('var(--success)')} />
          <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            {locale === 'zh'
              ? `覆盖池平静 · ${rows.length} 只均在 ±3% 内，无需动作`
              : `All quiet · ${rows.length} names within ±3%, no action`}
          </span>
        </div>
      </div>
    )
  }

  const shown = triage.slice(0, TRIAGE_MAX)
  const overflow = triage.length - shown.length

  // ── Collapsed: single summary line (auto when a chat is in progress). ─────────
  if (collapsed) {
    const tickers = triage
      .slice(0, 3)
      .map((i) => i.row.ticker)
      .join(' · ')
    return (
      <div style={STRIP_SHELL}>
        <button type="button" onClick={() => setCollapsed(false)} style={COLLAPSED_BTN}>
          <span aria-hidden style={dot('var(--warning)')} />
          <span style={{ color: 'var(--text)', fontSize: 12, fontWeight: 600 }}>
            {locale === 'zh'
              ? `${triage.length} 需要注意`
              : `${triage.length} need${triage.length === 1 ? 's' : ''} a look`}
          </span>
          <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>· {tickers}</span>
          <span aria-hidden style={{ color: 'var(--text-muted)', marginLeft: 'auto' }}>
            ▾
          </span>
        </button>
      </div>
    )
  }

  // ── Expanded: header + up to TRIAGE_MAX cards + optional overflow link. ───────
  return (
    <div style={STRIP_SHELL}>
      <div style={HEADER_ROW}>
        <span
          aria-hidden
          style={{ ...dot('var(--warning)'), boxShadow: '0 0 8px var(--warning-glow)' }}
        />
        <span style={{ color: 'var(--text)', fontSize: 12, fontWeight: 600 }}>
          {locale === 'zh' ? '需要你处理' : 'Needs your eyes'}
        </span>
        <span style={COUNT_PILL}>{triage.length}</span>
        {asOf && (
          <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 'auto' }}>
            {locale === 'zh' ? `截至 ${asOf}` : `as of ${asOf}`}
          </span>
        )}
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          aria-label={locale === 'zh' ? '折叠' : 'Collapse'}
          style={{ ...ICON_BTN, marginLeft: asOf ? 8 : 'auto' }}
        >
          ▴
        </button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {shown.map((item) => (
          <TriageCard key={item.row.ticker} item={item} locale={locale} navigate={navigate} />
        ))}
      </div>

      {overflow > 0 && (
        <button type="button" onClick={() => navigate('/coverage')} style={OVERFLOW_BTN}>
          {locale === 'zh' ? `还有 ${overflow} 条需要注意 →` : `${overflow} more need attention →`}
        </button>
      )}
    </div>
  )
}

interface TriageCardProps {
  item: TriageItem
  locale: Locale
  navigate: (to: string) => void
}

function TriageCard({ item, locale, navigate }: TriageCardProps): React.ReactElement {
  const { row } = item
  const [hover, setHover] = useState(false)
  const badge = verdictBadge(row.latest_verdict)
  const rail = railColor(item)

  const subline =
    item.kind === 'past_target'
      ? locale === 'zh'
        ? `已越过 ${row.target_price !== null ? formatNum(row.target_price) : '?'} 目标`
        : `crossed ${row.target_price !== null ? formatNum(row.target_price) : '?'} target`
      : locale === 'zh'
        ? '今日异动'
        : '1d anomaly'

  const onCardClick = (): void => {
    useUiStore.getState().sendChatPrompt(promptFor(item, locale), false)
  }
  const onChevron = (e: React.MouseEvent): void => {
    e.stopPropagation()
    navigate(`/stocks/${row.ticker}`)
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onCardClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onCardClick()
        }
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        padding: '8px 10px 8px 14px',
        borderRadius: 8,
        cursor: 'pointer',
        background: hover ? 'var(--aipanel-surface-hover)' : 'var(--aipanel-surface)',
        border: `1px solid ${hover ? 'var(--aipanel-line-strong)' : 'var(--aipanel-line)'}`,
        // Static neon halo on the left rail — persistent emphasis, no animation.
        boxShadow: `inset 3px 0 0 0 ${rail}, ${hover ? `0 0 0 1px ${rail}` : 'none'}`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            fontSize: 13,
            color: 'var(--text)',
            letterSpacing: '0.02em',
          }}
        >
          {row.ticker}
        </span>
        {row.latest_verdict && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: '0.04em',
              padding: '1px 6px',
              borderRadius: 4,
              color: badge.color,
              background: badge.bg,
              border: `1px solid ${badge.bg}`,
            }}
          >
            {verdictLabel(row.latest_verdict, locale)}
          </span>
        )}
        {row.change_pct_1d !== null && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              fontWeight: 600,
              color: changeColor(row.change_pct_1d),
            }}
          >
            {formatPercent(row.change_pct_1d, locale, 1, true)}
          </span>
        )}
        {row.price !== null && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              color: 'var(--text-muted)',
              marginLeft: 'auto',
            }}
          >
            {formatNum(row.price)}
            {row.currency ? ` ${row.currency}` : ''}
          </span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span
          style={{
            fontSize: 11,
            color: item.kind === 'past_target' ? 'var(--warning)' : 'var(--text-muted)',
          }}
        >
          {subline}
        </span>
        <span
          role="button"
          tabIndex={0}
          aria-label={locale === 'zh' ? `打开 ${row.ticker}` : `Open ${row.ticker}`}
          onClick={onChevron}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              e.stopPropagation()
              navigate(`/stocks/${row.ticker}`)
            }
          }}
          style={{
            marginLeft: 'auto',
            color: hover ? 'var(--text)' : 'var(--text-muted)',
            fontSize: 13,
            lineHeight: 1,
            cursor: 'pointer',
          }}
        >
          ▸
        </span>
      </div>
    </div>
  )
}

// ── Static style atoms (inline, token-only) ──────────────────────────────────

const STRIP_SHELL: React.CSSProperties = {
  position: 'relative',
  zIndex: 5,
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
  margin: '12px 12px 0',
  padding: '10px 12px',
  border: '1px solid var(--aipanel-line-strong)',
  borderRadius: 11,
  background: 'var(--aipanel-strip)',
}

const QUIET_ROW: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  minHeight: 16,
}

const HEADER_ROW: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
}

const COLLAPSED_BTN: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  width: '100%',
  padding: 0,
  background: 'transparent',
  border: 'none',
  cursor: 'pointer',
  textAlign: 'left',
}

const ICON_BTN: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  color: 'var(--text-muted)',
  cursor: 'pointer',
  fontSize: 12,
  lineHeight: 1,
  padding: 2,
}

const OVERFLOW_BTN: React.CSSProperties = {
  alignSelf: 'flex-start',
  background: 'transparent',
  border: 'none',
  color: 'var(--aip-accent)',
  cursor: 'pointer',
  fontSize: 11,
  padding: '2px 0',
}

const COUNT_PILL: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontWeight: 700,
  color: 'var(--warning)',
  background: 'var(--warning-soft)',
  borderRadius: 10,
  padding: '0 7px',
  lineHeight: '16px',
}

function dot(color: string): React.CSSProperties {
  return {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: color,
    flexShrink: 0,
  }
}
